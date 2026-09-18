"""Small class-based routing layer used by every feature API."""

from dataclasses import dataclass, field
from typing import Any, ClassVar

from fastapi import FastAPI


@dataclass(frozen=True)
class RouteDefinition:
    """Metadata that connects one HTTP method to an API class method."""

    path: str
    handler_name: str
    method: str
    response_model: Any | None = None
    status_code: int | None = None
    summary: str | None = None
    tags: list[str] = field(default_factory=list)


class BaseAPI:
    """Base class for a feature API with explicit route registration."""

    methods: ClassVar[list[str]] = []
    routes: ClassVar[list[RouteDefinition]] = []

    @classmethod
    def register(cls, app: FastAPI) -> None:
        for route in cls.routes:
            if route.method not in cls.methods:
                raise ValueError(f"{cls.__name__} does not declare {route.method} in methods")
            app.add_api_route(
                route.path,
                getattr(cls, route.handler_name),
                methods=[route.method],
                response_model=route.response_model,
                status_code=route.status_code,
                summary=route.summary,
                tags=route.tags,
            )
