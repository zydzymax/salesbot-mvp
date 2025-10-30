"""
Task queue and workers for async processing
Simple AsyncIO-based queue without Celery

Чтобы избежать циклических импортов, импортируйте напрямую:
    from app.tasks.queue import task_queue, Task
    from app.tasks.workers import process_call_analysis
"""

# Не импортируем автоматически, чтобы избежать циклических зависимостей
# from .queue import task_queue, Task
# from .workers import *