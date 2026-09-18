from app.api.base import BaseAPI, RouteDefinition
from app.config import get_settings


class HealthAPI(BaseAPI):
    methods = ["GET"]
    routes = [RouteDefinition("/health", "get", "GET", summary="Application health check", tags=["Health"])]

    @staticmethod
    def get() -> dict[str, str]:
        settings = get_settings()
        return {"status": "ok", "database": settings.database_url}
