"""Read-only stock snapshot from the restored Surya Pharmacy database."""
from datetime import date
from typing import Literal
from fastapi import Depends, Query, HTTPException
from sqlalchemy import inspect, text, select, table, column, literal, union_all, func, case, or_, String, cast
from app.models import Medicine
from app.models.sync import SyncIdentity
from sqlalchemy.orm import Session
from app.api.base import BaseAPI, RouteDefinition
from app.database import get_db

class StockSnapshotAPI(BaseAPI):
    methods = ['GET']
    routes = [
        RouteDefinition('/api/v1/inventory/stock/summary', 'summary', 'GET', tags=['Inventory']),
        RouteDefinition('/api/v1/inventory/stock/search', 'search', 'GET', tags=['Inventory']),
        RouteDefinition('/api/v1/inventory/stock', 'page', 'GET', tags=['Inventory']),
        RouteDefinition('/api/v1/inventory/source-stock', 'get', 'GET', tags=['Inventory'])]

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

    @staticmethod
    def stock_rows(db):
        deleted = select(SyncIdentity.local_id).where(SyncIdentity.entity == 'medicines', SyncIdentity.deleted == True)
        columns = [Medicine.sku.label('source_id'), Medicine.name, literal(None).label('quantity'), literal(None).label('source_modified_on'), Medicine.id.label('medicine_id'), Medicine.stock_quantity.label('allocated_quantity'), Medicine.expiry_date]
        catalog = select(*columns).where(~Medicine.id.in_(deleted))
        if not inspect(db.get_bind()).has_table('surya_stock_snapshot'):
            return catalog.subquery()
        snapshot = table('surya_stock_snapshot', *(column(name) for name in ('source_id', 'name', 'quantity', 'source_modified_on', 'imported_at')))
        source_id = cast(snapshot.c.source_id, String)
        historical = select(source_id.label('source_id'), snapshot.c.name, snapshot.c.quantity,
            snapshot.c.source_modified_on, Medicine.id.label('medicine_id'), Medicine.stock_quantity.label('allocated_quantity'), Medicine.expiry_date
        ).select_from(snapshot.outerjoin(Medicine, Medicine.sku == source_id)).where(or_(Medicine.id.is_(None), ~Medicine.id.in_(deleted)))
        catalog = catalog.where(~Medicine.sku.in_(select(source_id)))
        return union_all(historical, catalog).subquery()

    @staticmethod
    def paged(db, page, page_size, stock_filter, expiry_from, expiry_to, term=None):
        if expiry_from and expiry_to and expiry_from > expiry_to:
            raise HTTPException(422, 'Expiry from must be on or before expiry to')
        rows = StockSnapshotAPI.stock_rows(db)
        conditions = []
        if term:
            term = term.strip()
            if len(term) < 2:
                raise HTTPException(422, 'Enter at least two characters to search stock')
            conditions.append(or_(rows.c.name.icontains(term, autoescape=True), rows.c.source_id.icontains(term, autoescape=True)))
        if expiry_from: conditions.append(rows.c.expiry_date >= expiry_from)
        if expiry_to: conditions.append(rows.c.expiry_date <= expiry_to)
        if stock_filter == 'positive': conditions.append(rows.c.allocated_quantity > 0)
        elif stock_filter == 'zero': conditions.append(rows.c.allocated_quantity == 0)
        elif stock_filter == 'review': conditions.append(or_(rows.c.allocated_quantity.is_(None), rows.c.allocated_quantity < 0))
        query = select(rows).where(*conditions)
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        records = db.execute(query.order_by(rows.c.name, rows.c.source_id).offset((page-1)*page_size).limit(page_size)).mappings()
        return dict(items=[{**dict(row), 'current_quantity':row['allocated_quantity']} for row in records], total=total, page=page, page_size=page_size, has_more=page*page_size < total)

    @staticmethod
    def page(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100), stock_filter: Literal['all','positive','zero','review'] = 'all', expiry_from: date | None = None, expiry_to: date | None = None, db: Session = Depends(get_db)):
        return StockSnapshotAPI.paged(db, page, page_size, stock_filter, expiry_from, expiry_to)

    @staticmethod
    def search(q: str = Query(min_length=2, max_length=150), page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100), stock_filter: Literal['all','positive','zero','review'] = 'all', expiry_from: date | None = None, expiry_to: date | None = None, db: Session = Depends(get_db)):
        return StockSnapshotAPI.paged(db, page, page_size, stock_filter, expiry_from, expiry_to, q)

    @staticmethod
    def summary(db: Session = Depends(get_db)):
        deleted = select(SyncIdentity.local_id).where(SyncIdentity.entity == 'medicines', SyncIdentity.deleted == True)
        row = db.execute(select(func.coalesce(func.sum(Medicine.stock_quantity),0).label('units'),
            func.count(case((Medicine.stock_quantity > 0, 1))).label('positive'),
            func.count(case((Medicine.stock_quantity == 0, 1))).label('zero')).where(~Medicine.id.in_(deleted))).mappings().one()
        rows = StockSnapshotAPI.stock_rows(db)
        review = db.scalar(select(func.count()).select_from(rows).where(or_(rows.c.allocated_quantity.is_(None), rows.c.allocated_quantity < 0)))
        return {**dict(row), 'review':review}
