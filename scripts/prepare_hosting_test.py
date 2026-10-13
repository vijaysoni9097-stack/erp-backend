"""Seed only catalog/reference stock into the explicitly configured testing project.

Never copies customers, prescriptions, sales, employee credentials or sync state.
Run from the repository root. Credentials remain in .env.hosting.local.
"""
import os
from pathlib import Path
import secrets
import sys

from dotenv import dotenv_values, set_key
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    private = ROOT / '.env.hosting.local'
    cfg = dotenv_values(private)
    if (cfg.get('STAGING_PROJECT_REF') != 'wizlnubijmsjbolfxxox'
            or cfg.get('STAGING_DATABASE_USER') != 'postgres.wizlnubijmsjbolfxxox'
            or cfg.get('STAGING_DATABASE_HOST') != 'aws-0-ap-southeast-2.pooler.supabase.com'):
        raise ValueError('Refusing an unexpected testing destination')
    url = URL.create('postgresql+psycopg', username=cfg['STAGING_DATABASE_USER'],
                     password=cfg['STAGING_DATABASE_PASSWORD'], host=cfg['STAGING_DATABASE_HOST'],
                     port=5432, database='postgres', query={'sslmode': 'require'})
    os.environ.update(DATABASE_URL=url.render_as_string(hide_password=False),
                      DATABASE_SCHEMA='erp_app', REQUIRE_POSTGRES='true', SYNC_ENABLED='false')
    from app.database import Base, engine, SessionLocal, initialize_schema
    from app.models import Medicine, Supplier, StockSnapshot, PharmacistProfile
    from app.services.settings import seed_settings
    from app.setup_local import provision_account

    initialize_schema()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_settings(db)
        profile = db.get(PharmacistProfile, 1)
        if profile.password_hash is None:
            password = cfg.get('STAGING_LOGIN_PASSWORD') or secrets.token_urlsafe(24)
            set_key(str(private), 'STAGING_LOGIN_EMAIL', 'pharmacist@example.com')
            set_key(str(private), 'STAGING_LOGIN_PASSWORD', password)
            private.chmod(0o600)
            profile.first_name, profile.last_name = 'Test', 'Administrator'
            profile.role, profile.pharmacy_name = 'superadmin', 'Testing Pharmacy'
            profile.phone = None
            profile.address_line_1 = profile.address_line_2 = None
            profile.country = profile.state = profile.city = profile.postal_code = None
            db.flush()
            provision_account(db, 'pharmacist@example.com', password)

    source = create_engine(f'sqlite:///file:{ROOT / "temp.db"}?mode=ro&uri=true')
    with source.connect() as local, engine.begin() as cloud:
        cloud.execute(text('SELECT pg_advisory_xact_lock(71426014)'))
        for model in (Supplier, Medicine, StockSnapshot):
            table = model.__table__
            existing = set(cloud.execute(select(*table.primary_key.columns)).scalars())
            rows = [dict(row) for row in local.execute(select(table)).mappings()
                    if row[list(table.primary_key.columns)[0].name] not in existing]
            if model is Medicine:
                for row in rows:
                    row['stock_quantity'] = 0
            if rows:
                cloud.execute(table.insert(), rows)
            if model in (Supplier, Medicine):
                cloud.execute(text("SELECT setval(pg_get_serial_sequence(:table,'id'), "
                                   f"COALESCE((SELECT MAX(id) FROM {table.name}), 1))"),
                              {'table': table.name})
            print(f'{table.name}: inserted {len(rows)}, retained {len(existing)}')
    source.dispose()
    engine.dispose()
    print('Testing catalog ready. Separate test login saved privately; cloud sync remains disabled.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Driver errors may include connection details or row contents.
        print(f'Testing setup stopped ({type(exc).__name__}); no credentials displayed.')
        raise SystemExit(1)
