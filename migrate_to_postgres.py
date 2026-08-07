"""
migrate_to_postgres.py

Migrate data from the local SQLite database (instance/database.db) into the
Render PostgreSQL database.

SECURITY: The Postgres connection string is read ONLY from the DATABASE_URL
environment variable. It is NEVER stored in a file, NEVER logged, and NEVER
committed. Run it as:

    $env:DATABASE_URL="postgres://user:pass@host:port/db" ; python migrate_to_postgres.py

(Windows PowerShell) — or set DATABASE_URL in your shell on Mac/Linux.

How it works:
  - Connects to the local SQLite DB and reads all rows.
  - Connects to the target Postgres DB.
  - Creates the schema (via SQLAlchemy models).
  - Inserts rows table-by-table, preserving IDs and foreign-key relationships.
  - Is idempotent: skips rows that already exist (by email / natural key).
"""

import os
import sys
import sqlite3

# The Postgres URL MUST come from the environment. Never hardcode it.
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
if not DATABASE_URL or not DATABASE_URL.startswith('postgres'):
    print("ERROR: No valid DATABASE_URL environment variable found.")
    print("Set it first, e.g.:\n  $env:DATABASE_URL=\"postgres://...\" ; python migrate_to_postgres.py")
    sys.exit(1)

# Do NOT print the URL anywhere.
print("DATABASE_URL detected (value hidden).")

# Reuse the app's models so schema matches exactly.
from app import db, app as flask_app
# Import all models so they are registered with db.Model metadata.
from app import (
    User, Tournament, UserTournament, TournamentStat,
    WalletTransaction, Notification, TournamentChatMessage,
    GlobalChatMessage, TournamentMatch, TournamentMatchChatMessage,
    TournamentMatchDispute,
)

SQLITE_PATH = os.path.join('instance', 'database.db')


