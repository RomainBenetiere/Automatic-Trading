# Market Analysis & Investment Recommendation System

An automated system for portfolio analysis and crypto trading.

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env with your API keys

# 2. Run with Docker
docker compose up -d

# 3. Access
# Dashboard: http://localhost:3000
# API docs:  http://localhost:8000/docs
```

## Development

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

## Architecture

See `implementation_plan.md` for full details.

## License

Private — All rights reserved.
