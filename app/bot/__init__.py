"""
Telegram bot module
Handles user interactions, commands, and notifications
"""

from .telegram_bot import (
    bot,
    initialize_bot,
    start_polling,
    stop_bot,
    send_message,
    send_notification,
    send_analysis_result,
    format_daily_report
)

try:
    from .handlers import setup_handlers
except ImportError:
    setup_handlers = None

try:
    from .keyboards import *
except ImportError:
    pass