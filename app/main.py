"""
main.py — Application entry point.

Responsibilities:
1. Create all database tables on startup (via `Base.metadata.create_all`).
   In production you would use Alembic migrations instead.
2. Register each domain-specific router with the FastAPI application.
3. Expose a health-check root endpoint for quick connectivity tests.

Run with:
    uvicorn app.main:app --reload
"""

from fastapi import FastAPI

from .database import engine, Base
from .routers import activity, daily_metric, physiology, analytics

# ---------------------------------------------------------------------------
# Create tables — idempotent; safe to call on every startup.
# In production, replace with Alembic migrations for schema versioning.
# ---------------------------------------------------------------------------
Base.metadata.create_all(bind=engine)

# ---------------------------------------------------------------------------
# FastAPI application instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title="EnduranceLife API",
    description=(
        "RESTful API for managing endurance-sport training data parsed from "
        ".fit files (Coros, Garmin, etc.), daily nutrition/recovery metrics, "
        "and physiological trend tracking."
    ),
    version="0.1.0",
    # Override ReDoc JS source — the default cdn.jsdelivr.net path is
    # unreliable in some network environments (e.g. mainland China).
    redoc_url=None,  # Disable built-in, we'll serve a custom one below
)

# ---------------------------------------------------------------------------
# Register routers — each file under routers/ owns its own prefix and tags.
# ---------------------------------------------------------------------------
app.include_router(activity.router)
app.include_router(daily_metric.router)
app.include_router(physiology.router)
app.include_router(analytics.router)

# ---------------------------------------------------------------------------
# Health-check endpoint
# ---------------------------------------------------------------------------
@app.get("/", tags=["Health"])
def health_check():
    """Simple health-check endpoint to verify the API is running."""
    return {"status": "ok", "service": "EnduranceLife API"}


# ---------------------------------------------------------------------------
# Custom ReDoc page — loads JS from unpkg.com instead of cdn.jsdelivr.net
# which is unreliable in certain network environments.
# ---------------------------------------------------------------------------
from fastapi.responses import HTMLResponse  # noqa: E402


@app.get("/redoc", include_in_schema=False)
def custom_redoc():
    return HTMLResponse(
        """
<!DOCTYPE html>
<html>
<head>
    <title>EnduranceLife API — ReDoc</title>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700"
          rel="stylesheet">
    <style>body { margin: 0; padding: 0; }</style>
</head>
<body>
    <redoc spec-url="/openapi.json"></redoc>
    <script src="https://unpkg.com/redoc@2.1.5/bundles/redoc.standalone.js"></script>
</body>
</html>
        """
    )
