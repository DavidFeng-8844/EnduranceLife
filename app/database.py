"""
database.py — Database engine and session configuration.

Design choices:
- SQLite is used as the database backend for simplicity and portability.
  The DB file is stored at the project root as `endurance_life.db`.
- `check_same_thread=False` is required for SQLite when used with FastAPI,
  because FastAPI handles requests in multiple threads, while SQLite's
  default mode only allows access from the creating thread.
- A `sessionmaker` factory produces `Session` objects, and `get_db()` is a
  FastAPI dependency that yields a session per request, ensuring proper
  cleanup via `finally`.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# ---------------------------------------------------------------------------
# SQLite connection string — the DB file lives next to the project root.
# For production, swap this for PostgreSQL / MySQL via environment variables.
# ---------------------------------------------------------------------------
SQLALCHEMY_DATABASE_URL = "sqlite:///./endurance_life.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    # SQLite-specific: allow multi-threaded access
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
