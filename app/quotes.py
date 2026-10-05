import logging

import requests

logger = logging.getLogger(__name__)

STOIC_URL = 'https://stoic.tekloon.net/stoic-quote'


def get_quote():
    """Fetch a random stoic quote, returning {'quote', 'author'} or None on failure."""
    try:
        resp = requests.get(STOIC_URL, timeout=5)
        resp.raise_for_status()
        data = resp.json().get('data') or {}
    except (requests.RequestException, ValueError) as e:
        logger.warning('Failed to fetch stoic quote: %s', e)
        return None

    quote = (data.get('quote') or '').strip()
    if not quote:
        return None
    return {'quote': quote, 'author': (data.get('author') or '').strip()}
