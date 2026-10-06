.PHONY: dev dev-backend dev-frontend build docker-up docker-down migrate test

# ── Development ─────────────────────────────────────────────────
dev-backend:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

dev:
	@echo "Run these in separate terminals:"
	@echo "  make dev-backend"
	@echo "  make dev-frontend"

# ── Database ────────────────────────────────────────────────────
migrate:
	cd backend && alembic upgrade head

migrate-new:
	cd backend && alembic revision --autogenerate -m "$(MSG)"

# ── Docker ──────────────────────────────────────────────────────
docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

# ── Testing ─────────────────────────────────────────────────────
test:
	cd backend && python -m pytest tests/ -v

# ── Setup ───────────────────────────────────────────────────────
setup:
	cp -n .env.example .env || true
	cd backend && pip install -r requirements.txt
	cd frontend && npm install
	@echo "✓ Setup complete — edit .env with your API keys"
