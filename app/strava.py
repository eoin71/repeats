import json
import logging
import math
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from flask import current_app

logger = logging.getLogger(__name__)

TOKEN_URL = 'https://www.strava.com/oauth/token'
API_URL = 'https://www.strava.com/api/v3'
TZ = ZoneInfo('Europe/Dublin')
CACHE_SECONDS = 900

# Strava sport types counted as rides (including indoor)
RIDE_TYPES = {
    'Ride', 'GravelRide', 'MountainBikeRide', 'EBikeRide', 'EMountainBikeRide',
    'VirtualRide', 'Velomobile', 'Handcycle',
}

_token = {'access_token': None, 'expires_at': 0}
_cache = {}
_warned_unconfigured = False

REQUIRED_SETTINGS = ('STRAVA_CLIENT_ID', 'STRAVA_CLIENT_SECRET', 'STRAVA_REFRESH_TOKEN')


class StravaError(Exception):
    """A Strava call failed; the message is safe to log (contains no secrets)."""


def _token_file():
    return Path(current_app.instance_path) / 'strava_token.json'


def _error_detail(resp):
    """Short description of a failed Strava response, e.g. '401 Authorization Error (...)'."""
    try:
        body = resp.json()
        errors = '; '.join(
            f"{e.get('resource')}.{e.get('field')}: {e.get('code')}" for e in body.get('errors', [])
        )
        detail = body.get('message', '')
        return f'{resp.status_code} {detail}' + (f' ({errors})' if errors else '')
    except ValueError:
        return f'{resp.status_code} {resp.text[:200]}'


def _log_rate_limits(resp):
    """Log Strava's read rate-limit usage from response headers, warning above 80%."""
    usage = resp.headers.get('X-ReadRateLimit-Usage') or resp.headers.get('X-RateLimit-Usage')
    limit = resp.headers.get('X-ReadRateLimit-Limit') or resp.headers.get('X-RateLimit-Limit')
    if not usage or not limit:
        return
    try:
        (used_15m, used_day), (limit_15m, limit_day) = (
            [int(n) for n in usage.split(',')][:2], [int(n) for n in limit.split(',')][:2]
        )
    except ValueError:
        return
    level = logging.WARNING if used_15m > 0.8 * limit_15m or used_day > 0.8 * limit_day else logging.INFO
    logger.log(level, 'Strava API usage: %d/%d (15 min), %d/%d (daily)', used_15m, limit_15m, used_day, limit_day)


def _refresh_token():
    """Latest refresh token and where it came from.

    Strava can issue a new refresh token on each refresh, invalidating the old
    one, so the newest is kept in the instance folder (which persists in Docker).
    A saved token is ignored once STRAVA_REFRESH_TOKEN is changed.
    """
    env_token = os.environ.get('STRAVA_REFRESH_TOKEN')
    try:
        saved = json.loads(_token_file().read_text())
    except FileNotFoundError:
        return env_token, 'env'
    except (OSError, ValueError) as e:
        logger.warning('Strava: could not read saved token file %s (%s); using STRAVA_REFRESH_TOKEN', _token_file(), e)
        return env_token, 'env'
    if saved.get('env_token') == env_token and saved.get('refresh_token'):
        return saved['refresh_token'], 'saved file'
    return env_token, 'env'


