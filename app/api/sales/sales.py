from datetime import date, datetime, timezone
from hashlib import sha256
from app.services.sync_queue import queue_if_enabled
from decimal import Decimal, ROUND_HALF_UP

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, joinedload

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
from app.models.sales import CheckoutReceipt, SalePayment
from app.models.sync import SyncIdentity
from app.models import PharmacistProfile
from app.services.auth import get_current_profile


def invoice_load_options():
    # Batch related invoice data instead of querying separately for each sale/line.
    return (joinedload(Sale.payment), joinedload(Sale.company_record),
            selectinload(Sale.items).joinedload(SaleItem.discount_record))

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
        doctors = db.execute(select(PharmacistProfile.first_name, PharmacistProfile.last_name).where(PharmacistProfile.role == 'doctor')).all()
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
    def get(db: Session = Depends(get_db), from_at: datetime | None = None,
            to_at: datetime | None = None) -> list[Sale]:
        def utc_naive(value):
            return value.astimezone(timezone.utc).replace(tzinfo=None) if value and value.tzinfo else value
        start, end = utc_naive(from_at), utc_naive(to_at)
        if start is not None and end is not None and start >= end:
            raise HTTPException(422,'The sales date range must end after it starts')
        statement = select(Sale).options(*invoice_load_options())
        if start is not None: statement = statement.where(Sale.created_at >= start)
        if end is not None: statement = statement.where(Sale.created_at < end)
        return list(db.scalars(statement.order_by(Sale.created_at.desc(),Sale.id.desc())))

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
            exclusions = {} if payload.customer_mobile else {'customer_mobile': True}
            if all(not item.discount_percent for item in payload.items): exclusions['items'] = {'__all__': {'discount_percent'}}
            receipt_json = payload.model_dump_json(exclude=exclusions)
            receipt_hash = sha256(receipt_json.encode()).hexdigest()
            receipt = db.get(CheckoutReceipt, str(payload.request_id))
            if receipt:
                if receipt.actor_id != db.info.get('actor_id') or receipt.payload_hash != receipt_hash:
                    raise HTTPException(409, 'Checkout reference has already been used for another request')
                return db.scalar(select(Sale).options(*invoice_load_options()).where(Sale.id == receipt.sale_id))
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
        line_totals = {item.medicine_id: (medicines[item.medicine_id].selling_price * item.quantity * (Decimal('100')-item.discount_percent)/100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) for item in payload.items}
        subtotal = sum((line_totals[item.medicine_id] for item in payload.items), Decimal("0"))
        if isinstance(payload, CheckoutCreate):
            payment = payload.payment
            if payment.tendered < subtotal or (payment.method != 'cash' and payment.tendered != subtotal):
                raise HTTPException(422, 'Payment must cover the current bill total; digital payments must match it exactly')
        customer_id = payload.customer_id
        if isinstance(payload, CheckoutCreate):
            from app.services.customer_mobile import customers_by_mobile
            matches = customers_by_mobile(db,payload.customer_mobile) if payload.customer_mobile else []
            same_name = [customer for customer in matches if customer.full_name.strip().casefold()==payload.patient_name.casefold()]
            customer = same_name[0] if len(same_name)==1 else None
            if customer is None:
                customer = Customer(full_name=payload.patient_name,phone=payload.customer_mobile)
                db.add(customer); db.flush()
                queue_if_enabled(db, 'customers', customer)
            prescription = Prescription(customer_id=customer.id, doctor_name=payload.prescribed_by,
                                        prescribed_on=date.today(), status=PrescriptionStatus.pending)
            db.add(prescription); db.flush()
            queue_if_enabled(db, 'prescriptions', prescription)
            customer_id = customer.id
        sale = Sale(customer_id=customer_id, prescription_id=prescription.id if prescription else None,
                    subtotal=subtotal, tax_amount=payload.tax_amount, total_amount=subtotal + payload.tax_amount)
        from app.models.company import CompanyRegistration, SaleCompany, SaleLineDiscount
        from app.models.billing import BillingSettings
        company = db.get(CompanyRegistration,1)
        legacy = db.get(BillingSettings,1) if company is None else None
        sale.company_record = SaleCompany(company_name=company.company_name if company else None,
            address=company.address if company else None, gstin=company.gstin if company else legacy.gstin if legacy else None)
        db.add(sale)
        db.flush()
        for item in payload.items:
            medicine = medicines[item.medicine_id]
            line_total = line_totals[item.medicine_id]
            medicine.stock_quantity -= item.quantity
            entry = SaleItem(sale_id=sale.id, medicine_id=medicine.id, quantity=item.quantity,
                            unit_price=medicine.selling_price, line_total=line_total)
            entry.discount_record = SaleLineDiscount(original_unit_price=medicine.selling_price, discount_percent=item.discount_percent)
            db.add(entry)
            db.add(StockMovement(medicine_id=medicine.id, movement_type=StockMovementType.sale,
                                 quantity_change=-item.quantity, note=f"Sale #{sale.id}"))
        if prescription:
            prescription.status = PrescriptionStatus.dispensed
        if isinstance(payload, CheckoutCreate):
            sale.payment = SalePayment(method=payload.payment.method, amount=sale.total_amount,
                tendered=payload.payment.tendered, change=payload.payment.tendered-sale.total_amount,
                reference=payload.payment.reference)
        queue_if_enabled(db, 'sales', sale)
        if receipt_hash:
            db.add(CheckoutReceipt(request_id=str(payload.request_id), actor_id=db.info['actor_id'],
                                   payload_hash=receipt_hash, sale_id=sale.id))
        saved_sale_id = sale.id
        db.commit()
        return db.scalar(select(Sale).options(*invoice_load_options()).where(Sale.id == saved_sale_id))
