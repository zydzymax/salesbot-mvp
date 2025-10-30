"""
Database initialization and connection management
Optimized for SQLite with proper connection pooling
"""

from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import text

from ..config import get_settings
from .models import Base


class DatabaseManager:
    """Database connection and session management"""
    
    def __init__(self):
        self.settings = get_settings()
        self.engine = None
        self.session_factory = None
        
    async def init_database(self):
        """Initialize database connection and create tables"""
        # SQLite optimizations for better performance
        connect_args = {
            "check_same_thread": False,
            "timeout": 30,
        }
        
        # Create async engine with optimizations
        self.engine = create_async_engine(
            self.settings.database_url,
            echo=self.settings.debug,
            connect_args=connect_args,
            poolclass=StaticPool,
            pool_pre_ping=True,
            pool_recycle=3600,  # Recycle connections every hour
        )
        
        # Create session factory
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # Create all tables
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            
            # SQLite specific optimizations
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA synchronous=NORMAL"))
            await conn.execute(text("PRAGMA cache_size=10000"))
            await conn.execute(text("PRAGMA temp_store=MEMORY"))
            await conn.execute(text("PRAGMA mmap_size=268435456"))  # 256MB
            
        print("Database initialized successfully")
    
    @asynccontextmanager
    async def get_session(self):
        """Get database session as async context manager"""
        if not self.session_factory:
            await self.init_database()

        session = self.session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
    
    async def close(self):
        """Close database connections"""
        if self.engine:
            await self.engine.dispose()


# Global database manager instance
db_manager = DatabaseManager()


async def init_database():
    """Initialize database - called on startup"""
    await db_manager.init_database()


async def get_db_session() -> AsyncSession:
    """Dependency for FastAPI routes"""
    async with db_manager.get_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_test_data():
    """Create test data for development"""
    settings = get_settings()
    if not settings.is_development:
        return
        
    async with db_manager.get_session() as session:
        from .crud import ManagerCRUD
        
        # Create test manager
        existing_manager = await ManagerCRUD.get_manager_by_amocrm_id(
            session, "test_manager_001"
        )
        
        if not existing_manager:
            test_manager = await ManagerCRUD.create_manager(
                session=session,
                amocrm_user_id="test_manager_001",
                name="Test Manager",
                email="test@example.com"
            )
            print(f"Created test manager: {test_manager.name}")


async def cleanup_old_data():
    """Cleanup old data - run periodically"""
    async with db_manager.get_session() as session:
        from .crud import AnalysisCacheCRUD, SystemLogCRUD
        
        # Cleanup expired cache
        expired_count = await AnalysisCacheCRUD.cleanup_expired_cache(session)
        print(f"Cleaned up {expired_count} expired cache entries")
        
        # Cleanup old logs (keep 30 days)
        log_count = await SystemLogCRUD.cleanup_old_logs(session, days_to_keep=30)
        print(f"Cleaned up {log_count} old log entries")


if __name__ == "__main__":
    import asyncio
    
    async def main():
        await init_database()
        await create_test_data()
        print("Database setup complete!")
    
    asyncio.run(main())