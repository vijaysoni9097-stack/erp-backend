"""Pharmacy invoice identity stored per installation database."""
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class BillingSettings(Base):
    __tablename__ = 'billing_settings'
    id: Mapped[int] = mapped_column(primary_key=True)
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
