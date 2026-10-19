"""Authenticated, atomic, retry-safe purchase order creation and retrieval."""
from datetime import date
from decimal import Decimal
from hashlib import sha256
from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from app.api.base import BaseAPI, RouteDefinition
from app.database import get_db
from app.models import Medicine, Supplier
from app.models.sync import SyncIdentity
from app.models.purchase_orders import PurchaseOrder, PurchaseOrderItem
from app.schemas_purchase_orders import PurchaseOrderCreate, PurchaseOrderRead
from app.services.auth import get_current_profile


def require_purchasing(actor):
    if actor.role not in ('pharmacist', 'admin', 'superadmin'):
        raise HTTPException(403, 'Pharmacist or administrator access required')


def replay(order, actor, fingerprint):
    if order.created_by != actor.id or order.request_hash != fingerprint:
        raise HTTPException(409, 'Purchase order reference has already been used for another request')
    return order


class PurchaseOrderAPI(BaseAPI):
    methods = ['GET', 'POST']
    routes = [
        RouteDefinition('/api/v1/purchase-orders', 'get', 'GET', response_model=list[PurchaseOrderRead], tags=['Purchase Orders']),
        RouteDefinition('/api/v1/purchase-orders', 'post', 'POST', response_model=PurchaseOrderRead, status_code=201, tags=['Purchase Orders']),
        RouteDefinition('/api/v1/purchase-orders/{order_id}', 'detail', 'GET', response_model=PurchaseOrderRead, tags=['Purchase Orders']),
    ]

    @staticmethod
    def get(actor=Depends(get_current_profile), db: Session = Depends(get_db)):
        require_purchasing(actor)
        return list(db.scalars(select(PurchaseOrder).options(selectinload(PurchaseOrder.items)).order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id.desc())))

    @staticmethod
    def detail(order_id: int, actor=Depends(get_current_profile), db: Session = Depends(get_db)):
        require_purchasing(actor)
        order = db.get(PurchaseOrder, order_id)
        if order is None:
            raise HTTPException(404, 'Purchase order not found')
        return order

    @staticmethod
    def post(payload: PurchaseOrderCreate, actor=Depends(get_current_profile), db: Session = Depends(get_db)):
        require_purchasing(actor)
        fingerprint = sha256(payload.model_dump_json().encode()).hexdigest()
        prior = db.scalar(select(PurchaseOrder).where(PurchaseOrder.request_id == str(payload.request_id)))
        if prior:
            return replay(prior, actor, fingerprint)
        if payload.expected_delivery and payload.expected_delivery < date.today():
            raise HTTPException(422, 'Expected delivery cannot be in the past')
        deleted_suppliers = select(SyncIdentity.local_id).where(SyncIdentity.entity == 'suppliers', SyncIdentity.deleted == True)
        supplier = db.scalar(select(Supplier).where(Supplier.id == payload.supplier_id, ~Supplier.id.in_(deleted_suppliers)))
        if supplier is None:
            raise HTTPException(404, 'Supplier is unavailable')
        medicine_ids = [item.medicine_id for item in payload.items]
        deleted_medicines = select(SyncIdentity.local_id).where(SyncIdentity.entity == 'medicines', SyncIdentity.deleted == True)
        catalog = {medicine.id: medicine for medicine in db.scalars(select(Medicine).where(Medicine.id.in_(medicine_ids), ~Medicine.id.in_(deleted_medicines)))}
        if len(catalog) != len(medicine_ids):
            raise HTTPException(404, 'One or more medicines are unavailable')
        total = sum((item.quantity * item.unit_price for item in payload.items), Decimal('0.00'))
        if total > Decimal('9999999999.99'):
            raise HTTPException(422, 'Purchase order total exceeds the supported amount')
        order = PurchaseOrder(request_id=str(payload.request_id), request_hash=fingerprint, created_by=actor.id,
                              supplier_id=supplier.id, supplier_name=supplier.name, currency=payload.currency,
                              expected_delivery=payload.expected_delivery, notes=payload.notes,
                              total_amount=total, status='pending_approval')
        order.items = [PurchaseOrderItem(medicine_id=item.medicine_id, medicine_name=catalog[item.medicine_id].name,
                       sku=catalog[item.medicine_id].sku, batch_number=catalog[item.medicine_id].batch_number,
                       quantity=item.quantity, unit_price=item.unit_price, line_total=item.quantity * item.unit_price)
                       for item in payload.items]
        db.add(order)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            prior = db.scalar(select(PurchaseOrder).where(PurchaseOrder.request_id == str(payload.request_id)))
            if prior:
                return replay(prior, actor, fingerprint)
            raise HTTPException(409, 'Supplier or medicine changed. Refresh the catalog before retrying.')
        db.refresh(order)
        return order
