# EnduranceLife API

A RESTful API for managing endurance-sport training data, daily nutrition/recovery metrics, and physiological trend tracking. Built with **Python**, **FastAPI**, **SQLAlchemy** (SQLite), and **Pydantic V2**.

## Project Structure

```
EnduranceLife/
├── requirements.txt             # Python dependencies
├── README.md                    # This file
├── app/                         # Core API package
│   ├── __init__.py
│   ├── main.py                  # App entry point — init & router registration
│   ├── database.py              # SQLAlchemy engine & session config
│   ├── models.py                # ORM table definitions
│   ├── schemas.py               # Pydantic request/response models
│   └── routers/
│       ├── __init__.py
│       ├── activity.py          # CRUD for workout activities
│       ├── daily_metric.py      # CRUD for daily nutrition & recovery
│       ├── physiology.py        # CRUD for physiological snapshots
│       └── analytics.py         # Dashboard-facing analytics endpoints
├── scripts/                     # Standalone data-pipeline scripts
│   ├── __init__.py
│   ├── import_fit.py            # Parse Coros .fit files → Activity table
│   ├── enrich_weather.py        # Backfill weather data via Open-Meteo API
│   ├── seed_daily_metrics.py    # Generate simulated DailyMetric records
│   └── seed_physiology.py       # Generate trending PhysiologyLog records
└── data/
    └── coros/                   # Drop .fit files here for import
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
| `physiology_logs`| Body-state snapshots for trend charts      | Unique `(pid, date)` composite index  |

## Data Pipeline Scripts

The `scripts/` directory contains standalone Python modules for populating and enriching the database. All scripts are run as modules from the project root.

### 1. Import .fit Files

Parses Coros-exported `.fit` files using `fitdecode` and inserts them into the `Activity` table. Handles non-standard Coros field sizing, converts units (m→km, s→min, semicircles→degrees), and extracts HR/pace time-series as JSON arrays. Duplicate files are skipped via the `source_file` unique constraint.

```bash
python -m scripts.import_fit                    # default: pid=1, data/coros/
python -m scripts.import_fit --pid 2 --dir data/other_watch/
```

### 2. Enrich Weather Data

Backfills `temperature`, `humidity`, and `air_pressure` for Activity records using the [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api). Queries activities that have GPS coordinates but no weather data (idempotent). Matches the hourly weather slot to the activity's `start_time`.

```bash
python -m scripts.enrich_weather                    # default: 500 records, 0.01s delay
python -m scripts.enrich_weather --batch-size 100   # limit batch size
python -m scripts.enrich_weather --delay 0.5        # slower for rate-limit safety
```

### 3. Seed Daily Metrics (Simulated)

Generates realistic mock `DailyMetric` records for every distinct activity date. Values (sleep, fatigue, calories, recovery, etc.) are correlated with that day's training volume — harder days produce higher fatigue, more calories, and lower recovery.

```bash
python -m scripts.seed_daily_metrics            # all users
python -m scripts.seed_daily_metrics --pid 1    # specific user
```

### 4. Seed Physiology Logs (Simulated)

Generates bi-weekly `PhysiologyLog` snapshots from the user's first activity date to today with cumulative fitness progression: VO2Max gradually rises, resting HR drops, weight trends down, and threshold HR/pace zones are recalculated at each snapshot.

```bash
python -m scripts.seed_physiology               # default: pid=1
python -m scripts.seed_physiology --pid 2
```

## API Endpoints

### CRUD — Activities (`/activities`)
- `POST /activities/` — Create via JSON body (409 on duplicate `source_file`)
- `POST /activities/upload` — **Upload a .fit file** directly (Swagger UI file picker); parses via `fitdecode` and stores the raw file in the database (`fit_file_blob`)
- `GET /activities/` — List (filter by `pid`, `type`, `date_from`, `date_to`; paginate with `skip`, `limit`). Response includes `has_fit_file` flag
- `GET /activities/{id}` — Get one
- `GET /activities/{id}/download` — **Download the original .fit file** (returns binary with `Content-Disposition: attachment`)
- `PUT /activities/{id}` — Partial update
- `DELETE /activities/{id}` — Delete

### CRUD — Daily Metrics (`/daily-metrics`)
- `POST /daily-metrics/` — Create (409 on duplicate `pid` + `date`)
- `GET /daily-metrics/` — List (filter by `pid`, `date_from`, `date_to`)
- `GET /daily-metrics/{id}` — Get one
- `PUT /daily-metrics/{id}` — Partial update by ID
- `PUT /daily-metrics/by-date` — Partial update by `pid` + `date` (no need to know the row ID)
- `DELETE /daily-metrics/{id}` — Delete

### CRUD — Physiology Logs (`/physiology`)
- `POST /physiology/` — Create
- `GET /physiology/` — List (filter by `pid`)
- `GET /physiology/{id}` — Get one
- `PUT /physiology/{id}` — Partial update
- `DELETE /physiology/{id}` — Delete

### Analytics — Dashboard Endpoints (`/analytics`)

Chart-ready, strongly-typed endpoints designed for direct consumption by front-end dashboards (Vue/React + ECharts/Chart.js). Each endpoint returns a full Pydantic response model for clean Swagger documentation and TypeScript code-gen.

| Endpoint | Purpose | Key Output |
|---|---|---|
| `GET /analytics/physiology/trends` | Line chart data + current status | VO2Max / RHR / fitness trends, threshold zones, race time predictions (5K/10K/HM) |
| `GET /analytics/performance/records` | PR trophy display | Longest run, longest ride, fastest pace (runs ≥ 3km) |
| `GET /analytics/training/status` | Calendar + bar/pie charts | Per-day load/distance, period totals, intensity distribution (Easy/Tempo/Hard) |
| `GET /analytics/insights/environment` | Temperature impact analysis | Avg HR & pace across Cold (<10°C) / Moderate (10–22°C) / Hot (>22°C) |
| `GET /analytics/insights/lifestyle` | Sleep & fatigue correlation | A/B comparison of performance with good vs poor sleep, high vs low fatigue |
