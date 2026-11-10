"""Every HTTP and WebSocket route the core app serves, including lazily included routers.

Route matrices use this so a route added anywhere in the app is discovered by the tests.
"""

from __future__ import annotations

from typing import Any

from fastapi.routing import _IncludedRouter


def registered_routes(app: Any) -> list[Any]:
    """Expand included routers using the same candidate graph used by the ASGI router."""
    pending = list(app.router.routes)
    routes: list[Any] = []
    while pending:
        route = pending.pop()
        if isinstance(route, _IncludedRouter):
            pending.extend(route.effective_candidates())
        else:
            routes.append(route)
    return routes


def base_route(route: Any) -> Any:
    return getattr(route, "original_route", route)


def effective_path(route: Any) -> str:
    starlette_route = getattr(route, "starlette_route", None)
    return getattr(starlette_route, "path", getattr(route, "path", ""))
