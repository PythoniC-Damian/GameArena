"""Retry transactional lock conflicts, never hide permanent migration errors."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from sqlalchemy.exc import OperationalError
from alembic import command
from scripts import migrate

def error(code):
    return OperationalError('DDL',{},SimpleNamespace(pgcode=code))

def test_transient_lock_retries_then_succeeds(monkeypatch):
    upgrade=Mock(side_effect=[error('40P01'),error('55P03'),None]);sleep=Mock()
    monkeypatch.setattr(command,'upgrade',upgrade);monkeypatch.setattr(migrate.time,'sleep',sleep)
    migrate.upgrade_with_retry('config')
    assert upgrade.call_count==3 and [c.args[0] for c in sleep.call_args_list]==[1,2]

@pytest.mark.parametrize('code,calls',[('42601',1),('40P01',3)])
def test_permanent_or_repeated_error_is_not_hidden(monkeypatch,code,calls):
    upgrade=Mock(side_effect=error(code))
    monkeypatch.setattr(command,'upgrade',upgrade);monkeypatch.setattr(migrate.time,'sleep',lambda _:None)
    with pytest.raises(OperationalError):migrate.upgrade_with_retry('config')
    assert upgrade.call_count==calls
