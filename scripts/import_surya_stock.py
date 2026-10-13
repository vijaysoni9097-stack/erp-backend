"""Import source stock totals as a reference snapshot, never saleable allocations."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def run():
    source = ROOT / 'backups/stock-import/surya-stock.json'
    raw = source.read_bytes()
    rows = json.loads(raw)
    assert len({r['itemId'] for r in rows}) == len(rows), 'Duplicate source IDs'
    for r in rows:
        assert r['quantity'] is None or type(r['quantity']) is int
        assert r['stock_rows'] in (0, 1), 'Multiple stock rows require review'
    stamp = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(ROOT / 'temp.db') as db:
        backup = ROOT / 'backups/stock-import' / ('before-stock-' + datetime.now().strftime('%Y%m%d%H%M%S%f') + '.sqlite3')
        with sqlite3.connect(backup) as target:
            db.backup(target)
        backup.chmod(0o600)
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS surya_stock_snapshot (
            source_id TEXT PRIMARY KEY, name TEXT NOT NULL, quantity INTEGER,
            source_modified_on TEXT, imported_at TEXT NOT NULL, source_sha256 TEXT NOT NULL)''')
        db.execute('DELETE FROM surya_stock_snapshot')
        db.executemany('INSERT INTO surya_stock_snapshot VALUES (?,?,?,?,?,?)',
            [(r['itemId'],r['itemName'],r['quantity'],r['modified_on'],stamp,hashlib.sha256(raw).hexdigest()) for r in rows])
        print('Imported reference stock for', len(rows), 'items. Saleable stock and sync queue unchanged.')

if __name__ == '__main__':
    run()