def _access_token():
    """Return a valid access token, refreshing it when it's about to expire.

    Returns None if Strava isn't configured; raises StravaError if the refresh fails.
    """
    global _warned_unconfigured

    if _token['access_token'] and _token['expires_at'] - 60 > time.time():
        return _token['access_token']

    missing = [name for name in REQUIRED_SETTINGS if not os.environ.get(name)]
    if missing:
        if not _warned_unconfigured:
            logger.warning('Strava disabled: missing %s', ', '.join(missing))
            _warned_unconfigured = True
        return None

    refresh_token, source = _refresh_token()
    started = time.monotonic()
    try:
        resp = requests.post(TOKEN_URL, data={
            'client_id': os.environ['STRAVA_CLIENT_ID'],
            'client_secret': os.environ['STRAVA_CLIENT_SECRET'],
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token',
        }, timeout=10)
    except requests.RequestException as e:
        raise StravaError(f'token refresh request failed: {e.__class__.__name__}: {e}') from None

    if resp.status_code != 200:
        hint = ''
        if resp.status_code in (400, 401):
            hint = ' - the refresh token or client credentials are invalid; re-run scripts/strava_auth.py and update STRAVA_REFRESH_TOKEN'
        raise StravaError(f'token refresh failed (refresh token from {source}): {_error_detail(resp)}{hint}')

    data = resp.json()
    _token.update(access_token=data['access_token'], expires_at=data['expires_at'])
    logger.info(
        'Strava: access token refreshed in %.0f ms (refresh token from %s), valid until %s',
        (time.monotonic() - started) * 1000, source,
        datetime.fromtimestamp(data['expires_at'], TZ).strftime('%H:%M'),
    )

    if data.get('refresh_token') and data['refresh_token'] != refresh_token:
        try:
            _token_file().write_text(json.dumps({
                'env_token': os.environ.get('STRAVA_REFRESH_TOKEN'),
                'refresh_token': data['refresh_token'],
            }))
            logger.info('Strava: issued a new refresh token; saved to %s', _token_file())
        except OSError as e:
            logger.error(
                'Strava: issued a new refresh token but it could not be saved to %s (%s). '
                'The old token may stop working; check the instance volume is writable',
                _token_file(), e,
            )
    return _token['access_token']


def _decode_polyline(encoded):
    """Decode a Google encoded polyline into (lat, lng) pairs."""
    points, index, lat, lng = [], 0, 0, 0
    while index < len(encoded):
        for is_lng in (False, True):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if is_lng:
                lng += delta
            else:
                lat += delta
        points.append((lat / 1e5, lng / 1e5))
    return points


def _route_svg(encoded, width=280, height=180, pad=8):
    """Project a polyline into an SVG path that fits width x height, or None."""
    points = _decode_polyline(encoded or '')
    if len(points) < 2:
        return None

    # Equirectangular projection, scaling longitude by latitude so shapes aren't stretched
    mid_lat = math.radians(sum(p[0] for p in points) / len(points))
    xs = [p[1] * math.cos(mid_lat) for p in points]
    ys = [-p[0] for p in points]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    span = max(max_x - min_x, max_y - min_y) or 1
    scale = min((width - 2 * pad) / ((max_x - min_x) or span), (height - 2 * pad) / ((max_y - min_y) or span))
    off_x = (width - (max_x - min_x) * scale) / 2
    off_y = (height - (max_y - min_y) * scale) / 2
    coords = [((x - min_x) * scale + off_x, (y - min_y) * scale + off_y) for x, y in zip(xs, ys)]

    path = f'M {coords[0][0]:.1f} {coords[0][1]:.1f} ' + ' '.join(f'L {x:.1f} {y:.1f}' for x, y in coords[1:])
    return {'path': path, 'width': width, 'height': height, 'start': coords[0], 'end': coords[-1]}


def _summarize(activity):
    """Map a Strava activity to the fields the week view needs."""
    # Strava marks start_date_local with a 'Z' but it's already local time
    start = datetime.fromisoformat(activity['start_date_local'].rstrip('Z'))
    speed = activity.get('average_speed')
    max_speed = activity.get('max_speed')
    return {
        'id': activity['id'],
        'name': activity.get('name') or 'Ride',
        'type': activity.get('sport_type') or activity.get('type'),
        'start': start,
        'date': start.date(),
        'distance_km': round((activity.get('distance') or 0) / 1000, 1),
        'moving_time': activity.get('moving_time'),
        'elevation': round(activity.get('total_elevation_gain') or 0),
        'avg_speed': round(speed * 3.6, 1) if speed else None,
        'max_speed': round(max_speed * 3.6, 1) if max_speed else None,
        'avg_watts': round(activity['average_watts']) if activity.get('average_watts') else None,
        'np': activity.get('weighted_average_watts'),
        'max_watts': activity.get('max_watts'),
        'kj': round(activity['kilojoules']) if activity.get('kilojoules') else None,
        'avg_hr': round(activity['average_heartrate']) if activity.get('average_heartrate') else None,
        'max_hr': round(activity['max_heartrate']) if activity.get('max_heartrate') else None,
        'cadence': round(activity['average_cadence']) if activity.get('average_cadence') else None,
        'relative_effort': round(activity['suffer_score']) if activity.get('suffer_score') else None,
        'prs': activity.get('pr_count') or 0,
        'achievements': activity.get('achievement_count') or 0,
        'temp': activity.get('average_temp'),
        'trainer': activity.get('trainer'),
        'url': f"https://www.strava.com/activities/{activity['id']}",
        'route': _route_svg((activity.get('map') or {}).get('summary_polyline')),
    }


