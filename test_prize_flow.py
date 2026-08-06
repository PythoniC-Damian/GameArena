import importlib
import sqlite3
import sys


def test_existing_sqlite_db_gets_prize_columns_for_tournament_stat(tmp_path, monkeypatch):
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

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    sys.modules.pop("app", None)

    app_module = importlib.import_module("app")
    db = app_module.db

    with app_module.app.app_context():
        result = db.session.execute("PRAGMA table_info(tournament_stat)").fetchall()
        columns = {row[1] for row in result}

    assert {"prize_code", "prize_code_sent_at", "prize_status", "paystack_transfer_ref", "prize_paid_at"}.issubset(columns)
