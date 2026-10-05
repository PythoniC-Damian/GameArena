"""Verify the additive-to-Alembic transition only on the isolated test DB."""
import importlib
import os
from pathlib import Path
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
import pytest
from app import app, db, WalletTransaction
from db_migrate import migrate
from test_interface_contracts import player


def test_baseline_is_repeatable_and_preserves_wallet_records(monkeypatch):
    url = os.environ['GAMEARENA_TEST_DATABASE_URL']
    monkeypatch.setenv('MIGRATION_DATABASE_URL', url)
    with app.app_context():
        owner = player('migration_owner'); owner.wallet_balance = 1200
        transaction = WalletTransaction(user_id=owner.id, type='deposit', amount=1200, status='completed', transaction_ref='isolated-baseline-test')
        db.session.add(transaction); db.session.commit()
        migrate(url=url)
        config = Config(str(Path(__file__).parent/'alembic.ini'))
        command.upgrade(config, 'head'); command.upgrade(config, 'head')
        db.session.expire_all()
        assert owner.wallet_balance == 1200 and WalletTransaction.query.count() == 1
        assert db.session.execute(text('SELECT version_num FROM alembic_version')).scalar() == '20261005_existing_schema'


def test_baseline_refuses_incomplete_history():
    revision = importlib.import_module('migrations.versions.20261005_existing_schema')
    url = os.environ['GAMEARENA_TEST_DATABASE_URL']
    migrate(url=url)
    with app.app_context(), db.engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("DELETE FROM schema_migration WHERE migration_id='20261004_chat_delivery_and_profile_photos'"))
            context = MigrationContext.configure(connection)
            with Operations.context(context), pytest.raises(RuntimeError, match='incomplete'):
                revision.upgrade()
        finally:
            transaction.rollback()
