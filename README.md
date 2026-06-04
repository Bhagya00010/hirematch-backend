# HireMatch Backend

FastAPI backend for HireMatch AI. The project currently includes the application entrypoint, environment-based configuration, SQLAlchemy database setup, and Alembic migration wiring.

## Tech Stack

- Python
- FastAPI
- Uvicorn
- SQLAlchemy
- Alembic
- PostgreSQL
- Pydantic Settings

## Project Structure

```text
app/
  core/
    config.py       # Environment configuration
    security.py     # Security helpers
  db/
    base.py         # SQLAlchemy declarative base
    database.py     # Engine and session factory
    session.py      # FastAPI DB dependency
  models/
    user.py         # User model placeholder
  main.py           # FastAPI app
alembic/
  env.py            # Alembic environment config
  script.py.mako    # Migration template
requirements.txt
.env.example
```

## Prerequisites

- Python 3.10 or newer
- PostgreSQL
- Redis, if you add Celery background workers

## Setup

Create and activate a virtual environment:

```bash
python -m venv venv
```

On Windows PowerShell:

```bash
.\venv\Scripts\Activate.ps1
```

On macOS or Linux:

```bash
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a local environment file:

```bash
cp .env.example .env
```

On Windows PowerShell, if `cp` is unavailable:

```powershell
Copy-Item .env.example .env
```

Update `.env` with your local values:

```env
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/hirematch
SECRET_KEY=your-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

Create the PostgreSQL database if it does not already exist:

```sql
CREATE DATABASE hirematch;
```

## Run the App

Start the development server:

```bash
uvicorn app.main:app --reload
```

Open:

- API root: `http://127.0.0.1:8000/`
- Swagger docs: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

The health endpoint should return:

```json
{
  "status": "running",
  "service": "HireMatch AI"
}
```

## Database Migrations

Alembic is configured to read `DATABASE_URL` from `.env`.

Create a new migration after adding or changing SQLAlchemy models:

```bash
alembic revision --autogenerate -m "describe changes"
```

Apply migrations:

```bash
alembic upgrade head
```

Roll back the latest migration:

```bash
alembic downgrade -1
```

## Tests

Run tests with:

```bash
pytest
```

## Notes

- Keep `.env` private. Use `.env.example` for shared configuration keys.
- Import new SQLAlchemy models in `app/db/base.py` so Alembic can detect them during autogeneration.
- `app/core/security.py` and `app/models/user.py` are currently placeholders.
