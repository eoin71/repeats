import logging
import os
from datetime import date, datetime, time, timedelta

import requests

logger = logging.getLogger(__name__)

BASE_URL = 'https://intervals.icu'
# Cloudflare blocks requests with the default python-requests User-Agent (HTTP 403).
HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json',
}

_athlete_id = None


def _api_key():
    return os.environ.get('INTERVALS_ICU_API_KEY')


def _auth():
    return requests.auth.HTTPBasicAuth('API_KEY', _api_key())


def get_athlete_id():
    """Return the athlete id, discovering it via /athletes on first call."""
    global _athlete_id

    override = os.environ.get('INTERVALS_ICU_ATHLETE_ID')
    if override:
        return override
    if _athlete_id:
        return _athlete_id

    key = _api_key()
    if not key:
        return None

    try:
        resp = requests.get(
            f'{BASE_URL}/api/v1/athletes',
            headers=HEADERS,
            auth=_auth(),
            timeout=10,
        )
        resp.raise_for_status()
        athletes = resp.json()
        if athletes:
            _athlete_id = athletes[0]['id']
            return _athlete_id
    except (requests.RequestException, ValueError, KeyError, IndexError) as e:
        logger.warning('Failed to discover intervals.icu athlete id: %s', e)

    return None


def _summarize_event(event):
    """Map a raw calendar event to the fields the week view needs."""
    start = event.get('start_date_local') or ''
    event_date = None
    start_time = None
    if start:
        try:
            start_dt = datetime.fromisoformat(start)
            event_date = start_dt.date()
            # Events without a planned time come back at midnight
            if start_dt.time() != time.min:
                start_time = start_dt
        except ValueError:
            pass

    return {
        'date': event_date,
        'start': start_time,
        'name': event.get('name') or 'Workout',
        'type': event.get('type') or 'Workout',
        'duration': event.get('moving_time'),
        'load': event.get('icu_training_load'),
        'description': event.get('description') or '',
        'category': event.get('category'),
        'completed': event.get('paired_activity_id') is not None,
    }


def get_week_events(monday):
    """Return summarized calendar events for the Mon-Sun week starting at monday.

    Returns a list of dicts, or None if the plan could not be fetched.
    """
    athlete_id = get_athlete_id()
    key = _api_key()
    if not athlete_id or not key:
        return None

    sunday = monday + timedelta(days=6)
    try:
        resp = requests.get(
            f'{BASE_URL}/api/v1/athlete/{athlete_id}/events',
            params={'oldest': monday.isoformat(), 'newest': sunday.isoformat()},
            headers=HEADERS,
            auth=_auth(),
            timeout=10,
        )
        resp.raise_for_status()
        events = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning('Failed to fetch intervals.icu events: %s', e)
        return None

    if not isinstance(events, list):
        return None

    return [_summarize_event(e) for e in events]


def get_wellness_series(days=42):
    """Return daily fitness (CTL) / fatigue (ATL) history for the last `days` days.

    Returns a list of dicts sorted by date:
        [{'date': 'YYYY-MM-DD', 'fitness': float, 'fatigue': float}, ...]
    or None if the data could not be fetched.
    """
    athlete_id = get_athlete_id()
    key = _api_key()
    if not athlete_id or not key:
        return None

    newest = date.today()
    oldest = newest - timedelta(days=days)

    try:
        resp = requests.get(
            f'{BASE_URL}/api/v1/athlete/{athlete_id}/wellness',
            params={'oldest': oldest.isoformat(), 'newest': newest.isoformat()},
            headers=HEADERS,
            auth=_auth(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning('Failed to fetch intervals.icu wellness data: %s', e)
        return None

    if not isinstance(data, list):
        return None

    series = []
    for record in data:
        ctl = record.get('ctl')
        atl = record.get('atl')
        if ctl is None or atl is None:
            continue
        record_date = record.get('id') or record.get('date')
        if not record_date:
            continue
        series.append({
            'date': record_date,
            'fitness': float(ctl),
            'fatigue': float(atl),
        })

    series.sort(key=lambda r: r['date'])
    return series or None