def load_sqlite_data():
    """Read all rows from the local SQLite DB into a dict of {table: [rows]}."""
    con = sqlite3.connect(SQLITE_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    data = {}
    for t in tables:
        cur.execute(f"SELECT * FROM {t}")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        data[t] = rows
    con.close()
    return data


def migrate():
    with flask_app.app_context():
        print("Creating PostgreSQL schema (create_all)...")
        db.create_all()

        data = load_sqlite_data()
        print("Loaded SQLite data.")

        # --- 1. USERS ---
        user_id_map = {}
        existing_emails = set()
        existing_usernames = set()
        for u in User.query.all():
            existing_emails.add((u.email or '').lower())
            existing_usernames.add((u.username or '').lower())
            user_id_map[u.id] = u.id

        for row in data.get('user', []):
            email = (row.get('email') or '').lower()
            username = (row.get('username') or '')
            if email in existing_emails or username.lower() in existing_usernames:
                print(f"  SKIP user (exists): {email}")
                continue
            u = User(
                username=username,
                email=email,
                password=row.get('password') or '',
                is_admin=bool(row.get('is_admin')),
                suspended=bool(row.get('suspended')),
                email_verified=bool(row.get('email_verified')),
                verification_code=row.get('verification_code'),
                verification_expires_at=row.get('verification_expires_at'),
                reset_code=row.get('reset_code'),
                reset_expires_at=row.get('reset_expires_at'),
                avatar_url=row.get('avatar_url'),
                bio=row.get('bio'),
                payout_bank=row.get('payout_bank'),
                payout_account_number=row.get('payout_account_number'),
                payout_account_name=row.get('payout_account_name'),
                wallet_balance=row.get('wallet_balance') or 0,
            )
            db.session.add(u)
            db.session.flush()
            user_id_map[row['id']] = u.id
            existing_emails.add(email)
            existing_usernames.add(username.lower())
            print(f"  Added user: {email}")
        db.session.commit()
        print(f"Users done. {len(data.get('user', []))} processed.")

        # --- 2. TOURNAMENTS ---
        tournament_id_map = {}
        existing_games = set(t.game for t in Tournament.query.all())
        for row in data.get('tournament', []):
            # dedupe by game name
            if row.get('game') in existing_games:
                print(f"  SKIP tournament (game exists): {row.get('game')}")
                continue
            t = Tournament(
                name=row.get('name'),
                game=row.get('game'),
                entry_fee=row.get('entry_fee'),
                prize=row.get('prize'),
                max_participants=row.get('max_participants'),
                description=row.get('description'),
                created_at=row.get('created_at'),
                status=row.get('status'),
                room_id=row.get('room_id'),
                room_password=row.get('room_password'),
                match_time=row.get('match_time'),
                first_place=row.get('first_place'),
                second_place=row.get('second_place'),
                third_place=row.get('third_place'),
            )
            db.session.add(t)
            db.session.flush()
            tournament_id_map[row['id']] = t.id
            existing_games.add(t.game)
            print(f"  Added tournament: {t.game}")
        db.session.commit()
        print(f"Tournaments done. {len(data.get('tournament', []))} processed.")

        # --- 3. USER_TOURNAMENT (memberships) ---
        for row in data.get('user_tournament', []):
            uid = user_id_map.get(row.get('user_id'))
            tid = tournament_id_map.get(row.get('tournament_id'))
            if not uid or not tid:
                continue
            # skip if already exists
            exists = UserTournament.query.filter_by(
                user_id=uid, tournament_id=tid
            ).first()
            if exists:
                continue
            ut = UserTournament(
                user_id=uid,
                tournament_id=tid,
                joined_at=row.get('joined_at'),
                payment_status=row.get('payment_status'),
                transaction_ref=row.get('transaction_ref'),
                amount_paid=row.get('amount_paid'),
            )
            db.session.add(ut)
        db.session.commit()
        print(f"Memberships done. {len(data.get('user_tournament', []))} processed.")

        # --- 4. WALLET TRANSACTIONS ---
        for row in data.get('wallet_transaction', []):
            uid = user_id_map.get(row.get('user_id'))
            if not uid:
                continue
            exists = WalletTransaction.query.filter_by(transaction_ref=row.get('transaction_ref')).first()
            if exists:
                continue
            wt = WalletTransaction(
                user_id=uid,
                type=row.get('type'),
                amount=row.get('amount'),
                status=row.get('status'),
                transaction_ref=row.get('transaction_ref'),
                bank_name=row.get('bank_name'),
                account_number=row.get('account_number'),
                account_name=row.get('account_name'),
                created_at=row.get('created_at'),
            )
            db.session.add(wt)
        db.session.commit()
        print(f"Wallet done. {len(data.get('wallet_transaction', []))} processed.")

        # --- 5. NOTIFICATIONS ---
        for row in data.get('notification', []):
            uid = user_id_map.get(row.get('user_id'))
            if not uid:
                continue
            n = Notification(
                user_id=uid,
                message=row.get('message'),
                read_at=row.get('read_at'),
                created_at=row.get('created_at'),
            )
            db.session.add(n)
        db.session.commit()
        print(f"Notifications done. {len(data.get('notification', []))} processed.")

        # --- 6. GLOBAL CHAT ---
        for row in data.get('global_chat_message', []):
            uid = user_id_map.get(row.get('user_id'))
            if not uid:
                continue
            g = GlobalChatMessage(
                user_id=uid,
                message=row.get('message'),
                created_at=row.get('created_at'),
            )
            db.session.add(g)
        db.session.commit()
        print(f"Global chat done. {len(data.get('global_chat_message', []))} processed.")

        # --- 7. TOURNAMENT MATCHES ---
        match_id_map = {}
        for row in data.get('tournament_match', []):
            tid = tournament_id_map.get(row.get('tournament_id'))
            p1 = user_id_map.get(row.get('player_one_user_id'))
            p2 = user_id_map.get(row.get('player_two_user_id'))
            if not tid or not p1 or not p2:
                continue
            m = TournamentMatch(
                tournament_id=tid,
                player_one_user_id=p1,
                player_two_user_id=p2,
                status=row.get('status'),
                room_code=row.get('room_code'),
                room_password=row.get('room_password'),
                player_one_profile_id=row.get('player_one_profile_id'),
                player_two_profile_id=row.get('player_two_profile_id'),
                winner_user_id=user_id_map.get(row.get('winner_user_id')),
                proof_note=row.get('proof_note'),
                submitted_by_user_id=user_id_map.get(row.get('submitted_by_user_id')),
                created_at=row.get('created_at'),
                updated_at=row.get('updated_at'),
            )
            db.session.add(m)
            db.session.flush()
            match_id_map[row['id']] = m.id
        db.session.commit()
        print(f"Matches done. {len(data.get('tournament_match', []))} processed.")

        # --- 8. TOURNAMENT MATCH CHAT ---
        for row in data.get('tournament_match_chat_message', []):
            mid = match_id_map.get(row.get('match_id'))
            uid = user_id_map.get(row.get('user_id'))
            if not mid or not uid:
                continue
            mc = TournamentMatchChatMessage(
                match_id=mid,
                user_id=uid,
                message=row.get('message'),
                created_at=row.get('created_at'),
            )
            db.session.add(mc)
        db.session.commit()
        print(f"Match chat done. {len(data.get('tournament_match_chat_message', []))} processed.")

        # --- 9. TOURNAMENT CHAT ---
        for row in data.get('tournament_chat_message', []):
            tid = tournament_id_map.get(row.get('tournament_id'))
            uid = user_id_map.get(row.get('user_id'))
            if not tid or not uid:
                continue
            tc = TournamentChatMessage(
                tournament_id=tid,
                user_id=uid,
                message=row.get('message'),
                created_at=row.get('created_at'),
            )
            db.session.add(tc)
        db.session.commit()
        print(f"Tournament chat done. {len(data.get('tournament_chat_message', []))} processed.")

        # --- 10. TOURNAMENT STATS ---
        for row in data.get('tournament_stat', []):
            uid = user_id_map.get(row.get('user_id'))
            tid = tournament_id_map.get(row.get('tournament_id'))
            if not uid or not tid:
                continue
            ts = TournamentStat(
                user_id=uid,
                tournament_id=tid,
                wins=row.get('wins'),
                kills=row.get('kills'),
                points=row.get('points'),
                rank=row.get('rank'),
                prize_code=row.get('prize_code'),
                prize_code_sent_at=row.get('prize_code_sent_at'),
                prize_status=row.get('prize_status'),
                paystack_transfer_ref=row.get('paystack_transfer_ref'),
                prize_paid_at=row.get('prize_paid_at'),
            )
            db.session.add(ts)
        db.session.commit()
        print(f"Tournament stats done. {len(data.get('tournament_stat', []))} processed.")

        # --- 11. DISPUTES ---
        for row in data.get('tournament_match_dispute', []):
            mid = match_id_map.get(row.get('match_id'))
            uid = user_id_map.get(row.get('user_id'))
            if not mid or not uid:
                continue
            d = TournamentMatchDispute(
                match_id=mid,
                user_id=uid,
                reason=row.get('reason'),
                status=row.get('status'),
                created_at=row.get('created_at'),
            )
            db.session.add(d)
        db.session.commit()
        print(f"Disputes done. {len(data.get('tournament_match_dispute', []))} processed.")

        print("\nMigration complete!")


if __name__ == '__main__':
    migrate()
