"""
Monitoring and health check utilities
System metrics, health checks, and alerts
"""

import asyncio
import os
import psutil
from datetime import datetime
from typing import Dict, Any, Optional

import structlog
import aioredis

from ..config import get_settings
from ..database.init_db import db_manager
from ..amocrm.client import amocrm_client

logger = structlog.get_logger("salesbot.monitoring")


class MonitoringManager:
    """System monitoring and health checks"""
    
    def __init__(self):
        self.settings = get_settings()
        self.start_time = datetime.utcnow()
        self._redis_client = None
    
    async def get_redis_client(self):
        """Get Redis client for health checks"""
        if not self._redis_client:
            try:
                self._redis_client = aioredis.from_url(self.settings.redis_url)
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
        return self._redis_client
    
    async def check_database(self) -> Dict[str, Any]:
        """Check database connectivity and performance"""
        try:
            async with db_manager.get_session() as session:
                start_time = datetime.utcnow()
                await session.execute("SELECT 1")
                response_time = (datetime.utcnow() - start_time).total_seconds()
                
                return {
                    "status": "healthy",
                    "response_time_ms": round(response_time * 1000, 2)
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
    
    async def check_redis(self) -> Dict[str, Any]:
        """Check Redis connectivity"""
        try:
            redis_client = await self.get_redis_client()
            if not redis_client:
                return {"status": "unhealthy", "error": "No Redis connection"}
            
            start_time = datetime.utcnow()
            await redis_client.ping()
            response_time = (datetime.utcnow() - start_time).total_seconds()
            
            # Get Redis info
            info = await redis_client.info()
            
            return {
                "status": "healthy",
                "response_time_ms": round(response_time * 1000, 2),
                "memory_usage": info.get("used_memory_human"),
                "connected_clients": info.get("connected_clients")
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
    
    async def check_amocrm_connection(self) -> Dict[str, Any]:
        """Check AmoCRM API connectivity"""
        try:
            start_time = datetime.utcnow()
            is_connected = await amocrm_client.test_connection()
            response_time = (datetime.utcnow() - start_time).total_seconds()
            
            return {
                "status": "healthy" if is_connected else "unhealthy",
                "response_time_ms": round(response_time * 1000, 2)
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
    
    def get_disk_usage(self) -> Dict[str, Any]:
        """Get disk usage statistics"""
        try:
            disk_usage = psutil.disk_usage('/')
            
            return {
                "total_gb": round(disk_usage.total / (1024**3), 2),
                "used_gb": round(disk_usage.used / (1024**3), 2),
                "free_gb": round(disk_usage.free / (1024**3), 2),
                "percent_used": round((disk_usage.used / disk_usage.total) * 100, 1)
            }
        except Exception as e:
            return {"error": str(e)}
    
    def get_memory_usage(self) -> Dict[str, Any]:
        """Get memory usage statistics"""
        try:
            memory = psutil.virtual_memory()
            
            return {
                "total_mb": round(memory.total / (1024**2), 2),
                "used_mb": round(memory.used / (1024**2), 2),
                "available_mb": round(memory.available / (1024**2), 2),
                "percent_used": memory.percent
            }
        except Exception as e:
            return {"error": str(e)}
    
    def get_cpu_usage(self) -> Dict[str, Any]:
        """Get CPU usage statistics"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            
            return {
                "percent_used": cpu_percent,
                "cpu_count": cpu_count,
                "load_average": os.getloadavg() if hasattr(os, 'getloadavg') else None
            }
        except Exception as e:
            return {"error": str(e)}
    
    async def get_queue_size(self) -> Dict[str, Any]:
        """Get task queue size"""
        try:
            from ..tasks.queue import task_queue
            
            return {
                "pending_tasks": task_queue.qsize() if hasattr(task_queue, 'qsize') else 0,
                "active_workers": getattr(task_queue, 'active_workers', 0)
            }
        except Exception as e:
            return {"error": str(e)}
    
    def get_uptime(self) -> Dict[str, Any]:
        """Get application uptime"""
        uptime = datetime.utcnow() - self.start_time
        
        return {
            "uptime_seconds": int(uptime.total_seconds()),
            "uptime_human": str(uptime).split('.')[0],  # Remove microseconds
            "start_time": self.start_time.isoformat()
        }
    
    async def get_application_metrics(self) -> Dict[str, Any]:
        """Get application-specific metrics"""
        try:
            async with db_manager.get_session() as session:
                from ..database.crud import CallCRUD
                from ..database.models import TranscriptionStatus, AnalysisStatus
                
                # Get call statistics
                pending_transcriptions = len(await CallCRUD.get_calls_for_processing(
                    session, TranscriptionStatus.PENDING, limit=1000
                ))
                
                processing_transcriptions = len(await CallCRUD.get_calls_for_processing(
                    session, TranscriptionStatus.PROCESSING, limit=1000
                ))
                
                return {
                    "pending_transcriptions": pending_transcriptions,
                    "processing_transcriptions": processing_transcriptions,
                    "total_pending": pending_transcriptions + processing_transcriptions
                }
        except Exception as e:
            return {"error": str(e)}
    
    async def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check"""
        health_status = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "uptime": self.get_uptime(),
            "checks": {}
        }
        
        # Run all checks concurrently
        tasks = {
            "database": self.check_database(),
            "redis": self.check_redis(),
            "amocrm": self.check_amocrm_connection(),
            "application": self.get_application_metrics()
        }
        
        # Execute all checks
        for check_name, task in tasks.items():
            try:
                health_status["checks"][check_name] = await task
            except Exception as e:
                health_status["checks"][check_name] = {
                    "status": "unhealthy",
                    "error": str(e)
                }
        
        # Add system metrics
        health_status["checks"]["disk"] = self.get_disk_usage()
        health_status["checks"]["memory"] = self.get_memory_usage()
        health_status["checks"]["cpu"] = self.get_cpu_usage()
        health_status["checks"]["queue"] = await self.get_queue_size()
        
        # Determine overall status
        unhealthy_checks = []
        for check_name, check_result in health_status["checks"].items():
            if isinstance(check_result, dict) and check_result.get("status") == "unhealthy":
                unhealthy_checks.append(check_name)
        
        if unhealthy_checks:
            health_status["status"] = "unhealthy"
            health_status["unhealthy_checks"] = unhealthy_checks
        
        return health_status
    
    async def log_metric(self, metric_name: str, value: float, tags: Optional[Dict[str, str]] = None):
        """Log custom metric"""
        try:
            logger.info(
                f"metric.{metric_name}",
                value=value,
                tags=tags or {},
                timestamp=datetime.utcnow().isoformat()
            )
        except Exception as e:
            logger.error(f"Failed to log metric {metric_name}: {e}")
    
    async def alert(self, level: str, message: str, context: Optional[Dict[str, Any]] = None):
        """Send alert"""
        alert_data = {
            "level": level,
            "message": message,
            "context": context or {},
            "timestamp": datetime.utcnow().isoformat(),
            "environment": self.settings.environment
        }
        
        logger.warning(f"ALERT [{level}]: {message}", **alert_data)
        
        # In production, integrate with alerting system (Slack, email, etc.)
        # For now, just log the alert


# Global monitoring manager
monitoring_manager = MonitoringManager()