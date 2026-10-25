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

PENDING = ('approved', 'ordered', 'partially_received')


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
    medicine_ids = {item.medicine_id for order in orders for item in order.items}
    medicines = {m.id: m for m in db.scalars(select(Medicine).where(Medicine.id.in_(medicine_ids)))} if medicine_ids else {}
    result = []
    for order in orders:
        data = PurchaseOrderRead.model_validate(order).model_dump(mode='json')
        for item in data['items']:
            medicine = medicines.get(item['medicine_id'])
            item['expiry_date'] = medicine.expiry_date.isoformat() if medicine else None
            item['unit'] = medicine.unit if medicine else 'number'
            item['selling_price'] = str(medicine.selling_price) if medicine else None
            item['received_quantity'] = totals.get(item['id'], 0)
            item['remaining_quantity'] = max(0, item['quantity'] - item['received_quantity'])
        result.append(data)
    return result


def receive(order_id: int, payload: ReceiptCreate, actor=Depends(get_current_profile), db: Session = Depends(get_db)):
    if actor.role not in ('admin', 'superadmin'):
        raise HTTPException(403, 'Admin delivery review required')
    from app.config import get_settings
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
            line = catalog[item.order_item_id]
            if item.quantity > line.quantity - received_totals(db).get(line.id, 0):
                raise HTTPException(422, 'Received quantity exceeds the approved remaining quantity')
            original = db.get(Medicine, line.medicine_id)
            if original is None:
                raise HTTPException(409, 'Medicine is unavailable')
            if original.batch_number == item.batch_number and original.expiry_date == item.expiry_date:
                target = original
                if target.stock_quantity > 0 and target.unit != item.unit:
                    raise HTTPException(422, 'Unit differs from existing stock. Receive a separate batch or use the existing unit.')
            elif original.stock_quantity == 0 and not original.sale_items and not original.stock_movements:
                target = original
                target.batch_number = item.batch_number
                target.expiry_date = item.expiry_date
            else:
                from uuid import uuid4
                target = Medicine(name=original.name, generic_name=original.generic_name,
                    sku=f"{original.sku[:25]}-{uuid4().hex[:20]}", batch_number=item.batch_number,
                    expiry_date=item.expiry_date, stock_quantity=0, reorder_level=original.reorder_level)
                db.add(target)
            target.unit = item.unit
            target.purchase_price = item.purchase_price
            target.selling_price = item.selling_price
            target.supplier_id = order.supplier_id
            db.flush()
            medicine_id = target.id
            changed = db.execute(update(Medicine).where(Medicine.id == medicine_id,
                                 Medicine.stock_quantity <= 2147483647 - item.quantity)
                                 .values(stock_quantity=Medicine.stock_quantity + item.quantity))
            if changed.rowcount != 1:
                raise HTTPException(409, 'Medicine unavailable or stock exceeds supported limit')
            receipt.items.append(PurchaseReceiptItem(order_item_id=item.order_item_id, quantity=item.quantity))
            db.add(StockMovement(medicine_id=medicine_id, movement_type=StockMovementType.received,
                                 quantity_change=item.quantity, note=f'PO #{order_id}; receipt {payload.request_id}; reviewed by admin #{actor.id}; batch {item.batch_number}; expiry {item.expiry_date}; unit {item.unit}; purchase {item.purchase_price}; selling {item.selling_price}'))
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