def get_week_rides(monday):
    """Return summarized Strava rides for the Mon-Sun week starting at monday.

    Returns a list of dicts, or None if Strava isn't configured or the fetch
    failed (stale cached rides are returned instead when available).
    """
    cached = _cache.get(monday)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        logger.debug('Strava: using cached rides for week of %s', monday)
        return cached[1]

    start = datetime(monday.year, monday.month, monday.day, tzinfo=TZ)
    end = start + timedelta(days=7)
    try:
        token = _access_token()
        if not token:
            return None

        started = time.monotonic()
        resp = requests.get(
            f'{API_URL}/athlete/activities',
            headers={'Authorization': f'Bearer {token}'},
            params={'after': int(start.timestamp()), 'before': int(end.timestamp()), 'per_page': 100},
            timeout=10,
        )
        elapsed_ms = (time.monotonic() - started) * 1000
        _log_rate_limits(resp)

        if resp.status_code == 401:
            _token.update(access_token=None, expires_at=0)  # force a refresh next time
            raise StravaError(f'activities request unauthorised: {_error_detail(resp)} - check the token has activity:read_all scope')
        if resp.status_code == 429:
            raise StravaError(f'rate limit exceeded: {_error_detail(resp)}')
        if resp.status_code != 200:
            raise StravaError(f'activities request failed: {_error_detail(resp)}')

        activities = resp.json()
        rides = [_summarize(a) for a in activities if (a.get('sport_type') or a.get('type')) in RIDE_TYPES]
    except StravaError as e:
        logger.error('Strava: %s', e)
    except requests.RequestException as e:
        logger.error('Strava: activities request failed: %s: %s', e.__class__.__name__, e)
    except (ValueError, KeyError, TypeError) as e:
        logger.exception('Strava: could not parse activities response: %s', e)
    else:
        logger.info(
            'Strava: fetched %d activities (%d rides) for week of %s in %.0f ms',
            len(activities), len(rides), monday, elapsed_ms,
        )
        _cache[monday] = (time.time(), rides)
        return rides

    if cached:
        logger.warning('Strava: serving cached rides for week of %s from %s', monday,
                       datetime.fromtimestamp(cached[0], TZ).strftime('%H:%M'))
        return cached[1]
    return None


def match_rides(events, rides, is_ride_event):
    """Attach each ride to the planned ride event it best fits, as event['ride'].

    A ride matches a planned ride on the same day, preferring the one whose
    planned start is closest. Returns the rides that matched nothing.
    """
    unmatched = sorted(rides, key=lambda r: r['start'])
    for event in events:
        if not is_ride_event(event):
            continue
        same_day = [r for r in unmatched if r['date'] == event['date']]
        if not same_day:
            continue
        planned = event.get('start') or datetime.combine(event['date'], datetime.min.time()).replace(hour=12)
        ride = min(same_day, key=lambda r: abs(r['start'] - planned))
        event['ride'] = ride
        unmatched.remove(ride)
    matched = len(rides) - len(unmatched)
    if rides:
        logger.info('Strava: matched %d ride(s) to planned workouts, %d unplanned', matched, len(unmatched))
    return unmatched
