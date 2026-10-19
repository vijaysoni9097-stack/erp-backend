"""Read-only stock snapshot from the restored Surya Pharmacy database."""
from fastapi import Depends
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from app.api.base import BaseAPI, RouteDefinition
from app.database import get_db

class StockSnapshotAPI(BaseAPI):
    methods = ['GET']
    routes = [RouteDefinition('/api/v1/inventory/source-stock', 'get', 'GET', tags=['Inventory'])]

    @staticmethod
    def get(db: Session = Depends(get_db)):
        if not inspect(db.get_bind()).has_table('surya_stock_snapshot'):
            return {'source': 'Surya Pharmacy', 'imported_at': None, 'items': []}
        rows = db.execute(text('''SELECT s.source_id, s.name, s.quantity,
            s.source_modified_on, s.imported_at, m.id medicine_id,
            m.stock_quantity allocated_quantity, m.expiry_date
            FROM surya_stock_snapshot s
            LEFT JOIN medicines m ON m.sku=s.source_id ORDER BY s.name,s.source_id''')).mappings().all()
        return {'source': 'Surya Pharmacy (restored backup)',
                'imported_at': rows[0]['imported_at'] if rows else None,
                'items': [dict(r) for r in rows]}
