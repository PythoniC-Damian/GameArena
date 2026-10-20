"""Owner-operated session revocation and lost-MFA recovery. Never print credentials."""
import argparse
import os
import sys
from contextlib import closing
import psycopg2


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('revoke-sessions','reset-mfa'))
    parser.add_argument('--user-id',type=int,required=True)
    parser.add_argument('--confirm-username',required=True)
    args=parser.parse_args()
    url=os.environ.get('GAMEARENA_SECURITY_DATABASE_URL','')
    if not url.startswith(('postgresql://','postgres://')):
        raise SystemExit('Set GAMEARENA_SECURITY_DATABASE_URL privately; this tool never loads .env.')
    try:
        with closing(psycopg2.connect(url,connect_timeout=15)) as connection, connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT username FROM public."user" WHERE id=%s FOR UPDATE',(args.user_id,))
                row=cursor.fetchone()
                if not row or row[0]!=args.confirm_username:raise ValueError('Account confirmation did not match. No change was made.')
                if args.action=='reset-mfa':
                    cursor.execute('UPDATE account_security SET totp_secret=NULL,pending_secret=NULL,pending_at=NULL,enabled_at=NULL,recovery_hashes=%s,last_counter=-1,version=version+1 WHERE user_id=%s',('[]',args.user_id))
                cursor.execute('UPDATE public."user" SET auth_session_version=auth_session_version+1 WHERE id=%s',(args.user_id,))
        print('Existing sign-in sessions invalidated.' if args.action=='revoke-sessions' else 'MFA reset and sessions invalidated. The owner must sign in and enroll again.')
    except ValueError as error:raise SystemExit(str(error))
    except Exception:raise SystemExit('Recovery failed. Check database access privately; no credentials are displayed.') from None


if __name__=='__main__':main()
