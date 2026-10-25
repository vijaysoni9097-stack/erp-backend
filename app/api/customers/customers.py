from pydantic import BaseModel, ConfigDict
from app.services.sync_queue import queue_if_enabled
from fastapi import Depends, status, Query, HTTPException
from app.services.auth import get_current_profile
from app.services.customer_mobile import customers_by_mobile, normalize_mobile
from app.models.sync import SyncIdentity
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.base import BaseAPI, RouteDefinition
from app.database import get_db
from app.models import Customer
from app.schemas import CustomerCreate, CustomerRead


class CustomerMobileMatch(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    phone: str | None

class CustomerAPI(BaseAPI):
    methods = ["GET", "POST"]
    routes = [
        RouteDefinition("/api/v1/customers/lookup", "lookup", "GET", response_model=list[CustomerMobileMatch], tags=["Customers"]),
        RouteDefinition("/api/v1/customers", "get", "GET", response_model=list[CustomerRead], tags=["Customers"]),
        RouteDefinition("/api/v1/customers", "post", "POST", response_model=CustomerRead,
                        status_code=status.HTTP_201_CREATED, tags=["Customers"]),
    ]

    @staticmethod
    def get(search: str | None = None, db: Session = Depends(get_db)) -> list[Customer]:
        statement = select(Customer).where(~Customer.id.in_(select(SyncIdentity.local_id).where(SyncIdentity.entity=='customers',SyncIdentity.deleted==True))).order_by(Customer.full_name)
        if search:
            term = f"%{search.strip()}%"
            statement = statement.where(or_(Customer.full_name.ilike(term), Customer.phone.ilike(term)))
        return list(db.scalars(statement))

    @staticmethod
    def post(payload: CustomerCreate, db: Session = Depends(get_db)) -> Customer:
        customer = Customer(**payload.model_dump())
        db.add(customer)
        queue_if_enabled(db, 'customers', customer)
        db.commit()
        db.refresh(customer)
        return customer

    @staticmethod
    def lookup(phone: str = Query(min_length=1,max_length=40), profile=Depends(get_current_profile), db:Session=Depends(get_db)):
        if profile.role not in ('pharmacist','admin','superadmin'):
            raise HTTPException(403,'Pharmacist or administrator access required')
        try:return customers_by_mobile(db,phone)
        except ValueError as error:raise HTTPException(422,str(error)) from None
