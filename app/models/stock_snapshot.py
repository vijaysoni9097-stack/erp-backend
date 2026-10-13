"""Imported reference stock, kept separate from saleable allocations."""
from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class StockSnapshot(Base):
    __tablename__ = 'surya_stock_snapshot'
    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    quantity: Mapped[int | None] = mapped_column(Integer)
    source_modified_on: Mapped[str | None] = mapped_column(Text)
    imported_at: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(Text)
