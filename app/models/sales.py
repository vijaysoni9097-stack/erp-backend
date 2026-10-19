"""Pharmacy sale and sale-item database models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SaleStatus(str, Enum):
    completed = "completed"
    voided = "voided"


class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    prescription_id: Mapped[int | None] = mapped_column(ForeignKey("prescriptions.id"))
    status: Mapped[SaleStatus] = mapped_column(SqlEnum(SaleStatus), default=SaleStatus.completed)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())
    customer: Mapped["Customer | None"] = relationship(back_populates="sales")
    prescription: Mapped["Prescription | None"] = relationship(back_populates="sales")
    payment: Mapped["SalePayment | None"] = relationship(uselist=False, cascade="all, delete-orphan")
    items: Mapped[list["SaleItem"]] = relationship(back_populates="sale", cascade="all, delete-orphan")


class SaleItem(Base):
    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"))
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id"))
    quantity: Mapped[int] = mapped_column()
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    sale: Mapped[Sale] = relationship(back_populates="items")
    medicine: Mapped["Medicine"] = relationship(back_populates="sale_items")


class CheckoutReceipt(Base):
    """Local request receipt: retrying checkout must not dispense twice."""
    __tablename__ = 'checkout_receipts'
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[int] = mapped_column()
    payload_hash: Mapped[str] = mapped_column(String(64))
    sale_id: Mapped[int] = mapped_column(ForeignKey('sales.id'))


class SalePayment(Base):
    __tablename__ = 'sale_payments'
    sale_id: Mapped[int] = mapped_column(ForeignKey('sales.id'), primary_key=True)
    method: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    tendered: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    change: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    reference: Mapped[str | None] = mapped_column(String(100))
