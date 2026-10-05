"""One-time Strava authorisation: saves a refresh token with activity:read_all to .env.

Usage:
    uv run python scripts/strava_auth.py

Requires STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET in .env, and the Strava API
app's Authorization Callback Domain set to "localhost". Open the printed URL,
click Authorize, and the token is exchanged and saved automatically.
"""
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import dotenv_values

ENV_PATH = Path(__file__).resolve().parent.parent / '.env'
PORT = 8765
SCOPE = 'read,activity:read_all'


def save_refresh_token(token):
    """Replace (or add) STRAVA_REFRESH_TOKEN in .env, leaving other lines untouched."""
    lines = ENV_PATH.read_text().splitlines(keepends=True)
    new_line = f'STRAVA_REFRESH_TOKEN={token}\n'
    for i, line in enumerate(lines):
        if line.startswith('STRAVA_REFRESH_TOKEN='):
            lines[i] = new_line
            break
    else:
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n'
        lines.append(new_line)
    ENV_PATH.write_text(''.join(lines))


def main():
    env = dotenv_values(ENV_PATH)
    client_id, client_secret = env.get('STRAVA_CLIENT_ID'), env.get('STRAVA_CLIENT_SECRET')
    if not client_id or not client_secret:
        sys.exit('STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET must be set in .env')

    result = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            params = parse_qs(urlparse(self.path).query)
            if 'code' not in params:
                self.send_response(204)
                self.end_headers()
                return

            resp = requests.post('https://www.strava.com/oauth/token', data={
                'client_id': client_id,
                'client_secret': client_secret,
                'code': params['code'][0],
                'grant_type': 'authorization_code',
            }, timeout=15)
            data = resp.json()
            if resp.status_code == 200:
                save_refresh_token(data['refresh_token'])
                result['ok'] = True
                result['scope'] = params.get('scope', [''])[0]
                message = 'Strava connected. You can close this tab.'
            else:
                result['error'] = data
                message = 'Strava authorisation failed. Check the terminal.'

            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(message.encode())

        def log_message(self, *args):
            pass  # keep the terminal quiet

    url = 'https://www.strava.com/oauth/authorize?' + urlencode({
        'client_id': client_id,
        'response_type': 'code',
        'redirect_uri': f'http://localhost:{PORT}',
        'approval_prompt': 'force',
        'scope': SCOPE,
    })
    print(f'Open this URL and click Authorize:\n\n{url}\n', flush=True)

    server = HTTPServer(('localhost', PORT), Callback)
    server.timeout = 600
    server.handle_timeout = lambda: result.setdefault('error', 'timed out waiting for Strava')
    while not result:
        server.handle_request()

    if result.get('ok'):
        print(f'Saved STRAVA_REFRESH_TOKEN to .env (scope: {result["scope"]})')
    else:
        sys.exit(f'Failed: {result["error"]}')


if __name__ == '__main__':
    main()
