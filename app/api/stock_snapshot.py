"""Read-only stock snapshot from the restored Surya Pharmacy database."""
from fastapi import Depends
from sqlalchemy import inspect, text, select
from app.models import Medicine
from app.models.sync import SyncIdentity
from sqlalchemy.orm import Session
from app.api.base import BaseAPI, RouteDefinition
from app.database import get_db

class StockSnapshotAPI(BaseAPI):
    methods = ['GET']
    routes = [RouteDefinition('/api/v1/inventory/source-stock', 'get', 'GET', tags=['Inventory'])]

    @staticmethod
    def get(db: Session = Depends(get_db)):
        deleted = select(SyncIdentity.local_id).where(SyncIdentity.entity == 'medicines', SyncIdentity.deleted == True)
        catalog = list(db.scalars(select(Medicine).where(~Medicine.id.in_(deleted))))
        def catalog_row(m):
            return dict(source_id=m.sku, name=m.name, quantity=None, source_modified_on=None, imported_at=None,
                        medicine_id=m.id, allocated_quantity=m.stock_quantity, expiry_date=m.expiry_date)
        if not inspect(db.get_bind()).has_table('surya_stock_snapshot'):
            return {'source': 'Medicine inventory', 'imported_at': None, 'items': [catalog_row(m) for m in catalog]}
        rows = db.execute(text('''SELECT s.source_id, s.name, s.quantity,
            s.source_modified_on, s.imported_at, m.id medicine_id,
            m.stock_quantity allocated_quantity, m.expiry_date
            FROM surya_stock_snapshot s
            LEFT JOIN medicines m ON m.sku=s.source_id ORDER BY s.name,s.source_id''')).mappings().all()
        items = [dict(r) for r in rows]
        known = {r['source_id'] for r in items}
        items.extend(catalog_row(m) for m in catalog if m.sku not in known)
        items.sort(key=lambda row: (row['name'], row['source_id']))
        return {'source': 'Surya Pharmacy (restored backup)',
                'imported_at': rows[0]['imported_at'] if rows else None,
                'items': items}
