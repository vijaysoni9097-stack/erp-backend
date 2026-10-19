"""Persistent purchasing documents; creating an order never changes stock."""
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class PurchaseOrder(Base):
    __tablename__ = 'purchase_orders'
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[int] = mapped_column(Integer())
    supplier_id: Mapped[int] = mapped_column(ForeignKey('suppliers.id'))
    supplier_name: Mapped[str] = mapped_column(String(150))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(30), default='pending_approval', index=True)
    expected_delivery: Mapped[date | None] = mapped_column(Date())
    notes: Mapped[str | None] = mapped_column(Text())
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now(), index=True)
    items: Mapped[list['PurchaseOrderItem']] = relationship(cascade='all, delete-orphan', order_by='PurchaseOrderItem.id')


class PurchaseOrderItem(Base):
    __tablename__ = 'purchase_order_items'
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('purchase_orders.id', ondelete='CASCADE'), index=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey('medicines.id'))
    medicine_name: Mapped[str] = mapped_column(String(150))
    sku: Mapped[str] = mapped_column(String(50))
    batch_number: Mapped[str] = mapped_column(String(80))
    quantity: Mapped[int] = mapped_column(Integer())
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class PurchaseReceipt(Base):
    __tablename__ = 'purchase_receipts'
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[int] = mapped_column(ForeignKey('purchase_orders.id'), index=True)
    created_by: Mapped[int] = mapped_column(Integer())
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())
    items: Mapped[list['PurchaseReceiptItem']] = relationship(cascade='all, delete-orphan')


class PurchaseReceiptItem(Base):
    __tablename__ = 'purchase_receipt_items'
    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey('purchase_receipts.id'))
    order_item_id: Mapped[int] = mapped_column(ForeignKey('purchase_order_items.id'), index=True)
    quantity: Mapped[int] = mapped_column(Integer())
