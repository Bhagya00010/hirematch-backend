# HireMatch AI Backend

Backend service for **HireMatch AI**, an AI-powered recruitment platform that helps organizations streamline their hiring process through AI-powered resume parsing, candidate matching, and recruitment workflow automation.

---

# Tech Stack

- Python 3.12+
- FastAPI
- Uvicorn
- SQLAlchemy
- Alembic
- PostgreSQL
- Pydantic Settings

---

# Project Structure

```text
hirematch-backend/
│
├── app/
│   ├── api/
│   ├── core/
│   │   ├── config.py
│   │   └── security.py
│   │
│   ├── db/
│   │   ├── base.py
│   │   ├── database.py
│   │   └── session.py
│   │
│   ├── models/
│   ├── schemas/
│   ├── services/
│   ├── utils/
│   └── main.py
│
├── alembic/
│
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

# Prerequisites

Before starting, make sure the following software is installed:

- Python 3.12+
- PostgreSQL
- Git

Optional:

- Redis (for future background jobs)
- Docker Desktop

---

# Clone Repository

```bash
git clone <repository-url>

cd hirematch-backend
```

---

# Create Virtual Environment

## Windows

```powershell
python -m venv venv

.\venv\Scripts\activate
```

## Linux / macOS

```bash
python3 -m venv venv

source venv/bin/activate
```

---

# Install Dependencies

```bash
pip install -r requirements.txt
```

---

# Environment Configuration

Create a local environment file.

### Windows

```powershell
Copy-Item .env.example .env
```

### Linux / macOS

```bash
cp .env.example .env
```

Update the `.env` file with your local configuration:

```env
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/hirematch

SECRET_KEY=your-secret-key

ALGORITHM=HS256

ACCESS_TOKEN_EXPIRE_MINUTES=60

REFRESH_TOKEN_EXPIRE_DAYS=7

PASSWORD_RESET_TOKEN_EXPIRE_MINUTES=30

PASSWORD_RESET_URL=http://localhost:3000/reset-password

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587

SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password

SMTP_FROM_EMAIL=your-email@gmail.com
SMTP_FROM_NAME=HireMatch AI

SMTP_USE_TLS=true
```

> **Note:** For Gmail SMTP, use a Google App Password instead of your normal Gmail password.

---

# PostgreSQL Setup

Create the database if it does not already exist.

```sql
CREATE DATABASE hirematch;
```

Enable UUID generation support:

```sql
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
```

---

# Database Migrations

This project uses **Alembic** for database version control.

## Apply Existing Migrations

If you are setting up the project for the first time:

```bash
alembic upgrade head
```

---

## Create a New Migration

Whenever you add or modify SQLAlchemy models:

```bash
alembic revision --autogenerate -m "describe your changes"
```

Example:

```bash
alembic revision --autogenerate -m "create users table"
```

---

## Apply New Migration

```bash
alembic upgrade head
```

---

## Rollback Last Migration

```bash
alembic downgrade -1
```

---

## Check Current Migration Version

```bash
alembic current
```

---

## Migration Workflow

```text
Modify SQLAlchemy Models
          │
          ▼
alembic revision --autogenerate -m "migration message"
          │
          ▼
Review Migration File
          │
          ▼
alembic upgrade head
```

---

# Run Application

Start the development server:

```bash
uvicorn app.main:app --reload
```

Server URL:

```
http://127.0.0.1:8000
```

Swagger Documentation:

```
http://127.0.0.1:8000/docs
```

ReDoc Documentation:

```
http://127.0.0.1:8000/redoc
```

---

# Health Check

Example response:

```json
{
  "status": "running",
  "service": "HireMatch AI"
}
```

---

# Running Tests

Run all tests:

```bash
pytest
```

Run with verbose output:

```bash
pytest -v
```

---

# Common Development Commands

## Install New Package

```bash
pip install package-name

pip freeze > requirements.txt
```

---

## Create Migration

```bash
alembic revision --autogenerate -m "migration name"
```

---

## Apply Migration

```bash
alembic upgrade head
```

---

## Rollback Migration

```bash
alembic downgrade -1
```

---

## Run Development Server

```bash
uvicorn app.main:app --reload
```

---

## Stop Server

```text
CTRL + C
```

---

# Development Guidelines

- Never commit `.env`
- Never commit `venv`
- Always review generated Alembic migrations before applying them
- Keep sensitive credentials outside the repository
- Import new SQLAlchemy models in `app/db/base.py` so Alembic can detect them

---

# Future Modules

- User Management
- Job Management
- Resume Upload
- Resume Parsing
- AI Candidate Matching
- LangChain Integration
- LangGraph Workflows
- ChromaDB Integration
- Background Workers
- Docker Deployment
- Kubernetes Deployment

---

# License

Internal Project — HireMatch AI
