"""
Analysis result caching system
Redis-based caching with fallback to database
"""

import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

import aioredis
import structlog

from ..config import get_settings
from ..database.init_db import db_manager
from ..database.crud import AnalysisCacheCRUD

logger = structlog.get_logger("salesbot.analysis.cache")


class AnalysisCache:
    """Cache for analysis results with Redis and database fallback"""
    
    def __init__(self):
        self.settings = get_settings()
        self._redis_client = None
        
    async def get_redis_client(self) -> Optional[aioredis.Redis]:
        """Get Redis client with lazy initialization"""
        if not self._redis_client:
            try:
                self._redis_client = aioredis.from_url(
                    self.settings.redis_url,
                    decode_responses=True
                )
                # Test connection
                await self._redis_client.ping()
                logger.info("Redis connection established for analysis cache")
            except Exception as e:
                logger.warning(f"Redis connection failed, using database fallback: {e}")
                self._redis_client = None
        
        return self._redis_client
    
    async def get_analysis(
        self,
        cache_key: str,
        analysis_type: str
    ) -> Optional[Dict[str, Any]]:
        """Get cached analysis result"""
        
        # Try Redis first
        redis_client = await self.get_redis_client()
        if redis_client:
            try:
                redis_key = f"analysis:{analysis_type}:{cache_key}"
                cached_data = await redis_client.get(redis_key)
                
                if cached_data:
                    logger.info("Cache hit from Redis", cache_key=cache_key[:8])
                    return json.loads(cached_data)
                    
            except Exception as e:
                logger.warning(f"Redis cache get failed: {e}")
        
        # Fallback to database
        try:
            async with db_manager.get_session() as session:
                cached_result = await AnalysisCacheCRUD.get_cached_analysis(
                    session, cache_key, analysis_type
                )
                
                if cached_result:
                    logger.info("Cache hit from database", cache_key=cache_key[:8])
                    return cached_result
                    
        except Exception as e:
            logger.error(f"Database cache get failed: {e}")
        
        logger.debug("Cache miss", cache_key=cache_key[:8])
        return None
    
    async def save_analysis(
        self,
        cache_key: str,
        analysis_type: str,
        result: Dict[str, Any],
        ttl_seconds: int = 86400
    ):
        """Save analysis result to cache"""
        
        # Save to Redis
        redis_client = await self.get_redis_client()
        if redis_client:
            try:
                redis_key = f"analysis:{analysis_type}:{cache_key}"
                await redis_client.setex(
                    redis_key,
                    ttl_seconds,
                    json.dumps(result, default=str)
                )
                logger.info("Analysis cached to Redis", cache_key=cache_key[:8])
                
            except Exception as e:
                logger.warning(f"Redis cache save failed: {e}")
        
        # Save to database as backup
        try:
            async with db_manager.get_session() as session:
                await AnalysisCacheCRUD.save_analysis_cache(
                    session=session,
                    text_hash=cache_key,
                    analysis_type=analysis_type,
                    result=result,
                    ttl_seconds=ttl_seconds
                )
                logger.info("Analysis cached to database", cache_key=cache_key[:8])
                
        except Exception as e:
            logger.error(f"Database cache save failed: {e}")
    
    async def invalidate_cache(self, cache_key: str, analysis_type: str):
        """Invalidate specific cache entry"""
        
        # Remove from Redis
        redis_client = await self.get_redis_client()
        if redis_client:
            try:
                redis_key = f"analysis:{analysis_type}:{cache_key}"
                await redis_client.delete(redis_key)
                logger.info("Cache invalidated from Redis", cache_key=cache_key[:8])
                
            except Exception as e:
                logger.warning(f"Redis cache invalidation failed: {e}")
        
        # Note: Database entries expire automatically, no need to delete
    
    async def clear_expired_cache(self) -> int:
        """Clear expired cache entries"""
        cleaned_count = 0
        
        # Database cleanup (Redis entries expire automatically)
        try:
            async with db_manager.get_session() as session:
                cleaned_count = await AnalysisCacheCRUD.cleanup_expired_cache(session)
                logger.info(f"Cleaned {cleaned_count} expired cache entries from database")
                
        except Exception as e:
            logger.error(f"Cache cleanup failed: {e}")
        
        return cleaned_count
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache usage statistics"""
        stats = {
            "redis_available": False,
            "redis_keys": 0,
            "database_entries": 0,
            "total_size_mb": 0
        }
        
        # Redis stats
        redis_client = await self.get_redis_client()
        if redis_client:
            try:
                stats["redis_available"] = True
                
                # Count analysis keys
                analysis_keys = await redis_client.keys("analysis:*")
                stats["redis_keys"] = len(analysis_keys)
                
                # Get memory usage (rough estimate)
                info = await redis_client.info("memory")
                stats["redis_memory_mb"] = round(
                    info.get("used_memory", 0) / (1024 * 1024), 2
                )
                
            except Exception as e:
                logger.error(f"Failed to get Redis stats: {e}")
        
        # Database stats
        try:
            async with db_manager.get_session() as session:
                from sqlalchemy import func, select
                from ..database.models import AnalysisCache as CacheModel
                
                # Count entries
                result = await session.execute(
                    select(func.count(CacheModel.id))
                )
                stats["database_entries"] = result.scalar() or 0
                
                # Estimate size (very rough)
                if stats["database_entries"] > 0:
                    stats["estimated_db_size_mb"] = round(
                        stats["database_entries"] * 0.01, 2  # ~10KB per entry estimate
                    )
                
        except Exception as e:
            logger.error(f"Failed to get database cache stats: {e}")
        
        return stats
    
    async def warm_cache(self, popular_analyses: List[Dict[str, Any]]):
        """Pre-populate cache with popular analyses"""
        logger.info(f"Warming cache with {len(popular_analyses)} entries")
        
        for analysis in popular_analyses:
            try:
                await self.save_analysis(
                    cache_key=analysis["cache_key"],
                    analysis_type=analysis["analysis_type"],
                    result=analysis["result"],
                    ttl_seconds=analysis.get("ttl_seconds", 86400)
                )
            except Exception as e:
                logger.error(f"Failed to warm cache entry: {e}")
        
        logger.info("Cache warming completed")
    
    async def health_check(self) -> Dict[str, Any]:
        """Check cache health"""
        health = {
            "redis_healthy": False,
            "database_healthy": False,
            "overall_healthy": False
        }
        
        # Test Redis
        redis_client = await self.get_redis_client()
        if redis_client:
            try:
                await redis_client.ping()
                health["redis_healthy"] = True
            except Exception as e:
                logger.error(f"Redis health check failed: {e}")
        
        # Test database
        try:
            async with db_manager.get_session() as session:
                from sqlalchemy import select
                await session.execute(select(1))
                health["database_healthy"] = True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
        
        # Overall health (at least one cache backend working)
        health["overall_healthy"] = health["redis_healthy"] or health["database_healthy"]
        
        return health