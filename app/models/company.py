"""Company registration and immutable invoice identity snapshots."""
from sqlalchemy import String, Text, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from decimal import Decimal
from app.database import Base

class CompanyRegistration(Base):
    __tablename__ = 'company_registration'
    id: Mapped[int] = mapped_column(primary_key=True)
    company_name: Mapped[str | None] = mapped_column(String(150))
    address: Mapped[str | None] = mapped_column(Text)
    gstin: Mapped[str | None] = mapped_column(String(15))

class SaleCompany(Base):
    __tablename__ = 'sale_company_snapshots'
    sale_id: Mapped[int] = mapped_column(ForeignKey('sales.id'), primary_key=True)
    company_name: Mapped[str | None] = mapped_column(String(150))
    address: Mapped[str | None] = mapped_column(Text)
    gstin: Mapped[str | None] = mapped_column(String(15))

class SaleLineDiscount(Base):
    __tablename__ = 'sale_line_discounts'
    sale_item_id: Mapped[int] = mapped_column(ForeignKey('sale_items.id'), primary_key=True)
    original_unit_price: Mapped[Decimal] = mapped_column(Numeric(12,2))
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5,2))
