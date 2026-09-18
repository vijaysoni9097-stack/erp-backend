"""Application lifecycle hooks kept outside the HTTP entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import Base, SessionLocal, engine
from app.services.settings import seed_settings


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize the local database and default configuration during startup."""
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_settings(db)
    yield
