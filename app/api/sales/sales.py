from datetime import date
from hashlib import sha256
from app.services.sync_queue import queue_if_enabled
from decimal import Decimal

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.base import BaseAPI, RouteDefinition
from app.api.common import get_or_404
from app.database import get_db
from app.models import (
    Customer,
    Medicine,
    Prescription,
    PrescriptionStatus,
    Sale,
    SaleItem,
    StockMovement,
    StockMovementType,
)
from app.schemas import SaleCreate, SaleRead, CheckoutCreate
from app.models.sales import CheckoutReceipt
from app.models.sync import SyncIdentity
from app.models import PharmacistProfile
from app.services.auth import get_current_profile


class SaleAPI(BaseAPI):
    methods = ["GET", "POST"]
    routes = [
        RouteDefinition('/api/v1/sales/prescribers', 'prescribers', 'GET', tags=['Sales']),
        RouteDefinition('/api/v1/sales/checkout', 'checkout', 'POST', response_model=SaleRead,
                        status_code=201, tags=['Sales']),
        RouteDefinition("/api/v1/sales", "get", "GET", response_model=list[SaleRead], tags=["Sales"]),
        RouteDefinition("/api/v1/sales", "post", "POST", response_model=SaleRead,
                        status_code=status.HTTP_201_CREATED, tags=["Sales"]),
    ]

    @staticmethod
    def prescribers(db: Session = Depends(get_db)):
        doctors = db.scalars(select(PharmacistProfile).where(PharmacistProfile.role == 'doctor')).all()
        names = set(db.scalars(select(Prescription.doctor_name).distinct()))
        names.update(f'{p.first_name} {p.last_name}' for p in doctors)
        return sorted(name for name in names if name)

    @staticmethod
    def checkout(payload: CheckoutCreate, actor=Depends(get_current_profile), db: Session = Depends(get_db)):
        if actor.role not in ('pharmacist', 'admin', 'superadmin'):
            raise HTTPException(403, 'Pharmacist or administrator access required')
        if payload.customer_id is not None or payload.prescription_id is not None or payload.tax_amount:
            raise HTTPException(422, 'Use patient and prescriber details for this checkout; tax is not configured')
        return SaleAPI.post(payload, db)

    @staticmethod
    def get(db: Session = Depends(get_db)) -> list[Sale]:
        return list(db.scalars(select(Sale).options(selectinload(Sale.items)).order_by(Sale.created_at.desc())))

    @staticmethod
    def post(payload: SaleCreate, db: Session = Depends(get_db)) -> Sale:
        """Atomically create a bill, decrement stock, and mark its prescription dispensed."""
        if db.bind.dialect.name == 'sqlite':
            from sqlalchemy import text
            db.rollback()
            db.execute(text('BEGIN IMMEDIATE'))
        from app.database import lock_inventory
        lock_inventory(db)
        receipt_hash = None
        if isinstance(payload, CheckoutCreate):
            receipt_hash = sha256(payload.model_dump_json().encode()).hexdigest()
            receipt = db.get(CheckoutReceipt, str(payload.request_id))
            if receipt:
                if receipt.actor_id != db.info.get('actor_id') or receipt.payload_hash != receipt_hash:
                    raise HTTPException(409, 'Checkout reference has already been used for another request')
                return db.scalar(select(Sale).options(selectinload(Sale.items)).where(Sale.id == receipt.sale_id))
        if payload.customer_id is not None:
            get_or_404(db, Customer, payload.customer_id, "Customer")
        prescription = None
        if payload.prescription_id is not None:
            prescription = get_or_404(db, Prescription, payload.prescription_id, "Prescription")
            if prescription.status != PrescriptionStatus.pending:
                raise HTTPException(status_code=422, detail="Only pending prescriptions can be dispensed")
        medicine_ids = [item.medicine_id for item in payload.items]
        if len(medicine_ids) != len(set(medicine_ids)):
            raise HTTPException(status_code=422, detail="Each medicine may appear only once in a sale")
        medicines = {medicine.id: medicine for medicine in db.scalars(select(Medicine).where(Medicine.id.in_(medicine_ids)))}
        if len(medicines) != len(medicine_ids):
            raise HTTPException(status_code=404, detail="One or more medicines were not found")
        deleted_ids = set(db.scalars(select(SyncIdentity.local_id).where(
            SyncIdentity.entity == 'medicines', SyncIdentity.deleted == True,
            SyncIdentity.local_id.in_(medicine_ids))))
        for item in payload.items:
            if item.medicine_id in deleted_ids or medicines[item.medicine_id].expiry_date < date.today():
                raise HTTPException(422, 'An expired or removed medicine cannot be sold')
            if medicines[item.medicine_id].stock_quantity < item.quantity:
                raise HTTPException(status_code=422, detail=f"Insufficient stock for {medicines[item.medicine_id].name}")
        customer_id = payload.customer_id
        if isinstance(payload, CheckoutCreate):
            customer = Customer(full_name=payload.patient_name)
            db.add(customer); db.flush()
            queue_if_enabled(db, 'customers', customer)
            prescription = Prescription(customer_id=customer.id, doctor_name=payload.prescribed_by,
                                        prescribed_on=date.today(), status=PrescriptionStatus.pending)
            db.add(prescription); db.flush()
            queue_if_enabled(db, 'prescriptions', prescription)
            customer_id = customer.id
        subtotal = sum((medicines[item.medicine_id].selling_price * item.quantity for item in payload.items), Decimal("0"))
        sale = Sale(customer_id=customer_id, prescription_id=prescription.id if prescription else None,
                    subtotal=subtotal, tax_amount=payload.tax_amount, total_amount=subtotal + payload.tax_amount)
        db.add(sale)
        db.flush()
        for item in payload.items:
            medicine = medicines[item.medicine_id]
            line_total = medicine.selling_price * item.quantity
            medicine.stock_quantity -= item.quantity
            db.add(SaleItem(sale_id=sale.id, medicine_id=medicine.id, quantity=item.quantity,
                            unit_price=medicine.selling_price, line_total=line_total))
            db.add(StockMovement(medicine_id=medicine.id, movement_type=StockMovementType.sale,
                                 quantity_change=-item.quantity, note=f"Sale #{sale.id}"))
        if prescription:
            prescription.status = PrescriptionStatus.dispensed
        queue_if_enabled(db, 'sales', sale)
        if receipt_hash:
            db.add(CheckoutReceipt(request_id=str(payload.request_id), actor_id=db.info['actor_id'],
                                   payload_hash=receipt_hash, sale_id=sale.id))
        db.commit()
        return db.scalar(select(Sale).options(selectinload(Sale.items)).where(Sale.id == sale.id))
