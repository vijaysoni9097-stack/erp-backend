"""Read-only Supabase administration connection check.

Run from the backend root with: python scripts/check_supabase.py
These database-owner credentials are for development/administration only.
Never distribute them with a desktop installation or put them in frontend env files.
"""
from getpass import getpass
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
import psycopg

ROOT = Path(__file__).resolve().parents[1]


def main():
    load_dotenv(ROOT / '.env', override=False)
    host = os.getenv('SUPABASE_ADMIN_DB_HOST')
    certificate = os.getenv('SUPABASE_ADMIN_DB_SSLROOTCERT')
    if not host or not certificate:
        print('Configure SUPABASE_ADMIN_DB_HOST and SUPABASE_ADMIN_DB_SSLROOTCERT in the backend .env.')
        return 1
    certificate_path = Path(certificate)
    if not certificate_path.is_absolute():
        certificate_path = ROOT / certificate_path
    if not certificate_path.is_file():
        print('The configured Supabase CA certificate file was not found.')
        return 1
    password = os.getenv('SUPABASE_ADMIN_DB_PASSWORD') or getpass('Supabase database password: ')
    try:
        with psycopg.connect(
            host=host,
            port=int(os.getenv('SUPABASE_ADMIN_DB_PORT', '5432')),
            dbname=os.getenv('SUPABASE_ADMIN_DB_NAME', 'postgres'),
            user=os.getenv('SUPABASE_ADMIN_DB_USER', 'postgres'),
            password=password,
            sslmode='verify-full', sslrootcert=str(certificate_path), connect_timeout=10,
            options='-c default_transaction_read_only=on -c statement_timeout=10000',
        ) as connection:
            connection.execute('SELECT 1').fetchone()
            count = connection.execute("SELECT count(*) FROM pg_tables WHERE schemaname IN ('public', 'erp')").fetchone()[0]
            print('Supabase connection verified (TLS, certificate and hostname verification enabled).')
            print(f'Application table count: {count}')
            print('Local DATABASE_URL was not changed. This check does not enable synchronization.')
            return 0
    except (psycopg.Error, ValueError) as error:
        # Connection exceptions can contain sensitive connection parameters; never print them.
        print(f'Supabase connection failed ({type(error).__name__}). Check host, credentials, certificate, and network connectivity.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
