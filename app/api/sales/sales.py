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
from app.schemas import SaleCreate, SaleRead


class SaleAPI(BaseAPI):
    methods = ["GET", "POST"]
    routes = [
        RouteDefinition("/api/v1/sales", "get", "GET", response_model=list[SaleRead], tags=["Sales"]),
        RouteDefinition("/api/v1/sales", "post", "POST", response_model=SaleRead,
                        status_code=status.HTTP_201_CREATED, tags=["Sales"]),
    ]

    @staticmethod
    def get(db: Session = Depends(get_db)) -> list[Sale]:
        return list(db.scalars(select(Sale).options(selectinload(Sale.items)).order_by(Sale.created_at.desc())))

    @staticmethod
    def post(payload: SaleCreate, db: Session = Depends(get_db)) -> Sale:
        """Atomically create a bill, decrement stock, and mark its prescription dispensed."""
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
        for item in payload.items:
            if medicines[item.medicine_id].stock_quantity < item.quantity:
                raise HTTPException(status_code=422, detail=f"Insufficient stock for {medicines[item.medicine_id].name}")
        subtotal = sum((medicines[item.medicine_id].selling_price * item.quantity for item in payload.items), Decimal("0"))
        sale = Sale(customer_id=payload.customer_id, prescription_id=payload.prescription_id,
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
        db.commit()
        return db.scalar(select(Sale).options(selectinload(Sale.items)).where(Sale.id == sale.id))
