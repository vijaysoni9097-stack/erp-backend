from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.base import BaseAPI, RouteDefinition
from app.database import get_db
from app.models import Supplier
from app.schemas import SupplierCreate, SupplierRead


class SupplierAPI(BaseAPI):
    methods = ["GET", "POST"]
    routes = [
        RouteDefinition("/api/v1/suppliers", "get", "GET", response_model=list[SupplierRead], tags=["Suppliers"]),
        RouteDefinition("/api/v1/suppliers", "post", "POST", response_model=SupplierRead,
                        status_code=status.HTTP_201_CREATED, tags=["Suppliers"]),
    ]

    @staticmethod
    def get(db: Session = Depends(get_db)) -> list[Supplier]:
        return list(db.scalars(select(Supplier).order_by(Supplier.name)))

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
