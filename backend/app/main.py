"""FastAPI application — entry point, lifespan, and router mounts."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.scheduler.jobs import (
    run_crypto_daily_job,
    run_crypto_stops_check_job,
    run_stocks_weekly_job,
    run_optimizer_weekly_job,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Lifespan — scheduler setup ──────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — starts scheduler on boot, shuts down gracefully."""
    # Initialise database tables
    await init_db()
    logger.info("Database initialised")

    # Initialise APScheduler
    scheduler = AsyncIOScheduler()

    # 4H crypto strategy job
    scheduler.add_job(
        run_crypto_daily_job,
        CronTrigger(
            hour=settings.crypto_strategy_cron_hours,
            minute=0,
        ),
        id="crypto_strategy_4h",
        name="Crypto Strategy & Execution (4H)",
        replace_existing=True,
    )

    # 15-minute crypto stop-loss and trailing-stop watcher
    scheduler.add_job(
        run_crypto_stops_check_job,
        CronTrigger(
            minute=settings.crypto_stops_check_cron_minutes,
        ),
        id="crypto_stops_watcher",
        name="Crypto Stop-Loss & Trailing-Stop Watcher (15m)",
        replace_existing=True,
    )

    # Weekly stocks/ETFs/bonds job
    scheduler.add_job(
        run_stocks_weekly_job,
        CronTrigger(
            day_of_week=settings.stocks_schedule_day_of_week,
            hour=settings.stocks_schedule_hour,
            minute=settings.stocks_schedule_minute,
        ),
        id="stocks_weekly",
        name="Weekly Stocks/ETFs/Bonds Analysis",
        replace_existing=True,
    )

    # Weekly Optimizer job (runs a few hours before stocks weekly to prepare parameters)
    scheduler.add_job(
        run_optimizer_weekly_job,
        CronTrigger(
            day_of_week=settings.stocks_schedule_day_of_week,
            hour=max(0, settings.stocks_schedule_hour - 3),
            minute=settings.stocks_schedule_minute,
        ),
        id="optimizer_weekly",
        name="Weekly Parameter Optimization",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started — crypto 4H strategy at UTC hours [%s], crypto stops watcher every [%s] min, stocks weekly on %s at %02d:%02d UTC",
        settings.crypto_strategy_cron_hours,
        settings.crypto_stops_check_cron_minutes,
        settings.stocks_schedule_day_of_week,
        settings.stocks_schedule_hour,
        settings.stocks_schedule_minute,
    )

    # Store scheduler on app state for access from routes
    app.state.scheduler = scheduler

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("Scheduler shut down")


# ── FastAPI app ─────────────────────────────────────────────────────────

app = FastAPI(
    title="Market Analysis & Investment Recommendation System",
    description="Automated portfolio analysis with crypto execution",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow frontend (dev: port 5173, prod: port 3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
from app.api.health import router as health_router
from app.api.portfolio import router as portfolio_router
from app.api.scores import router as scores_router
from app.api.crypto import router as crypto_router
from app.api.config import router as config_router

app.include_router(health_router)
app.include_router(portfolio_router)
app.include_router(scores_router)
app.include_router(crypto_router)
app.include_router(config_router)


# ── Manual trigger endpoints (run in background) ───────────────────────

@app.post("/api/jobs/crypto/trigger", tags=["jobs"])
async def trigger_crypto_job(background_tasks: BackgroundTasks):
    """Manually trigger the 4H crypto analysis job in the background."""
    logger.info("Manual trigger: crypto 4H strategy job requested")
    background_tasks.add_task(run_crypto_daily_job)
    return {"status": "started", "message": "Analyse crypto 4H lancée en tâche de fond"}


@app.post("/api/jobs/crypto-stops/trigger", tags=["jobs"])
async def trigger_crypto_stops_job(background_tasks: BackgroundTasks):
    """Manually trigger the 15-minute crypto stop-loss / trailing-stop check in the background."""
    logger.info("Manual trigger: crypto stops check job requested")
    background_tasks.add_task(run_crypto_stops_check_job)
    return {"status": "started", "message": "Vérification des stop-loss lancée en tâche de fond"}


@app.post("/api/jobs/stocks/trigger", tags=["jobs"])
async def trigger_stocks_job(background_tasks: BackgroundTasks):
    """Manually trigger the weekly stocks analysis job in the background."""
    logger.info("Manual trigger: stocks weekly job requested")
    background_tasks.add_task(run_stocks_weekly_job)
    return {"status": "started", "message": "Analyse hebdomadaire des actions/ETF lancée en tâche de fond"}


@app.post("/api/jobs/optimizer/trigger", tags=["jobs"])
async def trigger_optimizer_job(background_tasks: BackgroundTasks):
    """Manually trigger the optimizer job in the background."""
    logger.info("Manual trigger: optimizer weekly job requested")
    background_tasks.add_task(run_optimizer_weekly_job)
    return {"status": "started", "message": "L'optimiseur hebdomadaire a été lancé avec succès en tâche de fond."}


@app.get("/api/jobs/status", tags=["jobs"])

async def get_jobs_status():
    """Get scheduler status and next run times."""
    scheduler: AsyncIOScheduler = app.state.scheduler
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        })
    return {
        "scheduler_running": scheduler.running,
        "jobs": jobs,
    }
