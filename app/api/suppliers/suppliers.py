from fastapi import Depends, HTTPException, status
from app.models.sync import SyncIdentity
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.base import BaseAPI, RouteDefinition
from app.database import get_db
from app.models import Supplier
from app.schemas import SupplierCreate, SupplierRead


class SupplierAPI(BaseAPI):
    methods = ["GET", "POST", "PUT", "DELETE"]
    routes = [
        RouteDefinition('/api/v1/suppliers/{supplier_id}', 'put', 'PUT', response_model=SupplierRead, tags=['Suppliers']),
        RouteDefinition('/api/v1/suppliers/{supplier_id}', 'delete', 'DELETE', status_code=204, tags=['Suppliers']),
        RouteDefinition("/api/v1/suppliers", "get", "GET", response_model=list[SupplierRead], tags=["Suppliers"]),
        RouteDefinition("/api/v1/suppliers", "post", "POST", response_model=SupplierRead,
                        status_code=status.HTTP_201_CREATED, tags=["Suppliers"]),
    ]

    @staticmethod
    def get(db: Session = Depends(get_db)) -> list[Supplier]:
        return list(db.scalars(select(Supplier).where(~Supplier.id.in_(select(SyncIdentity.local_id).where(SyncIdentity.entity=='suppliers',SyncIdentity.deleted==True))).order_by(Supplier.name)))

    @staticmethod
    def post(payload: SupplierCreate, db: Session = Depends(get_db)) -> Supplier:
        supplier = Supplier(**payload.model_dump())
        db.add(supplier)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="A supplier with this name already exists")
        db.refresh(supplier)
        return supplier

    @staticmethod
    def put(supplier_id: int, payload: SupplierCreate, db: Session = Depends(get_db)):
        from app.api.common import get_or_404
        supplier = get_or_404(db, Supplier, supplier_id, 'Supplier')
        for key, value in payload.model_dump().items(): setattr(supplier,key,value)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, 'A supplier with this name already exists')
        db.refresh(supplier)
        return supplier

    @staticmethod
    def delete(supplier_id: int, db: Session = Depends(get_db)):
        from app.api.common import get_or_404
        supplier = get_or_404(db, Supplier, supplier_id, 'Supplier')
        from app.models import Medicine
        if db.scalar(select(Medicine.id).where(Medicine.supplier_id==supplier_id)):
            raise HTTPException(409, 'This supplier is linked to medicines and cannot be deleted')
        try:
            db.delete(supplier)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, 'This supplier is linked to medicines and cannot be deleted')
