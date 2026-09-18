"""Prescription database model."""

from __future__ import annotations

from datetime import date
from enum import Enum

from sqlalchemy import Date, Enum as SqlEnum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PrescriptionStatus(str, Enum):
    pending = "pending"
    dispensed = "dispensed"
    cancelled = "cancelled"


class Prescription(Base):
    __tablename__ = "prescriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    doctor_name: Mapped[str] = mapped_column(String(150))
    prescribed_on: Mapped[date] = mapped_column(Date(), default=date.today)
    notes: Mapped[str | None] = mapped_column(Text())
    status: Mapped[PrescriptionStatus] = mapped_column(SqlEnum(PrescriptionStatus), default=PrescriptionStatus.pending)
    customer: Mapped["Customer"] = relationship(back_populates="prescriptions")
    sales: Mapped[list["Sale"]] = relationship(back_populates="prescription")
