from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.base import BaseAPI, RouteDefinition
from app.database import get_db
from app.models import Medicine, Sale, SaleStatus
from app.schemas import DashboardRead


class DashboardAPI(BaseAPI):
    methods = ["GET"]
    routes = [RouteDefinition("/api/v1/dashboard", "get", "GET", response_model=DashboardRead, tags=["Dashboard"])]

    @staticmethod
    def get(db: Session = Depends(get_db)) -> DashboardRead:
        today_start = datetime.combine(date.today(), time.min)
        today_end = today_start + timedelta(days=1)
        return DashboardRead(
            total_medicines=db.scalar(select(func.count(Medicine.id))) or 0,
            low_stock_medicines=db.scalar(select(func.count(Medicine.id)).where(Medicine.stock_quantity <= Medicine.reorder_level)) or 0,
            expiring_within_30_days=db.scalar(select(func.count(Medicine.id)).where(
                Medicine.expiry_date.between(date.today(), date.today() + timedelta(days=30)))) or 0,
            today_sales_total=db.scalar(select(func.coalesce(func.sum(Sale.total_amount), 0)).where(
                Sale.status == SaleStatus.completed, Sale.created_at >= today_start, Sale.created_at < today_end)) or Decimal("0"),
        )
