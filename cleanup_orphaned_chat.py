"""
cleanup_orphaned_chat.py

Delete orphaned GlobalChatMessage rows in the currently-configured database.

An "orphaned" row is one whose user_id does NOT reference an existing user (or
whose user relationship resolves to None). These rows cause the /chat page to
crash with HTTP 500.

Usage:
    # Target the local SQLite DB (default behaviour via the app config/.env)
    python cleanup_orphaned_chat.py

    # Target the Render Postgres DB
    $env:DATABASE_URL="postgres://..." ; python cleanup_orphaned_chat.py
"""

import os
import sys

# Load the app AFTER pointing DATABASE_URL so the engine binds correctly.
DATABASE_URL = (os.environ.get('DATABASE_URL') or '').strip()
if DATABASE_URL:
    print("Using DATABASE_URL from environment (value hidden).")
else:
    print("No DATABASE_URL set - using the app's default (SQLite).")


def _resolve_database_url():
    """Print the DB engine we're about to clean (host details hidden)."""
    from app import app
    uri = app.config['SQLALCHEMY_DATABASE_URI'] or ''
    if uri.startswith('postgres'):
        print("Targeting PostgreSQL database.")
    elif uri.startswith('sqlite'):
        suf = uri.replace('sqlite:///', '').replace('\\', '/')
        print(f"Targeting SQLite database: {suf}")
    else:
        print(f"Targeting database type: {uri.split(':')[0]}")

    if not uri:
        sys.exit("ERROR: No SQLALCHEMY_DATABASE_URI configured.")


def cleanup():
    from app import app, db, GlobalChatMessage, User, TournamentChatMessage, TournamentMatchChatMessage

    _resolve_database_url()

    with app.app_context():
        valid_user_ids = set(r[0] for r in db.session.query(User.id).all())
        print(f"Valid users found: {len(valid_user_ids)}")

        total_deleted = 0

        # --- Global chat ---
        orphaned_gc = [m for m in GlobalChatMessage.query.all() if m.user_id not in valid_user_ids]
        if orphaned_gc:
            for m in orphaned_gc:
                db.session.delete(m)
            db.session.commit()
            total_deleted += len(orphaned_gc)
            print(f"Deleted {len(orphaned_gc)} orphaned GlobalChatMessage rows.")
        else:
            print("No orphaned GlobalChatMessage rows found.")

        # --- Tournament chat (defensive) ---
        orphaned_tc = [m for m in TournamentChatMessage.query.all() if m.user_id not in valid_user_ids]
        if orphaned_tc:
            for m in orphaned_tc:
                db.session.delete(m)
            db.session.commit()
            total_deleted += len(orphaned_tc)
            print(f"Deleted {len(orphaned_tc)} orphaned TournamentChatMessage rows.")
        else:
            print("No orphaned TournamentChatMessage rows found.")

        # --- Match chat (defensive) ---
        orphaned_mc = [m for m in TournamentMatchChatMessage.query.all() if m.user_id not in valid_user_ids]
        if orphaned_mc:
            for m in orphaned_mc:
                db.session.delete(m)
            db.session.commit()
            total_deleted += len(orphaned_mc)
            print(f"Deleted {len(orphaned_mc)} orphaned TournamentMatchChatMessage rows.")
        else:
            print("No orphaned TournamentMatchChatMessage rows found.")

        print(f"\nCleanup complete. Total orphaned rows deleted: {total_deleted}")


if __name__ == '__main__':
    cleanup()

