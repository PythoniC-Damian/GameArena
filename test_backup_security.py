"""Encrypted archive integrity and overwrite protection using synthetic data."""
import base64
import io
import secrets
from unittest.mock import Mock
import pytest
from scripts import backup_database as backup


def archive(key):
    result=io.BytesIO()
    backup.encrypt_stream(io.BytesIO(b'PGDMP synthetic private record'),result,key,{'format':'pg_custom'})
    return result.getvalue()


def test_encrypted_archive_roundtrip_and_random_nonce():
    key=secrets.token_bytes(32);encrypted=archive(key);output=io.BytesIO()
    assert b'synthetic private record' not in encrypted
    assert encrypted != archive(key)
    assert backup.decrypt_stream(io.BytesIO(encrypted),output,key)['format']=='pg_custom'
    assert output.read()==b'PGDMP synthetic private record'


@pytest.mark.parametrize('change', ['key','ciphertext','tag','truncate'])
def test_invalid_backup_never_reaches_postgres(tmp_path,monkeypatch,change):
    key=secrets.token_bytes(32);encrypted=bytearray(archive(key))
    if change=='key': key=secrets.token_bytes(32)
    if change=='ciphertext':encrypted[-20]^=1
    if change=='tag':encrypted[-1]^=1
    if change=='truncate':encrypted=encrypted[:12]
    target=tmp_path/'damaged.gabk';target.write_bytes(encrypted)
    monkeypatch.setenv('GAMEARENA_BACKUP_KEY',base64.urlsafe_b64encode(key).decode())
    call=Mock(side_effect=AssertionError('No process may consume unauthenticated data'))
    monkeypatch.setattr(backup.subprocess,'run',call)
    with pytest.raises(ValueError):backup.verify_or_restore(target,'gamearena_restore_test')
    assert not call.called


def test_existing_backup_cannot_be_overwritten(tmp_path,monkeypatch):
    target=tmp_path/'existing.gabk';target.write_bytes(b'original')
    monkeypatch.setenv('GAMEARENA_BACKUP_KEY',base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
    monkeypatch.setenv('GAMEARENA_BACKUP_DATABASE_URL','postgresql://synthetic@localhost/test')
    with pytest.raises(FileExistsError):backup.create_backup(target)
    assert target.read_bytes()==b'original'


def test_credentials_stay_out_of_process_arguments():
    env=backup.connection_environment('postgresql://synthetic:private%40password@localhost:55476/gamearena_restore_test?sslmode=require')
    assert env['PGPASSWORD']=='private@password' and env['PGSSLMODE']=='require'
    with pytest.raises(ValueError):backup.connection_environment('https://example.invalid/database')
