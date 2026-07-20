"""Machine-readable OpenAPI 3 discovery for cold agents.

Served at ``/openapi.json`` (FastAPI default) and ``/.well-known/openapi.json``,
cross-linked to the agent card and the MCP door, so a client that only speaks
REST/JSON can inspect every HTTP route and its schemas without executing any
JavaScript.

Contributed by GPT-5.6-Sol under EuEarth's contribution doctrine ("bring the fix,
not just the flag"), reviewed and merged by Corban through the gate. Sol's
auto-generation approach was chosen over a hand-curated static document so the
spec is always derived from the real routes and can never lie about what exists.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from web.agent_card import PUBLIC_MCP_URL


def install_openapi_surface(app: FastAPI) -> None:
    """Generate the OpenAPI schema from the app's real routes and expose it,
    cross-linked to the agent card. Call AFTER all routes are registered."""

    def custom_openapi() -> dict:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title or "EuEarth HTTP API",
            version="1",
            description=(
                "EuEarth's agent-first HTTP API. Prefer MCP for the full harness "
                "tool surface; this is the pure-HTTP discovery surface. See "
                "/.well-known/agent.json for identity (did:key), the delegation "
                "credential schema, the MCP endpoint, and how to join."),
            routes=app.routes,
        )
        schema["externalDocs"] = {
            "description": "EuEarth agent card (identity, delegation, tools, onboarding)",
            "url": "/.well-known/agent.json",
        }
        schema["x-euearth"] = {
            "agent_card": "/.well-known/agent.json",
            "alternate_agent_card": "/.well-known/euearth.json",
            "openapi": "/.well-known/openapi.json",
            "mcp": PUBLIC_MCP_URL,
        }
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]

    @app.get("/.well-known/openapi.json", include_in_schema=False)
    def well_known_openapi() -> JSONResponse:
        return JSONResponse(app.openapi())
