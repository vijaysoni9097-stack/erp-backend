from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class PurchaseItemCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    medicine_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=2147483647, strict=True)
    unit_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class PurchaseOrderCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    request_id: UUID
    supplier_id: int = Field(gt=0)
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    expected_delivery: date | None = None
    notes: str | None = Field(default=None, max_length=1000)
    items: list[PurchaseItemCreate] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_items(self):
        if len({item.medicine_id for item in self.items}) != len(self.items):
            raise ValueError('Each medicine must appear only once')
        return self


class PurchaseItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    medicine_id: int
    medicine_name: str
    sku: str
    batch_number: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class PurchaseOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    request_id: str
    created_by: int
    supplier_id: int
    supplier_name: str
    currency: str
    status: str
    expected_delivery: date | None
    notes: str | None
    total_amount: Decimal
    created_at: datetime
    items: list[PurchaseItemRead]
