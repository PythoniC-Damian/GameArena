"""Stream encrypted PostgreSQL backups; restore only to a confirmed empty drill DB.

Never load .env or put database passwords/encryption keys in command arguments.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlparse, parse_qs, unquote
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC=b'GABK1'
CHUNK=1024*1024


def key_from_environment():
    try:
        key=base64.urlsafe_b64decode(os.environ.get('GAMEARENA_BACKUP_KEY','').encode())
        if len(key)!=32: raise ValueError()
        return key
    except Exception:
        raise ValueError('Set a private GAMEARENA_BACKUP_KEY containing a base64-encoded 32-byte key.') from None


def connection_environment(url):
    parsed=urlparse(url)
    if parsed.scheme not in ('postgresql','postgres') or not parsed.hostname or not parsed.path.strip('/'):
        raise ValueError('Provide a valid PostgreSQL URL through the named environment variable.')
    env=dict(os.environ)
    env.update(PGHOST=parsed.hostname,PGPORT=str(parsed.port or 5432),
        PGDATABASE=unquote(parsed.path.lstrip('/')),PGUSER=unquote(parsed.username or ''),
        PGPASSWORD=unquote(parsed.password or ''),PGCONNECT_TIMEOUT='15')
    for source,target in (('sslmode','PGSSLMODE'),('sslrootcert','PGSSLROOTCERT')):
        value=parse_qs(parsed.query).get(source)
        if value: env[target]=value[0]
    return env


def binary(name):
    folder=os.environ.get('GAMEARENA_PG_BIN','')
    value=str(Path(folder)/(name+'.exe' if os.name=='nt' else name)) if folder else shutil.which(name)
    if not value or not Path(value).is_file(): raise ValueError('Install PostgreSQL client tools or set GAMEARENA_PG_BIN.')
    return value


def encrypt_stream(source,destination,key,metadata):
    nonce=secrets.token_bytes(12)
    encryptor=Cipher(algorithms.AES(key),modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(MAGIC)
    destination.write(MAGIC+nonce)
    header=json.dumps(metadata,separators=(',',':')).encode()
    destination.write(encryptor.update(len(header).to_bytes(4,'big')+header))
    while True:
        chunk=source.read(CHUNK)
        if not chunk: break
        destination.write(encryptor.update(chunk))
    destination.write(encryptor.finalize())
    destination.write(encryptor.tag)


def decrypt_stream(source,destination,key):
    source.seek(0,2);size=source.tell();source.seek(0)
    if size<len(MAGIC)+12+16+4 or source.read(len(MAGIC))!=MAGIC:
        raise ValueError('This is not a supported GameArena encrypted backup.')
    nonce=source.read(12)
    source.seek(-16,2);tag=source.read(16);source.seek(len(MAGIC)+12)
    decryptor=Cipher(algorithms.AES(key),modes.GCM(nonce,tag)).decryptor()
    decryptor.authenticate_additional_data(MAGIC)
    remaining=size-len(MAGIC)-12-16
    header=bytearray();metadata=None;header_length=None
    while remaining:
        chunk=source.read(min(CHUNK,remaining))
        if not chunk:raise ValueError('Backup is truncated.')
        remaining-=len(chunk);plain=decryptor.update(chunk)
        if metadata is None:
            header.extend(plain)
            if header_length is None and len(header)>=4:
                header_length=int.from_bytes(header[:4],'big')
                if not 1<=header_length<=65536:raise ValueError('Backup metadata is invalid.')
            if header_length is not None and len(header)>=header_length+4:
                metadata=json.loads(header[4:header_length+4])
                destination.write(header[header_length+4:]);header.clear()
        else:destination.write(plain)
    # Authentication MUST finish before pg_restore or any SQL is executed.
    try: destination.write(decryptor.finalize())
    except Exception:raise ValueError('Backup authentication failed: wrong key, corruption or tampering.') from None
    if not isinstance(metadata,dict) or metadata.get('format')!='pg_custom':
        raise ValueError('Backup metadata is invalid.')
    destination.flush();destination.seek(0)
    return metadata


def create_backup(destination):
    url=os.environ.get('GAMEARENA_BACKUP_DATABASE_URL','')
    env=connection_environment(url);key=key_from_environment()
    target=Path(destination).resolve()
    target.parent.mkdir(parents=True,exist_ok=True)
    metadata={'format':'pg_custom','created_at':datetime.now(timezone.utc).isoformat(),
        'database_fingerprint':hashlib.sha256((env['PGHOST']+':'+env['PGPORT']+'/'+env['PGDATABASE']).encode()).hexdigest()}
    process=None;created=False
    try:
        descriptor=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);created=True
        with os.fdopen(descriptor,'wb') as output,tempfile.TemporaryFile() as errors:
            process=subprocess.Popen([binary('pg_dump'),'--format=custom','--no-owner','--no-privileges'],
                env=env,stdout=subprocess.PIPE,stderr=errors)
            try:
                encrypt_stream(process.stdout,output,key,metadata)
                if process.wait()!=0:raise ValueError('pg_dump failed. Check client/server versions, database permissions and connection settings privately.')
            finally:process.stdout.close()
        return target
    except Exception:
        if process and process.poll() is None:process.kill();process.wait()
        if created:target.unlink(missing_ok=True)
        raise


def verify_or_restore(path,target_name=None):
    import psycopg2
    with Path(path).open('rb') as encrypted,tempfile.TemporaryFile() as archive,tempfile.TemporaryFile() as errors:
        metadata=decrypt_stream(encrypted,archive,key_from_environment())
        listing=subprocess.run([binary('pg_restore'),'--list'],stdin=archive,stdout=subprocess.DEVNULL,stderr=errors)
        if listing.returncode:raise ValueError('Decryption succeeded but the PostgreSQL archive could not be read.')
        if target_name is None:return metadata
        if not target_name.startswith('gamearena_restore_'):
            raise ValueError('Restore drills require a dedicated database named gamearena_restore_...')
        target_url=os.environ.get('GAMEARENA_RESTORE_DATABASE_URL','')
        env=connection_environment(target_url)
        if env['PGDATABASE']!=target_name:raise ValueError('The restore target must match --confirm-empty-database exactly.')
        fingerprint=hashlib.sha256((env['PGHOST']+':'+env['PGPORT']+'/'+env['PGDATABASE']).encode()).hexdigest()
        if fingerprint==metadata.get('database_fingerprint'):raise ValueError('Never restore a drill over its source database.')
        connection=psycopg2.connect(target_url,connect_timeout=15)
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT current_database()')
                if cursor.fetchone()[0]!=target_name:raise ValueError('Database identity check failed.')
                cursor.execute("SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')")
                if cursor.fetchone()[0]:raise ValueError('Restore target is not empty. No restore was attempted.')
                cursor.execute('SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()')
                if cursor.fetchone()[0]:raise ValueError('Other sessions use the restore target. Disconnect them before the drill.')
        finally:connection.close()
        archive.seek(0)
        result=subprocess.run([binary('pg_restore'),'--clean','--if-exists','--no-owner','--no-privileges','--single-transaction',
            '--exit-on-error','--dbname='+env['PGDATABASE']],env=env,stdin=archive,stdout=subprocess.DEVNULL,stderr=errors)
        if result.returncode:raise ValueError('Restore failed and its database transaction was rolled back. Check extension and role prerequisites privately.')
        return metadata


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    backup=commands.add_parser('backup');backup.add_argument('--output',required=True)
    verify=commands.add_parser('verify');verify.add_argument('file')
    restore=commands.add_parser('restore');restore.add_argument('file');restore.add_argument('--confirm-empty-database',required=True)
    commands.add_parser('generate-key')
    args=parser.parse_args()
    try:
        if args.command=='generate-key':
            print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode());return
        if args.command=='backup':
            path=create_backup(args.output)
            print('Encrypted backup created:',path.name)
        else:
            verify_or_restore(args.file,args.confirm_empty_database if args.command=='restore' else None)
            print('Restore completed on the isolated drill database.' if args.command=='restore' else 'Backup authentication and PostgreSQL archive verification passed.')
    except Exception as error:
        # Provider/library exceptions can contain passwords or connection strings.
        message=str(error) if isinstance(error,ValueError) else 'Operation failed; check configuration privately. No credentials are displayed.'
        print(message,file=sys.stderr);raise SystemExit(1)


if __name__=='__main__':main()
