from fastapi import Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.base import BaseAPI, RouteDefinition
from app.api.common import get_or_404
from app.database import get_db
from app.models import Customer, Prescription, PrescriptionStatus
from app.schemas import PrescriptionCreate, PrescriptionRead


class PrescriptionAPI(BaseAPI):
    methods = ["GET", "POST"]
    routes = [
        RouteDefinition("/api/v1/prescriptions", "get", "GET", response_model=list[PrescriptionRead],
                        tags=["Prescriptions"]),
        RouteDefinition("/api/v1/prescriptions", "post", "POST", response_model=PrescriptionRead,
                        status_code=status.HTTP_201_CREATED, tags=["Prescriptions"]),
    ]

    @staticmethod
    def get(status_filter: PrescriptionStatus | None = Query(default=None, alias="status"),
            db: Session = Depends(get_db)) -> list[Prescription]:
        statement = select(Prescription).order_by(Prescription.prescribed_on.desc())
        if status_filter:
            statement = statement.where(Prescription.status == status_filter)
        return list(db.scalars(statement))

    @staticmethod
    def post(payload: PrescriptionCreate, db: Session = Depends(get_db)) -> Prescription:
        get_or_404(db, Customer, payload.customer_id, "Customer")
        prescription = Prescription(**payload.model_dump())
        db.add(prescription)
        db.commit()
        db.refresh(prescription)
        return prescription
