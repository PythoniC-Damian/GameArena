import sqlite3
import pytest

import db_migrate


def test_sqlite_migrations_are_rejected(tmp_path):
    db_path = tmp_path / "legacy.sqlite"

    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE user (id INTEGER PRIMARY KEY, username TEXT, email TEXT, password TEXT)"
    )
    conn.execute(
        "CREATE TABLE tournament (id INTEGER PRIMARY KEY, name TEXT, game TEXT, entry_fee INTEGER, prize INTEGER, max_participants INTEGER)"
    )
    conn.execute(
        """
        CREATE TABLE tournament_stat (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            tournament_id INTEGER NOT NULL,
            wins INTEGER DEFAULT 0,
            kills INTEGER DEFAULT 0,
            points INTEGER DEFAULT 0,
            rank INTEGER DEFAULT 0
        )
        """
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match='Unsupported database dialect'):
        db_migrate.migrate(f"sqlite:///{db_path}")
