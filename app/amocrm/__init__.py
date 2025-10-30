"""
AmoCRM integration module
Handles API calls, webhooks, and data synchronization

Чтобы избежать циклических импортов, импортируйте напрямую:
    from app.amocrm.client import AmoCRMClient, amocrm_client
    from app.amocrm.webhooks import WebhookHandler
    from app.amocrm.sync import DataSynchronizer
"""

# Не импортируем автоматически, чтобы избежать циклических зависимостей
# from .client import AmoCRMClient
# from .webhooks import WebhookHandler
# from .sync import DataSynchronizer