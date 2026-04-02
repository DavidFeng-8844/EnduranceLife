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
from .routers import activity, daily_metric, physiology

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
)

# ---------------------------------------------------------------------------
# Register routers — each file under routers/ owns its own prefix and tags.
# ---------------------------------------------------------------------------
app.include_router(activity.router)
app.include_router(daily_metric.router)
app.include_router(physiology.router)


# ---------------------------------------------------------------------------
# Health-check endpoint
# ---------------------------------------------------------------------------
@app.get("/", tags=["Health"])
def health_check():
    """Simple health-check endpoint to verify the API is running."""
    return {"status": "ok", "service": "EnduranceLife API"}
