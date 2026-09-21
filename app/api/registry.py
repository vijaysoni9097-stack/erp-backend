"""The sole location where feature APIs are registered with FastAPI."""

from fastapi import FastAPI

from app.api.auth.auth import AuthAPI
from app.api.base import BaseAPI
from app.api.customers.customers import CustomerAPI
from app.api.dashboard.dashboard import DashboardAPI
from app.api.health.health import HealthAPI
from app.api.medicines.medicines import MedicineAPI
from app.api.prescriptions.prescriptions import PrescriptionAPI
from app.api.sales.sales import SaleAPI
from app.api.settings.settings import SettingsAPI
from app.api.suppliers.suppliers import SupplierAPI

API_CLASSES: tuple[type[BaseAPI], ...] = (
    HealthAPI,
    DashboardAPI,
    AuthAPI,
    SupplierAPI,
    MedicineAPI,
    CustomerAPI,
    PrescriptionAPI,
    SaleAPI,
    SettingsAPI,
)


def register_apis(app: FastAPI) -> None:
    """Register every feature class once during application bootstrap."""
    if getattr(app.state, "apis_registered", False):
        return
    for api_class in API_CLASSES:
        api_class.register(app)
    app.state.apis_registered = True
