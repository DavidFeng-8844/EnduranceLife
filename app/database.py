"""
database.py — Database engine and session configuration.

Supports two backends via the DATABASE_URL environment variable:

  1. **PostgreSQL** (production / Render.com):
     Set DATABASE_URL to the Render Internal Database URL, e.g.
     postgresql://user:pass@host/dbname

  2. **SQLite** (local development):
     If DATABASE_URL is not set, defaults to a local file
     `endurance_life.db` in the project root.

Render.com note:
  Render provides PostgreSQL connection strings starting with `postgres://`
  (without the "ql"). SQLAlchemy 2.x requires the full `postgresql://`
  scheme, so we auto-correct this at startup.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base


# ---------------------------------------------------------------------------
# Determine the database URL from environment or default to SQLite
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    # Render.com uses `postgres://` but SQLAlchemy 2.x requires `postgresql://`
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    engine = create_engine(DATABASE_URL)
else:
    # Local development: SQLite with multi-thread support
    DATABASE_URL = "sqlite:///./endurance_life.db"
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
    )

# Each call to SessionLocal() returns a new database session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class that all ORM models inherit from
Base = declarative_base()


def get_db():
    """
    FastAPI dependency that provides a database session for each request.

    Usage in a route:
        @router.get("/items")
        def list_items(db: Session = Depends(get_db)):
            ...

    The `finally` block guarantees the session is closed even if an
    exception occurs, preventing connection leaks.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
