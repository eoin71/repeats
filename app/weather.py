import logging
import math
import os
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from flask import current_app, has_app_context

logger = logging.getLogger(__name__)

# Met Éireann open data point forecast (HARMONIE for ~48h, then ECMWF). HTTP only.
MET_URL = 'http://openaccess.pf.api.met.ie/metno-wdb2ts/locationforecast'
TZ = ZoneInfo('Europe/Dublin')
CACHE_SECONDS = 3600
STALE_MAX_SECONDS = 12 * 3600    # oldest forecast to fall back on when a fetch fails
RETRY_AFTER_SECONDS = 300        # after a failed fetch, don't retry (and block pages) for this long
TIMEOUT = (5, 20)                # (connect, read) seconds
DEFAULT_RIDE_HOURS = 2

# Outdoor cycling activity types from intervals.icu (VirtualRide is indoors)
CYCLING_TYPES = {
    'Ride', 'GravelRide', 'MountainBikeRide', 'EBikeRide', 'EMountainBikeRide', 'Velomobile',
}

# Piecewise-linear curves mapping a measurement to a 0-1 factor
RAIN_CURVE = [(0, 1.0), (0.2, 0.8), (1, 0.5), (2.5, 0.25), (4, 0.1)]            # mm/h
WIND_CURVE = [(15, 1.0), (25, 0.75), (35, 0.5), (45, 0.15)]                     # km/h
GUST_CURVE = [(40, 1.0), (55, 0.6), (65, 0.1)]                                  # km/h
TEMP_CURVE = [(-5, 0.3), (2, 0.5), (5, 0.8), (12, 1.0), (22, 1.0), (28, 0.8), (35, 0.4)]  # feels-like °C
WET_ROAD_FACTOR = 0.85
ICE_FACTOR = 0.3

LABELS = [(8, 'great'), (6, 'good'), (4, 'rideable'), (2, 'grim'), (0, 'turbo-trainer day')]

_cache = {'fetched_at': 0.0, 'hours': None, 'retry_after': 0.0}


def _location():
    lat = float(os.environ.get('WEATHER_LAT', 53.3190))
    lon = float(os.environ.get('WEATHER_LON', -6.3035))
    return lat, lon


