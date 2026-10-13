"""Prepare this Mac for sync; --activate links a confirmed Auth user and enables sync.

Does not read, reset, or upload login passwords. Never uploads medicine records.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import secrets
import sqlite3
from uuid import UUID, uuid4
import psycopg
from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[1]
PHARMACY = UUID('3a3f3ad9-ae5e-5828-bb6f-936068f05e00')
PUBLIC_KEY = 'sb_publishable_6oH7L5aa46fHxG0RD-q5Vg_VXLvCGPm'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--activate',action='store_true')
    args=parser.parse_args()
    env=ROOT/'.env'; cfg=dotenv_values(env)
    with sqlite3.connect('file:'+str(ROOT/'temp.db')+'?mode=ro',uri=True) as local:
        local.row_factory=sqlite3.Row
        profile=dict(local.execute('SELECT id,email,first_name,last_name,license_number,role FROM employee_table WHERE id=1').fetchone())
    if profile['role']!='superadmin': raise RuntimeError('Local account is not superadmin')
    device=UUID(cfg['SYNC_DEVICE_ID']) if cfg.get('SYNC_DEVICE_ID') else uuid4()
    secret=cfg.get('SYNC_DEVICE_SECRET') or secrets.token_urlsafe(48)
    if len(secret)<32: raise RuntimeError('Device secret is too short')
    if cfg.get('SYNC_PHARMACY_ID') not in (None,'',str(PHARMACY)): raise RuntimeError('Existing pharmacy does not match')
    cert=Path(cfg['SUPABASE_ADMIN_DB_SSLROOTCERT'])
    if not cert.is_absolute(): cert=ROOT/cert
    with psycopg.connect(host=cfg['SUPABASE_ADMIN_DB_HOST'],port=int(cfg.get('SUPABASE_ADMIN_DB_PORT',5432)),dbname=cfg.get('SUPABASE_ADMIN_DB_NAME','postgres'),user=cfg.get('SUPABASE_ADMIN_DB_USER','postgres'),password=cfg['SUPABASE_ADMIN_DB_PASSWORD'],sslmode='verify-full',sslrootcert=str(cert),connect_timeout=15) as cloud:
        cloud.execute('SELECT pg_advisory_xact_lock(71426013)')
        if not cloud.execute('SELECT 1 FROM erp.pharmacies WHERE id=%s',(PHARMACY,)).fetchone(): raise RuntimeError('Pharmacy not found')
        user=cloud.execute('SELECT id,email_confirmed_at FROM auth.users WHERE lower(email)=lower(%s) AND deleted_at IS NULL',(profile['email'],)).fetchall()
        if len(user)>1: raise RuntimeError('Multiple matching cloud users')
        if args.activate and (not user or not user[0][1]): raise RuntimeError('Create and confirm the cloud login in Supabase first; local sync remains unchanged')
        auth_id=user[0][0] if user and user[0][1] else None
        employee=cloud.execute('SELECT id,auth_user_id,role,disabled_at,deleted_at FROM erp.employee_profiles WHERE pharmacy_id=%s AND lower(email)=lower(%s)',(PHARMACY,profile['email'])).fetchall()
        if len(employee)>1: raise RuntimeError('Multiple employee profiles')
        if employee:
            employee_id,linked,role,disabled,deleted=employee[0]
            if role!='superadmin' or disabled or deleted or (linked and linked!=auth_id): raise RuntimeError('Existing employee configuration requires review')
            if auth_id and not linked:
                cloud.execute('UPDATE erp.employee_profiles SET auth_user_id=%s,updated_at=now(),version=version+1 WHERE pharmacy_id=%s AND id=%s',(auth_id,PHARMACY,employee_id))
        else:
            employee_id=uuid4()
            cloud.execute('INSERT INTO erp.employee_profiles(pharmacy_id,id,auth_user_id,first_name,last_name,email,role,license_number,pharmacy_name) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',(PHARMACY,employee_id,auth_id,profile['first_name'],profile['last_name'],profile['email'],'superadmin',profile['license_number'],'Surya Pharmacy'))
        old=cloud.execute('SELECT enrolled_by,credential_hash,revoked_at FROM erp.registered_devices WHERE pharmacy_id=%s AND id=%s',(PHARMACY,device)).fetchone()
        digest=sha256(secret.encode()).hexdigest()
        if old and (old[0]!=employee_id or old[1]!=digest or old[2]): raise RuntimeError('Device registration differs; refusing to overwrite')
        if not old:
            cloud.execute('INSERT INTO erp.registered_devices(pharmacy_id,id,name,enrolled_by,credential_hash) VALUES (%s,%s,%s,%s,%s)',(PHARMACY,device,'Vijay Mac — Pharmacy',employee_id,digest))
    folder=ROOT/'backups'; folder.mkdir(exist_ok=True)
    backup=folder/('before-sync-config-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.env')
    backup.write_bytes(env.read_bytes()); backup.chmod(0o600)
    values={'SUPABASE_PUBLISHABLE_KEY':PUBLIC_KEY,'SYNC_PHARMACY_ID':str(PHARMACY),'SYNC_DEVICE_ID':str(device),'SYNC_DEVICE_SECRET':secret,'SYNC_ENABLED':'true' if args.activate else cfg.get('SYNC_ENABLED','false')}
    for key,value in values.items(): set_key(str(env),key,value,quote_mode='always')
    env.chmod(0o600)
    print('Device registered; private configuration saved. No medicines uploaded.')
    print('Cloud login linked; sync enabled. Restart backend and sign in online.' if args.activate else 'Prepared. Sync remains disabled until the confirmed cloud login is linked with --activate.')


if __name__=='__main__': main()
