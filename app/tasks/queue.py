"""
Simple AsyncIO task queue for background processing
Lightweight alternative to Celery for MVP
"""

import asyncio
import heapq
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum
import uuid

import structlog

logger = structlog.get_logger("salesbot.tasks.queue")


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """Task representation"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    func: Callable = None
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    priority: int = 5  # Lower number = higher priority
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    
    def __lt__(self, other):
        # For heapq ordering
        return (self.priority, self.created_at) < (other.priority, other.created_at)


class SimpleTaskQueue:
    """Simple async task queue with priorities and workers"""
    
    def __init__(self, max_workers: int = 2, max_queue_size: int = 100):
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size
        
        self._queue = []  # Priority heap
        self._tasks = {}  # Task ID -> Task mapping
        self._workers = []
        self._running = False
        self._queue_lock = asyncio.Lock()
        
        self.active_tasks = 0
        self.completed_tasks = 0
        self.failed_tasks = 0
        
    async def add_task(
        self,
        func: Callable,
        *args,
        priority: int = 5,
        max_retries: int = 3,
        **kwargs
    ) -> str:
        """Add task to queue"""
        if len(self._queue) >= self.max_queue_size:
            raise RuntimeError("Task queue is full")
        
        task = Task(
            func=func,
            args=args,
            kwargs=kwargs,
            priority=priority,
            max_retries=max_retries
        )
        
        async with self._queue_lock:
            heapq.heappush(self._queue, task)
            self._tasks[task.id] = task
        
        logger.info(f"Task added to queue", task_id=task.id, priority=priority)
        return task.id
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID"""
        return self._tasks.get(task_id)
    
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel pending task"""
        task = self._tasks.get(task_id)
        if not task or task.status != TaskStatus.PENDING:
            return False
        
        task.status = TaskStatus.CANCELLED
        logger.info(f"Task cancelled", task_id=task_id)
        return True
    
    async def _get_next_task(self) -> Optional[Task]:
        """Get next task from queue"""
        async with self._queue_lock:
            while self._queue:
                task = heapq.heappop(self._queue)
                if task.status == TaskStatus.PENDING:
                    return task
                # Remove cancelled/completed tasks from queue
                
        return None
    
    async def _execute_task(self, task: Task) -> None:
        """Execute single task"""
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()
        self.active_tasks += 1
        
        logger.info(f"Executing task", task_id=task.id)
        
        try:
            if asyncio.iscoroutinefunction(task.func):
                result = await task.func(*task.args, **task.kwargs)
            else:
                result = task.func(*task.args, **task.kwargs)
            
            task.result = result
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()
            self.completed_tasks += 1
            
            logger.info(f"Task completed", task_id=task.id)
            
        except Exception as e:
            task.error = str(e)
            task.retry_count += 1
            
            logger.error(f"Task failed", task_id=task.id, error=str(e))
            
            # Retry logic
            if task.retry_count <= task.max_retries:
                task.status = TaskStatus.PENDING
                # Re-add to queue with lower priority
                async with self._queue_lock:
                    task.priority += 1
                    heapq.heappush(self._queue, task)
                
                logger.info(f"Task queued for retry", task_id=task.id, retry=task.retry_count)
            else:
                task.status = TaskStatus.FAILED
                self.failed_tasks += 1
                logger.error(f"Task failed permanently", task_id=task.id)
        
        finally:
            self.active_tasks -= 1
    
    async def _worker(self, worker_id: int):
        """Worker coroutine"""
        logger.info(f"Worker {worker_id} started")
        
        try:
            while self._running:
                task = await self._get_next_task()
                
                if task:
                    await self._execute_task(task)
                else:
                    # No tasks available, wait a bit
                    await asyncio.sleep(0.1)
        
        except asyncio.CancelledError:
            logger.info(f"Worker {worker_id} cancelled")
        except Exception as e:
            logger.error(f"Worker {worker_id} error: {e}")
        
        finally:
            logger.info(f"Worker {worker_id} stopped")
    
    async def start(self):
        """Start the task queue workers"""
        if self._running:
            return
        
        self._running = True
        
        # Start workers
        for i in range(self.max_workers):
            worker = asyncio.create_task(self._worker(i))
            self._workers.append(worker)
        
        logger.info(f"Task queue started with {self.max_workers} workers")
    
    async def stop(self, timeout: float = 10.0):
        """Stop the task queue gracefully"""
        if not self._running:
            return
        
        logger.info("Stopping task queue...")
        self._running = False
        
        # Cancel all workers
        for worker in self._workers:
            worker.cancel()
        
        # Wait for workers to finish
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._workers, return_exceptions=True),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.warning("Task queue stop timeout, forcing shutdown")
        
        self._workers.clear()
        logger.info("Task queue stopped")
    
    def qsize(self) -> int:
        """Get queue size"""
        return len(self._queue)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        return {
            "queue_size": len(self._queue),
            "active_tasks": self.active_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "running": self._running,
            "workers": len(self._workers),
        }
    
    async def cleanup_old_tasks(self, hours: int = 24):
        """Clean up old completed/failed tasks"""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        
        to_remove = []
        for task_id, task in self._tasks.items():
            if (task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED] and
                task.completed_at and task.completed_at < cutoff_time):
                to_remove.append(task_id)
        
        for task_id in to_remove:
            del self._tasks[task_id]
        
        logger.info(f"Cleaned up {len(to_remove)} old tasks")


# Global task queue instance
task_queue = SimpleTaskQueue()


# Context manager for queue lifecycle
class TaskQueueManager:
    """Context manager for task queue"""
    
    def __init__(self, queue: SimpleTaskQueue):
        self.queue = queue
    
    async def __aenter__(self):
        await self.queue.start()
        return self.queue
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.queue.stop()