def _parse_time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _download():
    """Fetch the raw forecast XML from Met Éireann."""
    lat, lon = _location()
    # Met Éireann expects ';' separated params, so build the query by hand
    resp = requests.get(f'{MET_URL}?lat={lat};long={lon}', timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.content


def _parse_hours(content):
    """Flatten forecast XML into hourly records (local time).

    Instant readings (temperature, wind, humidity) are carried forward to fill
    gaps, and precipitation intervals (1h near-term, 3-6h later) are spread
    evenly over the hours they cover, preferring the shortest interval.
    """
    root = ET.fromstring(content)

    instants = {}
    intervals = []
    for node in root.iter('time'):
        start, end = _parse_time(node.get('from')), _parse_time(node.get('to'))
        loc = node.find('location')
        if loc is None:
            continue
        if start == end:
            temp = loc.find('temperature')
            wind = loc.find('windSpeed')
            if temp is None or wind is None:
                continue
            gust = loc.find('windGust')
            direction = loc.find('windDirection')
            humidity = loc.find('humidity')
            instants[start] = {
                'temp': float(temp.get('value')),
                'wind': float(wind.get('mps')) * 3.6,
                'gust': float(gust.get('mps')) * 3.6 if gust is not None else None,
                'wind_dir': direction.get('name') if direction is not None else '',
                'humidity': float(humidity.get('value')) if humidity is not None else None,
            }
        else:
            precip = loc.find('precipitation')
            symbol = loc.find('symbol')
            if precip is None:
                continue
            intervals.append((start, end, float(precip.get('value') or 0), symbol.get('id') if symbol is not None else None))

    # Longest intervals first so shorter (more precise) ones overwrite them
    rain_by_hour = {}
    for start, end, total, symbol in sorted(intervals, key=lambda i: i[0] - i[1]):
        step = int((end - start).total_seconds() // 3600)
        for i in range(step):
            rain_by_hour[start + timedelta(hours=i)] = (total / step, symbol, step)

    hours = []
    instant_times = sorted(instants)
    idx = 0
    for hour in sorted(rain_by_hour):
        # Latest instant reading at or before this hour
        while idx + 1 < len(instant_times) and instant_times[idx + 1] <= hour:
            idx += 1
        if not instant_times or instant_times[idx] > hour:
            continue
        rain, symbol, step = rain_by_hour[hour]
        hours.append({
            'time': hour.astimezone(TZ),
            'rain': rain,
            'symbol': symbol,
            'step': step,
            **instants[instant_times[idx]],
        })
    return hours


def _cache_file():
    """Forecast saved in the instance folder, shared by all workers; None outside a request."""
    if not has_app_context():
        return None
    return Path(current_app.instance_path) / 'met_forecast.xml'


def _read_cache_file():
    """Return (xml bytes, age in seconds) of the saved forecast, or (None, None)."""
    path = _cache_file()
    try:
        return path.read_bytes(), time.time() - path.stat().st_mtime
    except (OSError, AttributeError):
        return None, None


def _write_cache_file(content):
    path = _cache_file()
    if path is None:
        return
    try:
        tmp = path.with_suffix('.tmp')
        tmp.write_bytes(content)
        tmp.replace(path)  # atomic, so other workers never read a half-written file
    except OSError as e:
        logger.warning('Met Éireann: could not save forecast to %s: %s', path, e)


def _get_hours():
    """Return hourly forecast records, refetching after CACHE_SECONDS.

    Checks, in order: this worker's memory, the forecast saved on disk by any
    worker, then Met Éireann. If the fetch fails, the newest saved forecast up
    to STALE_MAX_SECONDS old is used and fetching pauses for RETRY_AFTER_SECONDS.
    """
    now = time.time()
    if _cache['hours'] is not None and now - _cache['fetched_at'] < CACHE_SECONDS:
        return _cache['hours']

    content, age = _read_cache_file()
    if content is not None and age < CACHE_SECONDS:
        try:
            hours = _parse_hours(content)
            _cache.update(fetched_at=now - age, hours=hours)
            logger.debug('Met Éireann: using forecast saved %.0f min ago', age / 60)
            return hours
        except (ET.ParseError, ValueError, TypeError) as e:
            logger.warning('Met Éireann: saved forecast is unreadable (%s); refetching', e)

    if now < _cache['retry_after']:
        return _stale_hours(content, age, log=False)

    started = time.monotonic()
    try:
        content = _download()
        hours = _parse_hours(content)
    except (requests.RequestException, ET.ParseError, ValueError, TypeError) as e:
        logger.error(
            'Met Éireann: forecast fetch failed after %.1f s: %s: %s. Not retrying for %d min',
            time.monotonic() - started, e.__class__.__name__, e, RETRY_AFTER_SECONDS // 60,
        )
        _cache['retry_after'] = now + RETRY_AFTER_SECONDS
        return _stale_hours(*_read_cache_file())

    _write_cache_file(content)
    _cache.update(fetched_at=now, hours=hours, retry_after=0.0)
    logger.info(
        'Met Éireann: fetched forecast in %.1f s (%d KB, %d hours to %s)',
        time.monotonic() - started, len(content) // 1024, len(hours),
        hours[-1]['time'].strftime('%a %d %b') if hours else 'n/a',
    )
    return hours


def _stale_hours(content, age, log=True):
    """Fallback after a failed fetch: memory, else a saved forecast within STALE_MAX_SECONDS."""
    if _cache['hours'] is not None and time.time() - _cache['fetched_at'] < STALE_MAX_SECONDS:
        return _cache['hours']
    if content is not None and age < STALE_MAX_SECONDS:
        try:
            hours = _parse_hours(content)
        except (ET.ParseError, ValueError, TypeError):
            return None
        if log:
            logger.warning('Met Éireann: using saved forecast from %.1f h ago', age / 3600)
        _cache.update(fetched_at=time.time() - age, hours=hours)
        return hours
    if log:
        logger.warning('Met Éireann: no forecast available (nothing saved in the last %d h)', STALE_MAX_SECONDS // 3600)
    return None


def _interp(x, curve):
    """Linearly interpolate x along a curve of (x, factor) points, clamped at the ends."""
    if x <= curve[0][0]:
        return curve[0][1]
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return curve[-1][1]


def _feels_like(temp, wind_kmh):
    """Wind chill (°C) where it applies, otherwise the air temperature."""
    if temp <= 10 and wind_kmh > 4.8:
        v = wind_kmh ** 0.16
        return 13.12 + 0.6215 * temp - 11.37 * v + 0.3965 * temp * v
    return temp


def _hour_score(hour, previous):
    """Score one hour 0-1 as the product of rain, wind, temperature and road factors."""
    rain = _interp(hour['rain'], RAIN_CURVE)
    wind = _interp(hour['wind'], WIND_CURVE)
    if hour['gust'] is not None:
        wind = min(wind, _interp(hour['gust'], GUST_CURVE))
    temp = _interp(_feels_like(hour['temp'], hour['wind']), TEMP_CURVE)

    recent_rain = any(h['rain'] >= 0.1 for h in previous)
    road = 1.0
    if hour['temp'] <= 2 and (recent_rain or hour['rain'] >= 0.1):
        road = ICE_FACTOR
    elif recent_rain and hour['rain'] < 0.1:
        road = WET_ROAD_FACTOR

    return rain * wind * temp * road


def _sun_times(day):
    """Approximate local sunrise and sunset (NOAA solar equations)."""
    lat, lon = _location()
    gamma = 2 * math.pi / 365 * (day.timetuple().tm_yday - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    lat_r = math.radians(lat)
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(lat_r) * math.cos(decl))
              - math.tan(lat_r) * math.tan(decl))
    ha = math.degrees(math.acos(max(-1.0, min(1.0, cos_ha))))
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    sunrise = midnight + timedelta(minutes=720 - 4 * (lon + ha) - eqtime)
    sunset = midnight + timedelta(minutes=720 - 4 * (lon - ha) - eqtime)
    return sunrise.astimezone(TZ), sunset.astimezone(TZ)


def _scored_hours(hours):
    """Hourly records with a cycleability score, using the prior 3 hours for wet roads."""
    return [{**hour, 'score': _hour_score(hour, hours[max(0, i - 3):i])} for i, hour in enumerate(hours)]


def _daylight_hours(hours, day):
    """Scored hourly records for a day whose midpoint falls between sunrise and sunset."""
    sunrise, sunset = _sun_times(day)
    return [
        hour for hour in _scored_hours(hours)
        if hour['time'].date() == day and sunrise <= hour['time'] + timedelta(minutes=30) <= sunset
    ]


def _planned_window(hours, start, duration):
    """Mean score over the hours a ride is planned for, or None if not forecast.

    `start` is a naive local datetime; any hour overlapping the ride counts.
    """
    start = start.replace(tzinfo=TZ)
    end = start + timedelta(seconds=duration or DEFAULT_RIDE_HOURS * 3600)
    window = [
        hour for hour in _scored_hours(hours)
        if hour['time'] < end and hour['time'] + timedelta(hours=1) > start
    ]
    if not window:
        return None
    return sum(h['score'] for h in window) / len(window), window


def _best_window(daylight, length):
    """Best consecutive run of `length` hours by mean score (whole day if shorter)."""
    length = max(1, min(length, len(daylight)))
    best = None
    for i in range(len(daylight) - length + 1):
        window = daylight[i:i + length]
        if window[-1]['time'] - window[0]['time'] != timedelta(hours=length - 1):
            continue  # skip gaps in the forecast
        mean = sum(h['score'] for h in window) / length
        if best is None or mean > best[0]:
            best = (mean, window)
    return best


def _icon(symbol):
    """Emoji for a Met Éireann weather symbol id."""
    s = (symbol or '').lower().replace('dark_', '')
    if 'thunder' in s:
        return '⛈️'
    if 'snow' in s or 'sleet' in s:
        return '🌨️'
    if 'rain' in s or 'drizzle' in s:
        return '🌦️' if 'sun' in s else '🌧️'
    if 'fog' in s:
        return '🌫️'
    if 'partlycloud' in s:
        return '⛅'
    if 'lightcloud' in s:
        return '🌤️'
    if 'cloud' in s:
        return '☁️'
    if 'sun' in s:
        return '☀️'
    return '☁️'


def _label(score):
    return next(label for threshold, label in LABELS if score >= threshold)


def _summarize(window):
    mean, hours = window
    score = round(mean * 10, 1)
    symbol = Counter(h['symbol'] for h in hours).most_common(1)[0][0]
    return {
        'score': score,
        'label': _label(score),
        'icon': _icon(symbol),
        'start': hours[0]['time'].strftime('%H:%M'),
        'end': (hours[-1]['time'] + timedelta(hours=1)).strftime('%H:%M'),
    }


def day_forecast(day):
    """Cycleability and general weather for a day's daylight hours, or None."""
    hours = _get_hours()
    if not hours:
        return None
    daylight = _daylight_hours(hours, day)
    window = _best_window(daylight, DEFAULT_RIDE_HOURS) if daylight else None
    if not window:
        return None

    summary = _summarize(window)
    symbol = Counter(h['symbol'] for h in daylight).most_common(1)[0][0]
    humidity = [h['humidity'] for h in daylight if h['humidity'] is not None]
    gusts = [h['gust'] for h in daylight if h['gust'] is not None]
    summary.update({
        'date': day,
        'icon': _icon(symbol),
        'temp_min': round(min(h['temp'] for h in daylight)),
        'temp_max': round(max(h['temp'] for h in daylight)),
        'wind': round(sum(h['wind'] for h in daylight) / len(daylight)),
        'gust': round(max(gusts)) if gusts else None,
        'wind_dir': Counter(h['wind_dir'] for h in daylight).most_common(1)[0][0],
        'humidity': round(sum(humidity) / len(humidity)) if humidity else None,
        'rain': round(sum(h['rain'] for h in daylight), 1),
        # Beyond ~48h the forecast is coarser (3-6h steps) and less reliable
        'confident': all(h['step'] == 1 for h in daylight),
    })
    return summary


def next_forecast():
    """Forecast for today, or tomorrow once today's daylight has passed."""
    today = datetime.now(TZ).date()
    return day_forecast(today) or day_forecast(today + timedelta(days=1))


def activity_score(event):
    """Cycleability for a planned outdoor ride.

    Scores the ride's planned hours when it has a start time, otherwise the
    best daylight window as long as the ride. Returns None for non-cycling
    events, completed rides or days without a forecast.
    """
    if event.get('type') not in CYCLING_TYPES or event.get('completed') or not event.get('date'):
        return None
    hours = _get_hours()
    if not hours:
        return None

    duration = event.get('duration')
    if event.get('start'):
        window = _planned_window(hours, event['start'], duration)
    else:
        daylight = _daylight_hours(hours, event['date'])
        length = math.ceil(duration / 3600) if duration else DEFAULT_RIDE_HOURS
        window = _best_window(daylight, length) if daylight else None
    if not window:
        return None

    summary = _summarize(window)
    summary['planned'] = bool(event.get('start'))
    summary['confident'] = all(h['step'] == 1 for h in window[1])
    return summary
