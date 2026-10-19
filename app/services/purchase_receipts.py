"""Atomic purchase receipts with immutable ordered quantities and retry protection."""
from hashlib import sha256
from fastapi import Depends, HTTPException
from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from app.database import get_db, lock_inventory
from app.models import Medicine, StockMovement, StockMovementType
from app.models.purchase_orders import PurchaseOrder, PurchaseReceipt, PurchaseReceiptItem
from app.models.sync import SyncIdentity
from app.schemas_purchase_orders import PurchaseOrderRead, ReceiptCreate
from app.services.auth import get_current_profile

PENDING = ('pending_approval', 'approved', 'ordered', 'partially_received')


def authorize(actor):
    if actor.role not in ('pharmacist', 'admin', 'superadmin'):
        raise HTTPException(403, 'Pharmacist or administrator access required')


def received_totals(db):
    return dict(db.execute(select(PurchaseReceiptItem.order_item_id, func.sum(PurchaseReceiptItem.quantity))
                           .group_by(PurchaseReceiptItem.order_item_id)).all())


def pending_receipt(actor=Depends(get_current_profile), db: Session = Depends(get_db)):
    authorize(actor)
    orders = db.scalars(select(PurchaseOrder).options(selectinload(PurchaseOrder.items))
                        .where(PurchaseOrder.status.in_(PENDING)).order_by(PurchaseOrder.id)).all()
    totals = received_totals(db)
    result = []
    for order in orders:
        data = PurchaseOrderRead.model_validate(order).model_dump(mode='json')
        for item in data['items']:
            item['received_quantity'] = totals.get(item['id'], 0)
            item['remaining_quantity'] = max(0, item['quantity'] - item['received_quantity'])
        result.append(data)
    return result


def receive(order_id: int, payload: ReceiptCreate, actor=Depends(get_current_profile), db: Session = Depends(get_db)):
    authorize(actor)
    from app.config import get_settings
    if get_settings().sync_enabled:
        raise HTTPException(409, 'PO receiving requires cloud receipt/allocation support in sync mode')
    lock_inventory(db)
    fingerprint = sha256(payload.model_dump_json().encode()).hexdigest()

    def replay(prior):
        if prior.order_id != order_id or prior.created_by != actor.id or prior.request_hash != fingerprint:
            raise HTTPException(409, 'Receipt reference already used for another request')
        return db.get(PurchaseOrder, order_id)

    prior = db.scalar(select(PurchaseReceipt).where(PurchaseReceipt.request_id == str(payload.request_id)))
    if prior:
        return replay(prior)
    order = db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == order_id).with_for_update())
    if order is None:
        raise HTTPException(404, 'Purchase order not found')
    if order.status not in PENDING:
        raise HTTPException(409, 'This order is no longer pending receipt')
    catalog = {item.id: item for item in order.items}
    if set(catalog) != {item.order_item_id for item in payload.items}:
        raise HTTPException(422, 'Include every PO item exactly once; use zero for undelivered items')
    deleted_ids = set(db.scalars(select(SyncIdentity.local_id).where(
        SyncIdentity.entity == 'medicines', SyncIdentity.deleted == True)))
    if any(item.medicine_id in deleted_ids for item in order.items):
        raise HTTPException(409, 'A medicine is no longer available')
    receipt = PurchaseReceipt(request_id=str(payload.request_id), request_hash=fingerprint,
                              order_id=order_id, created_by=actor.id)
    receipt.items = []
    try:
        for item in payload.items:
            if not item.quantity:
                continue
            medicine_id = catalog[item.order_item_id].medicine_id
            changed = db.execute(update(Medicine).where(Medicine.id == medicine_id,
                                 Medicine.stock_quantity <= 2147483647 - item.quantity)
                                 .values(stock_quantity=Medicine.stock_quantity + item.quantity))
            if changed.rowcount != 1:
                raise HTTPException(409, 'Medicine unavailable or stock exceeds supported limit')
            receipt.items.append(PurchaseReceiptItem(order_item_id=item.order_item_id, quantity=item.quantity))
            db.add(StockMovement(medicine_id=medicine_id, movement_type=StockMovementType.received,
                                 quantity_change=item.quantity, note=f'PO #{order_id}; receipt {payload.request_id}'))
        db.add(receipt)
        db.flush()
        totals = received_totals(db)
        order.status = 'received' if payload.close_order or all(totals.get(i.id, 0) >= i.quantity for i in order.items) else 'partially_received'
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = db.scalar(select(PurchaseReceipt).where(PurchaseReceipt.request_id == str(payload.request_id)))
        if prior:
            return replay(prior)
        raise HTTPException(409, 'Receipt changed concurrently; refresh before retrying')
    except Exception:
        db.rollback()
        raise
    db.refresh(order)
    return order
