"""Medicine inventory and stock-ledger database models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import Date, DateTime, Enum as SqlEnum, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class StockMovementType(str, Enum):
    received = "received"
    adjustment = "adjustment"
    sale = "sale"


class Medicine(Base):
    __tablename__ = "medicines"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), index=True)
    generic_name: Mapped[str | None] = mapped_column(String(150), index=True)
    sku: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    batch_number: Mapped[str] = mapped_column(String(80), index=True)
    expiry_date: Mapped[date] = mapped_column(Date(), index=True)
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    selling_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    stock_quantity: Mapped[int] = mapped_column(default=0)
    reorder_level: Mapped[int] = mapped_column(default=10)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())
    supplier: Mapped["Supplier | None"] = relationship(back_populates="medicines")
    sale_items: Mapped[list["SaleItem"]] = relationship(back_populates="medicine")
    stock_movements: Mapped[list["StockMovement"]] = relationship(back_populates="medicine")


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id"), index=True)
    movement_type: Mapped[StockMovementType] = mapped_column(SqlEnum(StockMovementType))
    quantity_change: Mapped[int] = mapped_column()
    note: Mapped[str | None] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())
    medicine: Mapped[Medicine] = relationship(back_populates="stock_movements")
