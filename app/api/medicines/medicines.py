from fastapi import Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.base import BaseAPI, RouteDefinition
from app.api.common import get_or_404
from app.database import get_db
from app.models import Medicine, StockMovement, StockMovementType, Supplier
from app.schemas import MedicineCreate, MedicineRead, StockAdjustment, StockMovementRead


class MedicineAPI(BaseAPI):
    methods = ["GET", "POST"]
    routes = [
        RouteDefinition("/api/v1/medicines", "get", "GET", response_model=list[MedicineRead], tags=["Medicines"]),
        RouteDefinition("/api/v1/medicines", "post", "POST", response_model=MedicineRead,
                        status_code=status.HTTP_201_CREATED, tags=["Medicines"]),
        RouteDefinition("/api/v1/medicines/{medicine_id}/stock", "post_stock", "POST", response_model=MedicineRead,
                        tags=["Medicines"]),
        RouteDefinition("/api/v1/medicines/{medicine_id}/movements", "get_movements", "GET",
                        response_model=list[StockMovementRead], tags=["Medicines"]),
    ]

    @staticmethod
    def get(search: str | None = None, low_stock_only: bool = False,
            db: Session = Depends(get_db)) -> list[Medicine]:
        statement = select(Medicine).order_by(Medicine.name)
        if search:
            term = f"%{search.strip()}%"
            statement = statement.where(or_(Medicine.name.ilike(term), Medicine.generic_name.ilike(term), Medicine.sku.ilike(term)))
        if low_stock_only:
            statement = statement.where(Medicine.stock_quantity <= Medicine.reorder_level)
        return list(db.scalars(statement))

    @staticmethod
    def post(payload: MedicineCreate, db: Session = Depends(get_db)) -> Medicine:
        if payload.supplier_id is not None:
            get_or_404(db, Supplier, payload.supplier_id, "Supplier")
        medicine = Medicine(**payload.model_dump())
        db.add(medicine)
        try:
            db.flush()
            if medicine.stock_quantity:
                db.add(StockMovement(medicine_id=medicine.id, movement_type=StockMovementType.received,
                                     quantity_change=medicine.stock_quantity, note="Opening stock"))
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="A medicine with this SKU already exists")
        db.refresh(medicine)
        return medicine

    @staticmethod
    def post_stock(medicine_id: int, payload: StockAdjustment, db: Session = Depends(get_db)) -> Medicine:
        medicine = get_or_404(db, Medicine, medicine_id, "Medicine")
        updated_quantity = medicine.stock_quantity + payload.quantity_change
        if updated_quantity < 0:
            raise HTTPException(status_code=422, detail="Stock cannot become negative")
        medicine.stock_quantity = updated_quantity
        db.add(StockMovement(medicine_id=medicine.id, movement_type=StockMovementType.adjustment,
                             quantity_change=payload.quantity_change, note=payload.note))
        db.commit()
        db.refresh(medicine)
        return medicine

    @staticmethod
    def get_movements(medicine_id: int, db: Session = Depends(get_db)) -> list[StockMovement]:
        get_or_404(db, Medicine, medicine_id, "Medicine")
        return list(db.scalars(select(StockMovement).where(StockMovement.medicine_id == medicine_id)
                               .order_by(StockMovement.created_at.desc())))
