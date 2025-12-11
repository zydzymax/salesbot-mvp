"""
FastAPI application for SalesBot MVP
Production-ready API with proper middleware and error handling
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, Depends, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
import structlog

from .config import get_settings
from .database.init_db import init_database, create_test_data
from .utils.monitoring import monitoring_manager
from .amocrm.webhooks import WebhookHandler
from .amocrm.sync import data_synchronizer
from .tasks.queue import task_queue, TaskQueueManager
from .tasks.scheduler import task_scheduler
from .utils.helpers import safe_json_loads

# Setup structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("salesbot.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    settings = get_settings()
    logger.info("Starting SalesBot MVP", version="1.0.0", environment=settings.environment)
    
    try:
        # Initialize database
        await init_database()

        # Run initial sync from AmoCRM (managers and leads with calls)
        logger.info("Starting initial AmoCRM synchronization...")
        try:
            sync_result = await data_synchronizer.full_sync(sync_leads=True)
            if sync_result.get("status") == "completed":
                logger.info(
                    "Initial sync completed",
                    managers=sync_result.get("results", {}).get("managers", {}),
                    leads=sync_result.get("results", {}).get("leads", {})
                )
            else:
                logger.warning("Initial sync failed", result=sync_result)
        except Exception as e:
            logger.error(f"Failed to run initial sync: {e}")

        # Create test data in development (ONLY if sync failed or no data)
        if settings.is_development:
            # Check if we have any data
            from .database.init_db import db_manager
            async with db_manager.get_session() as session:
                from sqlalchemy import select, func
                from .database.models import Call
                call_count = await session.scalar(select(func.count(Call.id)))

                if call_count == 0:
                    logger.warning("No calls found after sync, creating test data...")
                    await create_test_data()

        # Start task queue
        await task_queue.start()

        # Start task scheduler for alerts and periodic jobs
        await task_scheduler.start()

        # Start periodic sync in background
        if settings.environment == "production":
            asyncio.create_task(data_synchronizer.start_periodic_sync(interval_minutes=60))

        logger.info("Application startup completed")
        
        yield
        
    finally:
        # Cleanup
        logger.info("Shutting down application")
        await task_scheduler.stop()
        await task_queue.stop()
        logger.info("Application shutdown completed")


# Create FastAPI app
app = FastAPI(
    title="SalesBot MVP",
    description="AI-powered sales call analysis system",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if get_settings().is_development else None,
    redoc_url="/redoc" if get_settings().is_development else None
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if get_settings().is_development else ["https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"] if get_settings().is_development else ["app.justbusiness.lol", "localhost", "127.0.0.1"]
)

# Include web admin dashboard router
try:
    from .web.routers.admin_dashboard import router as admin_router
    app.include_router(admin_router)
    logger.info("Admin dashboard router loaded")
except Exception as e:
    logger.warning(f"Failed to load admin dashboard: {e}")

# Include deals router
try:
    from .web.routers.deals import router as deals_router
    app.include_router(deals_router, prefix="/admin")
    logger.info("Deals router loaded")
except Exception as e:
    logger.warning(f"Failed to load deals router: {e}")

# Include settings router
try:
    from .web.routers.settings import router as settings_router
    app.include_router(settings_router, prefix="/admin")
    logger.info("Settings router loaded")
except Exception as e:
    logger.warning(f"Failed to load settings router: {e}")

# Include ROP dashboard router
try:
    from .web.routers.rop_dashboard import router as rop_router
    app.include_router(rop_router, prefix="/admin")
    logger.info("ROP dashboard router loaded")
except Exception as e:
    logger.warning(f"Failed to load ROP dashboard router: {e}")

# Include auth router
try:
    from .web.routers.auth import router as auth_router
    app.include_router(auth_router)
    logger.info("Auth router loaded")
except Exception as e:
    logger.warning(f"Failed to load auth router: {e}")

# Include dashboard router
try:
    from .web.routers.dashboard import router as dashboard_router
    app.include_router(dashboard_router)
    logger.info("Dashboard router loaded")
except Exception as e:
    logger.warning(f"Failed to load dashboard router: {e}")


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests"""
    start_time = datetime.utcnow()
    
    # Generate request ID
    request_id = f"{int(start_time.timestamp())}-{id(request)}"
    
    logger.info(
        "Request started",
        request_id=request_id,
        method=request.method,
        url=str(request.url),
        client_ip=request.client.host if request.client else None
    )
    
    try:
        response = await call_next(request)
        
        duration = (datetime.utcnow() - start_time).total_seconds()
        
        logger.info(
            "Request completed",
            request_id=request_id,
            status_code=response.status_code,
            duration_seconds=round(duration, 3)
        )
        
        return response
        
    except Exception as e:
        duration = (datetime.utcnow() - start_time).total_seconds()
        
        logger.error(
            "Request failed",
            request_id=request_id,
            error=str(e),
            duration_seconds=round(duration, 3)
        )
        
        raise


# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.status_code,
                "message": exc.detail,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": 500,
                "message": "Internal server error",
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )


# Health check endpoint
@app.get("/health")
async def health_check():
    """Comprehensive health check"""
    try:
        health_status = await monitoring_manager.health_check()
        
        status_code = 200 if health_status["status"] == "healthy" else 503
        
        return JSONResponse(
            status_code=status_code,
            content=health_status
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )


# Metrics endpoint (protected)
@app.get("/metrics")
async def get_metrics(api_key: str = None):
    """Get system metrics"""
    settings = get_settings()
    
    # Simple API key check (in production, use proper auth)
    if api_key != "metrics_key_123":  # Change this in production
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    try:
        metrics = {
            "timestamp": datetime.utcnow().isoformat(),
            "system": monitoring_manager.get_uptime(),
            "queue": await monitoring_manager.get_queue_size(),
            "application": await monitoring_manager.get_application_metrics()
        }
        
        return metrics
        
    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to get metrics")


# AmoCRM webhook endpoints
@app.post("/webhook/amocrm/call")
async def amocrm_call_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle AmoCRM call webhooks"""
    try:
        # Get raw body for validation
        body = await request.body()
        
        # Parse JSON
        webhook_data = safe_json_loads(body.decode('utf-8'))
        if not webhook_data:
            raise HTTPException(status_code=400, detail="Invalid JSON")
        
        logger.info("Received AmoCRM webhook", webhook_keys=list(webhook_data.keys()))
        
        # Process webhook in background
        background_tasks.add_task(
            process_webhook_background,
            webhook_data
        )
        
        return {"status": "accepted", "timestamp": datetime.utcnow().isoformat()}
        
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")


async def process_webhook_background(webhook_data: Dict[str, Any]):
    """Process webhook in background"""
    try:
        result = await WebhookHandler.process_webhook(webhook_data)
        logger.info("Webhook processed", result=result)
    except Exception as e:
        logger.error(f"Background webhook processing failed: {e}")


# Manual analysis endpoint
@app.post("/api/analyze/{amocrm_call_id}")
async def analyze_call_manual(
    amocrm_call_id: str,
    background_tasks: BackgroundTasks
):
    """Manually trigger call analysis"""
    try:
        from .database.init_db import db_manager
        from .database.crud import CallCRUD
        from .tasks.workers import AnalyzeCallTask
        
        # Find call in database
        async with db_manager.get_session() as session:
            call = await CallCRUD.get_call_by_amocrm_id(session, amocrm_call_id)
            
            if not call:
                raise HTTPException(status_code=404, detail="Call not found")
            
            if not call.transcription_text:
                raise HTTPException(status_code=400, detail="Call not transcribed yet")
        
        # Queue analysis task
        analysis_task = AnalyzeCallTask(str(call.id))
        task_id = await task_queue.add_task(analysis_task.execute, priority=1)
        
        return {
            "status": "queued",
            "task_id": task_id,
            "call_id": str(call.id),
            "amocrm_call_id": amocrm_call_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to queue analysis: {e}")
        raise HTTPException(status_code=500, detail="Failed to queue analysis")


# Report generation endpoint
@app.get("/api/report/{report_type}")
async def generate_report(
    report_type: str,
    manager_id: int = None,
    date_from: str = None,
    date_to: str = None,
    background_tasks: BackgroundTasks = None
):
    """Generate and return report"""
    try:
        from .tasks.workers import GenerateReportTask
        from datetime import datetime
        
        # Parse dates
        date_from_dt = None
        date_to_dt = None
        
        if date_from:
            date_from_dt = datetime.fromisoformat(date_from)
        if date_to:
            date_to_dt = datetime.fromisoformat(date_to)
        
        # Queue report generation
        report_task = GenerateReportTask(
            report_type=report_type,
            manager_id=manager_id,
            date_from=date_from_dt,
            date_to=date_to_dt
        )
        
        task_id = await task_queue.add_task(report_task.execute, priority=6)
        
        return {
            "status": "queued",
            "task_id": task_id,
            "report_type": report_type,
            "estimated_completion": "2-5 minutes"
        }
        
    except Exception as e:
        logger.error(f"Failed to queue report: {e}")
        raise HTTPException(status_code=500, detail="Failed to queue report")


# Sync endpoint
@app.post("/api/sync")
async def trigger_sync(sync_type: str = "recent", background_tasks: BackgroundTasks = None):
    """Trigger data synchronization with AmoCRM"""
    try:
        if sync_type == "full":
            background_tasks.add_task(data_synchronizer.full_sync)
        elif sync_type == "recent":
            background_tasks.add_task(data_synchronizer.sync_recent_calls, 24)
        elif sync_type == "managers":
            background_tasks.add_task(data_synchronizer.sync_managers)
        else:
            raise HTTPException(status_code=400, detail="Invalid sync type")
        
        return {
            "status": "started",
            "sync_type": sync_type,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start sync: {e}")
        raise HTTPException(status_code=500, detail="Failed to start sync")


# Task status endpoint
@app.get("/api/task/{task_id}")
async def get_task_status(task_id: str):
    """Get task status"""
    try:
        task = await task_queue.get_task(task_id)
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        return {
            "task_id": task.id,
            "status": task.status,
            "created_at": task.created_at.isoformat(),
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "result": task.result,
            "error": task.error,
            "retry_count": task.retry_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get task status")


# Queue statistics
@app.get("/api/queue/stats")
async def get_queue_stats():
    """Get task queue statistics"""
    try:
        stats = task_queue.get_stats()
        return stats
    except Exception as e:
        logger.error(f"Failed to get queue stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get queue stats")


# Deal Analysis Endpoints
@app.post("/api/deals/{deal_id}/analyze")
async def analyze_deal(
    deal_id: int,
    notify: bool = True,
    background_tasks: BackgroundTasks = None
):
    """Analyze a single deal and optionally send recommendations to manager"""
    try:
        from .tasks.deal_monitor import deal_monitor

        # Queue analysis in background
        if background_tasks:
            background_tasks.add_task(
                deal_monitor.analyze_single_deal,
                deal_id,
                notify
            )

            return {
                "status": "queued",
                "deal_id": deal_id,
                "notify": notify,
                "message": "Deal analysis queued"
            }
        else:
            # Execute immediately
            analysis = await deal_monitor.analyze_single_deal(deal_id, notify)

            if not analysis:
                raise HTTPException(status_code=404, detail="Deal not found or analysis failed")

            return {
                "status": "completed",
                "deal_id": deal_id,
                "analysis": analysis
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to analyze deal: {e}", deal_id=deal_id)
        raise HTTPException(status_code=500, detail=f"Failed to analyze deal: {str(e)}")


@app.post("/api/managers/{manager_id}/analyze-deals")
async def analyze_manager_deals(
    manager_id: int,
    background_tasks: BackgroundTasks = None
):
    """Analyze all deals for a specific manager"""
    try:
        from .database.init_db import db_manager
        from .database.crud import ManagerCRUD
        from .tasks.deal_monitor import deal_monitor

        # Find manager
        async with db_manager.get_session() as session:
            manager = await ManagerCRUD.get_manager(session, manager_id)

            if not manager:
                raise HTTPException(status_code=404, detail="Manager not found")

        # Queue analysis in background
        if background_tasks:
            background_tasks.add_task(
                deal_monitor.analyze_manager_deals,
                manager
            )

            return {
                "status": "queued",
                "manager_id": manager_id,
                "manager_name": manager.name,
                "message": "Manager deals analysis queued"
            }
        else:
            # Execute immediately
            await deal_monitor.analyze_manager_deals(manager)

            return {
                "status": "completed",
                "manager_id": manager_id,
                "manager_name": manager.name,
                "message": "Analysis sent to manager via Telegram"
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to analyze manager deals: {e}", manager_id=manager_id)
        raise HTTPException(status_code=500, detail=f"Failed to analyze manager deals: {str(e)}")


@app.post("/api/deals/analyze-all")
async def analyze_all_deals(background_tasks: BackgroundTasks):
    """Analyze all active deals for all managers"""
    try:
        from .tasks.deal_monitor import deal_monitor

        # Queue analysis in background
        background_tasks.add_task(deal_monitor.analyze_all_deals)

        return {
            "status": "queued",
            "message": "All deals analysis queued",
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to analyze all deals: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to analyze all deals: {str(e)}")


@app.post("/api/deals/check-stale")
async def check_stale_deals(
    days_threshold: int = 3,
    background_tasks: BackgroundTasks = None
):
    """Check for deals without activity for N days"""
    try:
        from .tasks.deal_monitor import deal_monitor

        if days_threshold < 1 or days_threshold > 30:
            raise HTTPException(status_code=400, detail="days_threshold must be between 1 and 30")

        # Queue check in background
        if background_tasks:
            background_tasks.add_task(
                deal_monitor.check_stale_deals,
                days_threshold
            )

            return {
                "status": "queued",
                "days_threshold": days_threshold,
                "message": "Stale deals check queued"
            }
        else:
            # Execute immediately
            await deal_monitor.check_stale_deals(days_threshold)

            return {
                "status": "completed",
                "days_threshold": days_threshold,
                "message": "Stale deals check completed"
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to check stale deals: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to check stale deals: {str(e)}")


@app.post("/api/monitoring/start")
async def start_deal_monitoring(interval_hours: int = 24):
    """Start periodic deal monitoring"""
    try:
        from .tasks.deal_monitor import deal_monitor

        if interval_hours < 1 or interval_hours > 168:
            raise HTTPException(status_code=400, detail="interval_hours must be between 1 and 168 (1 week)")

        if deal_monitor.is_running:
            return {
                "status": "already_running",
                "message": "Deal monitoring is already running"
            }

        # Start monitoring in background task
        asyncio.create_task(deal_monitor.start_monitoring(interval_hours))

        return {
            "status": "started",
            "interval_hours": interval_hours,
            "message": f"Deal monitoring started with {interval_hours}h interval"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start monitoring: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start monitoring: {str(e)}")


@app.post("/api/monitoring/stop")
async def stop_deal_monitoring():
    """Stop periodic deal monitoring"""
    try:
        from .tasks.deal_monitor import deal_monitor

        if not deal_monitor.is_running:
            return {
                "status": "not_running",
                "message": "Deal monitoring is not running"
            }

        deal_monitor.stop_monitoring()

        return {
            "status": "stopped",
            "message": "Deal monitoring stopped"
        }

    except Exception as e:
        logger.error(f"Failed to stop monitoring: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop monitoring: {str(e)}")


@app.get("/api/monitoring/status")
async def get_monitoring_status():
    """Get current monitoring status"""
    try:
        from .tasks.deal_monitor import deal_monitor

        return {
            "is_running": deal_monitor.is_running,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to get monitoring status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get monitoring status: {str(e)}")


# Quality Scoring Endpoints
@app.post("/api/calls/{call_id}/score-quality")
async def score_call_quality(call_id: str):
    """Оценить качество звонка"""
    try:
        from .database.crud import CallCRUD
        from .analysis.call_quality_scorer import call_quality_scorer

        # Получить звонок
        async with db_manager.get_session() as session:
            call = await CallCRUD.get_call_by_id(session, call_id)

            if not call:
                raise HTTPException(status_code=404, detail="Call not found")

            if not call.transcription_text:
                raise HTTPException(status_code=400, detail="Call not transcribed yet")

        # Оценить качество
        quality_result = await call_quality_scorer.score_call(
            transcription=call.transcription_text,
            call_type="general",
            call_duration=call.duration_seconds or 0
        )

        # Сохранить результат
        async with db_manager.get_session() as session:
            call = await CallCRUD.get_call_by_id(session, call_id)
            call.quality_score = int(quality_result['total_score'])
            call.quality_analysis = quality_result
            call.quality_evaluated_at = datetime.utcnow()
            await session.commit()

        return quality_result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to score call quality: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/managers/{manager_id}/quality-stats")
async def get_manager_quality_stats(manager_id: int, days: int = 7):
    """Получить статистику качества звонков менеджера"""
    try:
        from_date = datetime.utcnow() - timedelta(days=days)

        async with db_manager.get_session() as session:
            from sqlalchemy import select, and_, func
            from .database.models import Call

            # Все звонки с оценкой
            stmt = select(Call).where(
                and_(
                    Call.manager_id == manager_id,
                    Call.created_at >= from_date,
                    Call.quality_score != None
                )
            )

            result = await session.execute(stmt)
            calls = list(result.scalars().all())

            if not calls:
                return {
                    "manager_id": manager_id,
                    "period_days": days,
                    "calls_scored": 0,
                    "avg_score": 0
                }

            avg_score = sum(c.quality_score for c in calls) / len(calls)
            scores_distribution = {
                'excellent': len([c for c in calls if c.quality_score >= 90]),
                'good': len([c for c in calls if 80 <= c.quality_score < 90]),
                'satisfactory': len([c for c in calls if 70 <= c.quality_score < 80]),
                'needs_improvement': len([c for c in calls if c.quality_score < 70])
            }

            return {
                "manager_id": manager_id,
                "period_days": days,
                "calls_scored": len(calls),
                "avg_score": round(avg_score, 1),
                "distribution": scores_distribution
            }

    except Exception as e:
        logger.error(f"Failed to get quality stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Commitment Tracking Endpoints
@app.get("/api/managers/{manager_id}/commitments")
async def get_manager_commitments(
    manager_id: int,
    status: str = "all"  # all, pending, overdue, fulfilled
):
    """Получить обещания менеджера"""
    try:
        async with db_manager.get_session() as session:
            from sqlalchemy import select, and_
            from .analysis.commitment_tracker import Commitment

            stmt = select(Commitment).where(Commitment.manager_id == manager_id)

            if status == "pending":
                stmt = stmt.where(and_(
                    Commitment.is_fulfilled == False,
                    Commitment.is_overdue == False
                ))
            elif status == "overdue":
                stmt = stmt.where(and_(
                    Commitment.is_fulfilled == False,
                    Commitment.is_overdue == True
                ))
            elif status == "fulfilled":
                stmt = stmt.where(Commitment.is_fulfilled == True)

            stmt = stmt.order_by(Commitment.deadline.asc())

            result = await session.execute(stmt)
            commitments = result.scalars().all()

            return {
                "manager_id": manager_id,
                "status_filter": status,
                "count": len(commitments),
                "commitments": [
                    {
                        "id": c.id,
                        "text": c.commitment_text,
                        "deadline": c.deadline.isoformat(),
                        "category": c.category,
                        "priority": c.priority,
                        "is_fulfilled": c.is_fulfilled,
                        "is_overdue": c.is_overdue
                    }
                    for c in commitments
                ]
            }

    except Exception as e:
        logger.error(f"Failed to get commitments: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/commitments/check-overdue")
async def check_overdue_commitments():
    """Проверить просроченные обещания"""
    try:
        from .analysis.commitment_tracker import commitment_tracker

        overdue = await commitment_tracker.check_overdue_commitments()

        return {
            "checked_at": datetime.utcnow().isoformat(),
            "overdue_count": len(overdue),
            "overdue_commitments": overdue
        }

    except Exception as e:
        logger.error(f"Failed to check overdue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Fraud Detection Endpoints
@app.get("/api/managers/{manager_id}/fraud-check")
async def check_manager_fraud(manager_id: int, days: int = 7):
    """Проверить менеджера на подозрительную активность"""
    try:
        from .fraud.activity_validator import activity_validator

        result = await activity_validator.detect_suspicious_activity(manager_id, days)

        return result

    except Exception as e:
        logger.error(f"Failed to check fraud: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Dashboard Endpoints
@app.get("/api/dashboard/manager/{manager_id}/kpi")
async def get_manager_kpi(manager_id: int, days: int = 7):
    """Получить KPI менеджера"""
    try:
        from .analytics.manager_dashboard import manager_dashboard

        kpi = await manager_dashboard.get_manager_kpi(manager_id, days)

        return kpi

    except Exception as e:
        logger.error(f"Failed to get manager KPI: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/team/comparison")
async def get_team_comparison(days: int = 7):
    """Сравнение всей команды"""
    try:
        from .analytics.manager_dashboard import manager_dashboard

        comparison = await manager_dashboard.get_team_comparison(days)

        return {
            "period_days": days,
            "team_size": len(comparison),
            "managers": comparison
        }

    except Exception as e:
        logger.error(f"Failed to get team comparison: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/leaderboard")
async def get_leaderboard(days: int = 7, metric: str = "quality"):
    """Рейтинг менеджеров"""
    try:
        from .analytics.manager_dashboard import manager_dashboard

        leaderboard = await manager_dashboard.get_leaderboard(days, metric)

        return {
            "period_days": days,
            "metric": metric,
            "leaderboard": leaderboard
        }

    except Exception as e:
        logger.error(f"Failed to get leaderboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/alerts")
async def get_dashboard_alerts():
    """Получить алерты по проблемам"""
    try:
        from .analytics.manager_dashboard import manager_dashboard

        alerts = await manager_dashboard.get_alerts()

        return {
            "alerts_count": len(alerts),
            "alerts": alerts,
            "checked_at": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to get alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/daily-report")
async def get_daily_report():
    """Ежедневный отчет"""
    try:
        from .analytics.manager_dashboard import manager_dashboard

        report = await manager_dashboard.generate_daily_report()

        return report

    except Exception as e:
        logger.error(f"Failed to generate daily report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    settings = get_settings()

    return {
        "name": "SalesBot MVP",
        "version": "1.0.0",
        "environment": settings.environment,
        "status": "running",
        "timestamp": datetime.utcnow().isoformat(),
        "endpoints": {
            "health": "/health",
            "metrics": "/metrics",
            "docs": "/docs" if settings.is_development else None,
            "deal_analysis": {
                "analyze_single": "POST /api/deals/{deal_id}/analyze",
                "analyze_manager": "POST /api/managers/{manager_id}/analyze-deals",
                "analyze_all": "POST /api/deals/analyze-all",
                "check_stale": "POST /api/deals/check-stale",
                "start_monitoring": "POST /api/monitoring/start",
                "stop_monitoring": "POST /api/monitoring/stop",
                "monitoring_status": "GET /api/monitoring/status"
            },
            "quality_scoring": {
                "score_call": "POST /api/calls/{call_id}/score-quality",
                "manager_stats": "GET /api/managers/{manager_id}/quality-stats"
            },
            "commitments": {
                "get_manager_commitments": "GET /api/managers/{manager_id}/commitments",
                "check_overdue": "POST /api/commitments/check-overdue"
            },
            "fraud_detection": {
                "check_manager": "GET /api/managers/{manager_id}/fraud-check"
            },
            "dashboard": {
                "manager_kpi": "GET /api/dashboard/manager/{manager_id}/kpi",
                "team_comparison": "GET /api/dashboard/team/comparison",
                "leaderboard": "GET /api/dashboard/leaderboard",
                "alerts": "GET /api/dashboard/alerts",
                "daily_report": "GET /api/dashboard/daily-report"
            }
        }
    }


if __name__ == "__main__":
    import uvicorn
    
    settings = get_settings()
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.is_development,
        log_level=settings.log_level.lower(),
        access_log=True
    )