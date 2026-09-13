# Solar Energy Report Web App

A complete, production-ready full-stack web application that allows users to input solar project parameters, runs real energy calculations based on industry standards, and generates a dynamic PDF report matching the Side Hustler Solar Proposal templates.

## Architecture

- **Backend:** FastAPI, Python, SQLAlchemy ORM, Alembic
- **Frontend:** HTML, CSS, JavaScript (Vanilla SPA structure), Chart.js
- **Database:** SQLite (local development), PostgreSQL (Production/Render)
- **PDF Generation:** ReportLab
- **Testing:** Pytest

## Features

- Dynamic calculation engine separated from business logic and independently tested
- Modern UI closely mirroring the reference designs
- Single Page Application (SPA) architecture
- REST API
- PDF dynamic generation tying directly to the calculated database results

## Local Setup

### 1. Create and Activate Virtual Environment
```bash
python -m venv .venv
# Activate (Windows)
.venv\Scripts\activate
# Activate (Mac/Linux)
source .venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
(Uses SQLite by default)

### 4. Database Setup
```bash
# Initialize the database with Alembic
alembic upgrade head
```

### 5. Run the Application
```bash
# Start FastAPI backend
uvicorn app.main:app --reload
```
Open `http://localhost:8000` in your browser.

On Windows, you can also double-click `start.bat` to start the server and
`stop.bat` to stop the process listening on port 8000.

### 6. Run Tests
```bash
pytest tests/ -v
```

## Production Deployment (Render)

This project includes a `render.yaml` for automatic deployment to Render.
It specifies:
- A PostgreSQL Database
- A Docker-based Web Service

To deploy:
1. Push to GitHub
2. Connect your repo in Render's dashboard using a Blueprint
3. Render will provision the PostgreSQL database and build the Docker container automatically.
