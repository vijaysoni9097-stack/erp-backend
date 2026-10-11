from app.api.base import BaseAPI, RouteDefinition


class HealthAPI(BaseAPI):
    public = True
    methods = ["GET"]
    routes = [RouteDefinition("/health", "get", "GET", summary="Application health check", tags=["Health"])]

    @staticmethod
    def get() -> dict[str, str]:
        return {"status": "ok"}
