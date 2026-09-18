"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.registry import register_apis
from app.config import get_settings
from app.lifecycle import lifespan


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    register_apis(app)
    return app


app = create_app()
