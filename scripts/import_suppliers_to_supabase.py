"""Copy previously imported Pharmacy suppliers to Supabase; dry run by default.

Uses the local supplier_import_sources provenance, preserves UUID mappings,
refuses to overwrite differing cloud records, and records cloud sync changes.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import UUID, uuid5

import psycopg
from psycopg.types.json import Jsonb
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'Surya_Pharmacy.dbo.vendorProfile'
PHARMACY_ID = uuid5(UUID('74dab4b7-e947-48e7-97ce-6eb4bca08584'), 'Surya_Pharmacy')
FIELDS = ('name', 'contact_person', 'phone', 'email', 'address')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    cfg = dotenv_values(ROOT / '.env')
    local = sqlite3.connect(ROOT / 'temp.db')
    local.row_factory = sqlite3.Row
    if args.apply:
        folder = ROOT / 'backups'
        folder.mkdir(exist_ok=True)
        backup = folder / ('before-supplier-cloud-import-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.sqlite3')
        with sqlite3.connect(backup) as dest:
            local.backup(dest)
        backup.chmod(0o600)
    local.execute('BEGIN IMMEDIATE' if args.apply else 'BEGIN')
    try:
        rows = local.execute('''SELECT s.*, i.source_id FROM suppliers s
            JOIN supplier_import_sources i ON i.supplier_id=s.id
            WHERE i.source=? ORDER BY s.id''', (SOURCE,)).fetchall()
        assert len(rows) == 564, 'Unexpected source count; review before importing'
        assert len({r['id'] for r in rows}) == len(rows), 'Duplicate source mappings'
        certificate = Path(cfg['SUPABASE_ADMIN_DB_SSLROOTCERT'])
        if not certificate.is_absolute(): certificate = ROOT / certificate
        with psycopg.connect(host=cfg['SUPABASE_ADMIN_DB_HOST'],
                port=int(cfg.get('SUPABASE_ADMIN_DB_PORT', 5432)),
                dbname=cfg.get('SUPABASE_ADMIN_DB_NAME', 'postgres'),
                user=cfg.get('SUPABASE_ADMIN_DB_USER', 'postgres'),
                password=cfg['SUPABASE_ADMIN_DB_PASSWORD'], sslmode='verify-full',
                sslrootcert=str(certificate), connect_timeout=15,
                options='-c statement_timeout=30000') as cloud:
            cloud.execute('SELECT pg_advisory_xact_lock(71426012)')
            pharmacies = cloud.execute('SELECT id,name FROM erp.pharmacies').fetchall()
            if pharmacies and pharmacies != [(PHARMACY_ID, 'Surya Pharmacy')]:
                raise ValueError('Unexpected pharmacy configuration; explicit mapping needed')
            current = cloud.execute('SELECT id,name,contact_person,phone,email,address,version,deleted_at FROM erp.suppliers WHERE pharmacy_id=%s', (PHARMACY_ID,)).fetchall()
            by_id = {r[0]: r[1:] for r in current}
            by_name = {r[1].strip().lower(): r[0] for r in current}
            prepared = []
            for row in rows:
                identity = local.execute("SELECT cloud_id,version,deleted FROM sync_identities WHERE entity='suppliers' AND local_id=?", (row['id'],)).fetchone()
                cloud_id = UUID(identity['cloud_id']) if identity else uuid5(PHARMACY_ID, SOURCE + ':' + row['source_id'])
                if identity and identity['deleted']: raise ValueError('Supplier has pending deletion')
                pending = local.execute("SELECT count(*) FROM sync_outbox WHERE entity='suppliers' AND cloud_id=? AND state IN ('pending','conflict')", (str(cloud_id),)).fetchone()[0]
                if pending: raise ValueError('Supplier has pending sync operations')
                payload = {key: row[key] for key in FIELDS}
                for key, limit in [('name',150),('contact_person',100),('phone',30),('email',150)]:
                    if payload[key] and len(payload[key]) > limit: raise ValueError('Field exceeds cloud limit')
                if not payload['name']: raise ValueError('Missing supplier name')
                existing = by_id.get(cloud_id)
                if existing and (tuple(payload.values()) != existing[:5] or existing[6] is not None):
                    raise ValueError('Existing cloud supplier differs; refusing overwrite')
                collision = by_name.get(payload['name'].strip().lower())
                if collision and collision != cloud_id: raise ValueError('Cloud supplier name collision')
                prepared.append((row['id'], cloud_id, payload, existing[5] if existing else 1, bool(existing)))
            new = sum(not p[4] for p in prepared)
            print(json.dumps({'source_count':len(rows),'new_suppliers':new,'already_present':len(rows)-new,'pharmacy':'Surya Pharmacy','pharmacy_id':str(PHARMACY_ID),'apply':args.apply}))
            if not args.apply:
                cloud.rollback()
                return
            cloud.execute('INSERT INTO erp.pharmacies(id,name) VALUES (%s,%s) ON CONFLICT (id) DO NOTHING', (PHARMACY_ID,'Surya Pharmacy'))
            cloud.execute('INSERT INTO erp.sync_heads(pharmacy_id,cursor) VALUES (%s,0) ON CONFLICT (pharmacy_id) DO NOTHING', (PHARMACY_ID,))
            with cloud.pipeline():
                for local_id, cloud_id, payload, version, exists in prepared:
                    if not exists:
                        cloud.execute('INSERT INTO erp.suppliers(pharmacy_id,id,name,contact_person,phone,email,address) VALUES (%s,%s,%s,%s,%s,%s,%s)', (PHARMACY_ID,cloud_id,*payload.values()))
                        cloud.execute('SELECT erp.log_change(%s,%s,%s,%s,%s,%s,false)', (PHARMACY_ID,'suppliers',cloud_id,version,uuid5(cloud_id,'initial-import'),Jsonb(payload)))
                    local.execute("INSERT INTO sync_identities(entity,local_id,cloud_id,version,deleted) VALUES ('suppliers',?,?,?,0) ON CONFLICT(entity,local_id) DO UPDATE SET version=excluded.version", (local_id,str(cloud_id),version))
            count = cloud.execute('SELECT count(*) FROM erp.suppliers WHERE pharmacy_id=%s', (PHARMACY_ID,)).fetchone()[0]
            assert count == len(prepared), 'Unexpected final count'
        local.commit()
        print('Committed suppliers and sync history to Supabase; local UUID mappings saved.')
    finally:
        local.rollback()
        local.close()


if __name__ == '__main__':
    main()
