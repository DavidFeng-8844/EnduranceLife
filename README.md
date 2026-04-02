# EnduranceLife API

A RESTful API for managing endurance-sport training data, daily nutrition/recovery metrics, and physiological trend tracking. Built with **Python**, **FastAPI**, **SQLAlchemy** (SQLite), and **Pydantic V2**.

## Project Structure

```
EnduranceLife/
├── requirements.txt         # Python dependencies
├── README.md                # This file
├── app/
│   ├── __init__.py
│   ├── main.py              # App entry point — init & router registration
│   ├── database.py          # SQLAlchemy engine & session config
│   ├── models.py            # ORM table definitions
│   ├── schemas.py           # Pydantic request/response models
│   └── routers/
│       ├── __init__.py
│       ├── activity.py      # CRUD for workout activities
│       ├── daily_metric.py  # CRUD for daily nutrition & recovery
│       └── physiology.py    # CRUD for physiological snapshots
```

## Quick Start

```bash
# 1. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Linux / macOS
venv\Scripts\activate           # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the development server
uvicorn app.main:app --reload
```

The API will be available at **http://127.0.0.1:8000**.

## API Documentation

FastAPI auto-generates interactive API docs:

| Format  | URL                                      |
|---------|------------------------------------------|
| Swagger | http://127.0.0.1:8000/docs               |
| ReDoc   | http://127.0.0.1:8000/redoc              |

## Data Tables

| Table            | Purpose                                    | Key Constraint                        |
|------------------|--------------------------------------------|---------------------------------------|
| `activities`     | Workout records from .fit files            | Unique `source_file`                  |
| `daily_metrics`  | Daily nutrition, sleep & recovery logging  | Unique `(pid, date)` composite index  |
| `physiology_logs`| Body-state snapshots for trend charts      | —                                     |

## API Endpoints

### Activities (`/activities`)
- `POST /activities/` — Create (409 on duplicate `source_file`)
- `GET /activities/` — List (filter by `pid`, `type`; paginate with `skip`, `limit`)
- `GET /activities/{id}` — Get one
- `PUT /activities/{id}` — Partial update
- `DELETE /activities/{id}` — Delete

### Daily Metrics (`/daily-metrics`)
- `POST /daily-metrics/` — Create (409 on duplicate `pid` + `date`)
- `GET /daily-metrics/` — List (filter by `pid`, `date_from`, `date_to`)
- `GET /daily-metrics/{id}` — Get one
- `PUT /daily-metrics/{id}` — Partial update
- `DELETE /daily-metrics/{id}` — Delete

### Physiology Logs (`/physiology`)
- `POST /physiology/` — Create
- `GET /physiology/` — List (filter by `pid`)
- `GET /physiology/{id}` — Get one
- `PUT /physiology/{id}` — Partial update
- `DELETE /physiology/{id}` — Delete
