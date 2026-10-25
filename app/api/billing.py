from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator
import re
from sqlalchemy.orm import Session
from app.api.base import BaseAPI, RouteDefinition
from app.database import get_db
from app.models.billing import BillingSettings
from app.models.company import CompanyRegistration
from pydantic import Field
from app.services.auth import get_current_profile

class BillingRead(BaseModel):
    model_config = ConfigDict(extra='forbid')
    gstin: str | None = None

    @field_validator('gstin')
    @classmethod
    def gstin_format(cls, value):
        value = (value or '').strip().upper()
        if value and not re.fullmatch(r'[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]', value):
            raise ValueError('Enter a 15-character GSTIN in the correct format')
        return value or None

class CompanyRead(BillingRead):
    company_name: str | None = Field(default=None, max_length=150)
    address: str | None = Field(default=None, max_length=1000)

class CompanyState(CompanyRead):
    registered: bool = False

class CompanyWrite(CompanyRead):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    company_name: str = Field(min_length=1, max_length=150)


def company_for_update(db, profile):
    if profile.role not in ('admin','superadmin'):
        raise HTTPException(403,'Administrator access required to register the company')
    if db.bind.dialect.name == 'sqlite':
        from sqlalchemy import text
        db.rollback();db.execute(text('BEGIN IMMEDIATE'))
    else:
        from app.database import lock_inventory
        lock_inventory(db)
    row=db.get(CompanyRegistration,1)
    if row and row.company_name and profile.role != 'superadmin':
        raise HTTPException(403,'Company registration is already saved. Only a superadmin can edit or update it.')
    return row

class BillingAPI(BaseAPI):
    methods = ['GET','PUT']
    routes = [RouteDefinition('/api/v1/settings/company', 'get_company', 'GET', response_model=CompanyState, tags=['Settings']),
              RouteDefinition('/api/v1/settings/company', 'put_company', 'PUT', response_model=CompanyRead, tags=['Settings']),
              RouteDefinition('/api/v1/settings/billing', 'get', 'GET', response_model=BillingRead, tags=['Settings']),
              RouteDefinition('/api/v1/settings/billing', 'put', 'PUT', response_model=BillingRead, tags=['Settings'])]

    @staticmethod
    def get(profile=Depends(get_current_profile), db: Session=Depends(get_db)):
        row = db.get(CompanyRegistration,1) or db.get(BillingSettings,1)
        return {'gstin': row.gstin if row else None}

    @staticmethod
    def put(payload: BillingRead, profile=Depends(get_current_profile), db: Session=Depends(get_db)):
        row = company_for_update(db,profile)
        if row is None:
            row=CompanyRegistration(id=1);db.add(row)
        row.gstin=payload.gstin
        db.commit()
        return payload

    @staticmethod
    def get_company(profile=Depends(get_current_profile), db: Session=Depends(get_db)):
        row = db.get(CompanyRegistration,1)
        if row:
            return {'company_name':row.company_name,'address':row.address,'gstin':row.gstin,'registered':bool(row.company_name)}
        legacy=db.get(BillingSettings,1)
        return {'company_name':None,'address':None,'gstin':legacy.gstin if legacy else None}

    @staticmethod
    def put_company(payload: CompanyWrite, profile=Depends(get_current_profile), db: Session=Depends(get_db)):
        row=company_for_update(db,profile)
        if row is None:
            row=CompanyRegistration(id=1);db.add(row)
        for key,value in payload.model_dump().items(): setattr(row,key,value.strip() or None if isinstance(value,str) else value)
        db.commit()
        return payload
