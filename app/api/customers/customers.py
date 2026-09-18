from fastapi import Depends, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.base import BaseAPI, RouteDefinition
from app.database import get_db
from app.models import Customer
from app.schemas import CustomerCreate, CustomerRead


class CustomerAPI(BaseAPI):
    methods = ["GET", "POST"]
    routes = [
        RouteDefinition("/api/v1/customers", "get", "GET", response_model=list[CustomerRead], tags=["Customers"]),
        RouteDefinition("/api/v1/customers", "post", "POST", response_model=CustomerRead,
                        status_code=status.HTTP_201_CREATED, tags=["Customers"]),
    ]

    @staticmethod
    def get(search: str | None = None, db: Session = Depends(get_db)) -> list[Customer]:
        statement = select(Customer).order_by(Customer.full_name)
        if search:
            term = f"%{search.strip()}%"
            statement = statement.where(or_(Customer.full_name.ilike(term), Customer.phone.ilike(term)))
        return list(db.scalars(statement))

    @staticmethod
    def post(payload: CustomerCreate, db: Session = Depends(get_db)) -> Customer:
        customer = Customer(**payload.model_dump())
        db.add(customer)
        db.commit()
        db.refresh(customer)
        return customer
