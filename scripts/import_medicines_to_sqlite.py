"""Stage/import legacy catalog using latest purchase details and ZERO opening stock.

This is a catalog-only mapping, not a reconstruction of saleable batch inventory.
Missing or invalid batch, expiry, or prices are held for review, never invented.
No network access or cloud writes. Dry run by default; --apply commits locally.
"""
import argparse
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import UUID, uuid5

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'Surya_Pharmacy.dbo.ItemDetail.latest-purchase-catalog'
NAMESPACE = UUID('f3fb31aa-6ed9-5326-95b2-595e87adf045')


def text(value):
    value = str(value).strip() if value is not None else ''
    return None if value in ('', '.', '-', 'NULL') else value


def convert(row, suppliers):
    sku, name, batch = text(row['itemId']), text(row['itemName']), text(row['BatchNo'])
    if not sku or not name: raise ValueError('Missing catalog ID or name')
    if not row['receivedItemId']: raise ValueError('No purchase history')
    if not batch: raise ValueError('Missing batch number')
    if not row['expiryDate']: raise ValueError('Missing expiry date')
    expiry = date.fromisoformat(row['expiryDate'][:10])
    prices = []
    for key in ('costPrice','MRP'):
        if row[key] is None: raise ValueError('Missing price')
        try: value = Decimal(str(row[key])).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
        except InvalidOperation: raise ValueError('Invalid price')
        if not value.is_finite() or value < 0 or value >= Decimal('10000000000'): raise ValueError('Invalid price')
        prices.append(str(value))
    generic = text(row['genericName'])
    for value, maximum in ((sku,50),(name,150),(batch,80),(generic,150)):
        if value and len(value)>maximum: raise ValueError('Field too long')
    return dict(name=name,generic_name=generic,sku=sku,batch_number=batch,expiry_date=expiry.isoformat(),
                purchase_price=prices[0],selling_price=prices[1],reorder_level=10,
                supplier_id=suppliers.get(row['vendorId']))


def run(source, database, report, actor_id, apply=False):
    raw = source.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    rows = [json.loads(line) for line in raw.decode('utf-8-sig').splitlines() if line.strip()]
    ids = [r['itemId'] for r in rows]
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate source item IDs')
    local = sqlite3.connect(database, timeout=10)
    local.row_factory = sqlite3.Row
    local.execute('PRAGMA foreign_keys=ON')
    if apply:
        backup = database.parent / 'backups' / ('before-medicine-import-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.sqlite3')
        backup.parent.mkdir(exist_ok=True)
        with sqlite3.connect(backup) as destination: local.backup(destination)
        backup.chmod(0o600)
    local.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
    try:
        actor = local.execute('SELECT role FROM employee_table WHERE id=?',(actor_id,)).fetchone()
        if not actor or actor['role']!='superadmin': raise ValueError('Select the importing superadmin account')
        suppliers = dict(local.execute("SELECT source_id,supplier_id FROM supplier_import_sources WHERE source='Surya_Pharmacy.dbo.vendorProfile'"))
        mappings = dict(local.execute("SELECT local_id,cloud_id FROM sync_identities WHERE entity='suppliers' AND deleted=0 AND version>0"))
        if apply:
            local.execute('''CREATE TABLE IF NOT EXISTS medicine_import_sources (
                source TEXT NOT NULL, source_id TEXT NOT NULL, medicine_id INTEGER NOT NULL REFERENCES medicines(id),
                raw_json TEXT NOT NULL, import_sha256 TEXT NOT NULL, imported_at TEXT NOT NULL,
                PRIMARY KEY(source,source_id))''')
        has_provenance = local.execute("SELECT 1 FROM sqlite_master WHERE name='medicine_import_sources'").fetchone()
        existing = dict(local.execute('SELECT sku,id FROM medicines'))
        prepared, skipped = [], []
        already = 0
        for row in rows:
            try: payload = convert(row,suppliers)
            except ValueError as error:
                skipped.append({'source_id':row['itemId'],'name':row['itemName'],'reason':str(error)})
                continue
            if payload['sku'] in existing:
                same = local.execute('SELECT medicine_id FROM medicine_import_sources WHERE source=? AND source_id=?',(SOURCE,row['itemId'])).fetchone() if has_provenance else None
                if not same or same[0]!=existing[payload['sku']]: raise ValueError('SKU already exists outside this import: '+payload['sku'])
                already += 1
                continue
            if payload['supplier_id'] is not None and payload['supplier_id'] not in mappings:
                raise ValueError('Supplier has no synchronized cloud identity')
            prepared.append((row,payload))
        summary = {'source_records':len(rows),'new_records':len(prepared),'already_imported':already,
                   'held_for_review':len(skipped),'review_reasons':dict(Counter(r['reason'] for r in skipped)),
                   'opening_stock':0,'mode':'latest-purchase catalog only','actor_id':actor_id,'applied':apply}
        stamp = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        for row,payload in prepared if apply else []:
            keys = list(payload)
            cursor = local.execute('INSERT INTO medicines ('+','.join(keys)+',stock_quantity) VALUES ('+','.join('?' for _ in keys)+',0)',tuple(payload.values()))
            local_id = cursor.lastrowid
            cloud_id = str(uuid5(NAMESPACE,row['itemId']))
            local.execute("INSERT INTO sync_identities(entity,local_id,cloud_id,version,deleted) VALUES ('medicines',?,?,0,0)",(local_id,cloud_id))
            queued = dict(payload)
            if queued['supplier_id'] is not None: queued['supplier_id'] = mappings[queued['supplier_id']]
            local.execute('''INSERT INTO sync_outbox(operation_id,actor_id,entity,cloud_id,payload,deleted,base_version,state,created_at)
                VALUES (?,?,'medicines',?,?,0,NULL,'pending',?)''',(str(uuid5(UUID(cloud_id),'initial-import')),actor_id,cloud_id,json.dumps(queued),stamp))
            local.execute('INSERT INTO medicine_import_sources VALUES (?,?,?,?,?,?)',(SOURCE,row['itemId'],local_id,json.dumps(row,sort_keys=True),source_hash,stamp))
        if apply:
            if local.execute('PRAGMA foreign_key_check').fetchall(): raise ValueError('Foreign key check failed')
            local.commit()
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps({'summary':summary,'held_for_review':skipped},indent=2)+'\n')
        report.chmod(0o600)
        print(json.dumps(summary))
        return summary
    finally:
        local.rollback()
        local.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'backups/medicine-import/catalog.jsonl')
    parser.add_argument('--database',type=Path,default=ROOT/'temp.db')
    parser.add_argument('--report',type=Path,default=ROOT/'backups/medicine-import/report.json')
    parser.add_argument('--actor-id',type=int,required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    run(args.source,args.database,args.report,args.actor_id,args.apply)
