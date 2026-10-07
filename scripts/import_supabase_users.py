"""Preview by default. Import identities without changing GameArena user IDs."""
import argparse
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests
from app import app, db, User


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Create managed identities and save links.')
    args = parser.parse_args()
    with app.app_context():
        users = User.query.filter(User.supabase_auth_id.is_(None)).order_by(User.id).all()
        print(f'{len(users)} accounts require import. Business IDs, balances and history are preserved.')
        if not args.apply:
            print('Preview only. Imported accounts will need Forgot password before password sign-in.')
            return
        url = (os.environ.get('SUPABASE_URL') or '').rstrip('/')
        key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY')
        if not url.startswith('https://') or not key:
            raise SystemExit('SUPABASE_URL and server-only SUPABASE_SERVICE_ROLE_KEY are required.')
        headers = {'apikey': key, 'Authorization': 'Bearer ' + key}
        identities = {}
        page = 1
        while True:
            response = requests.get(url + '/auth/v1/admin/users', headers=headers,
                params={'page': page, 'per_page': 100}, timeout=(5, 20))
            if not response.ok:
                raise SystemExit('Unable to inspect managed identities; no secrets or response bodies are printed.')
            batch = response.json().get('users', [])
            identities.update({u['email'].lower(): u for u in batch if u.get('email')})
            if len(batch) < 100:
                break
            page += 1
        for user in users:
            identity = identities.get(user.email.lower())
            if identity:
                # Existing identities require proof through sign-in; never silently
                # attach a preexisting managed identity with an unreviewed email.
                print(f'User {user.id}: existing identity, will link after verified sign-in.')
                continue
            response = requests.post(url + '/auth/v1/admin/users', headers=headers, json={
                'email': user.email, 'password': secrets.token_urlsafe(48),
                'email_confirm': bool(user.email_verified),
                'user_metadata': {'username': user.username}}, timeout=(5, 20))
            if not response.ok:
                raise SystemExit(f'Import stopped at user {user.id}; inspect provider logs, then rerun.')
            identity = response.json()
            if not identity.get('id') or identity.get('email', '').lower() != user.email.lower():
                raise SystemExit(f'Unexpected identity for user {user.id}; stopped.')
            user.supabase_auth_id = identity['id']
            db.session.commit()
            print(f'User {user.id}: imported; password reset required.')


if __name__ == '__main__':
    main()
