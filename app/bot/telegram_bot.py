"""
Telegram bot main module
Handles bot initialization and message sending
"""

import asyncio
from typing import Optional, Dict, Any
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
import structlog

from ..config import get_settings
from .handlers import setup_handlers

logger = structlog.get_logger("salesbot.bot.telegram_bot")

# Global bot and dispatcher instances
bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None


async def initialize_bot():
    """Initialize Telegram bot"""
    global bot, dp
    
    settings = get_settings()
    
    if not settings.telegram_bot_token:
        logger.warning("Telegram bot token not configured")
        return False
    
    try:
        bot = Bot(token=settings.telegram_bot_token, parse_mode=ParseMode.HTML)
        dp = Dispatcher()
        
        # Setup handlers
        setup_handlers(dp, bot)
        
        # Get bot info
        bot_info = await bot.get_me()
        logger.info(
            "Telegram bot initialized",
            bot_username=bot_info.username,
            bot_id=bot_info.id
        )
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize bot: {e}")
        return False


async def start_polling():
    """Start bot polling"""
    global dp
    
    if not dp:
        success = await initialize_bot()
        if not success:
            logger.error("Cannot start polling without initialized bot")
            return
    
    try:
        logger.info("Starting Telegram bot polling")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Polling error: {e}")


async def stop_bot():
    """Stop bot"""
    global bot, dp
    
    if bot:
        await bot.session.close()
        logger.info("Telegram bot stopped")


async def send_message(chat_id: str, text: str, **kwargs) -> bool:
    """Send message to chat"""
    global bot
    
    if not bot:
        await initialize_bot()
    
    if not bot:
        logger.error("Bot not initialized, cannot send message")
        return False
    
    try:
        await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        logger.info(f"Message sent to {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        return False


async def send_notification(chat_id: str, message: str) -> bool:
    """Send notification to user"""
    return await send_message(chat_id, message, parse_mode=ParseMode.HTML)


async def send_analysis_result(
    chat_id: str,
    call_id: str,
    analysis_result: Dict[str, Any]
) -> bool:
    """Send analysis result to user"""
    try:
        overall_score = analysis_result.get("overall_score", 0)
        summary = analysis_result.get("summary", "Анализ завершен")
        client_sentiment = analysis_result.get("client_sentiment", "neutral")
        
        # Format sentiment emoji
        sentiment_emoji = {
            "positive": "😊",
            "neutral": "😐",
            "negative": "😟"
        }.get(client_sentiment, "😐")
        
        message = f"""
✅ <b>Анализ звонка завершен</b>

📞 <b>ID звонка:</b> <code>{call_id}</code>
📊 <b>Общая оценка:</b> {overall_score:.1f}/100

{sentiment_emoji} <b>Настроение клиента:</b> {client_sentiment}

📝 <b>Краткое резюме:</b>
{summary}

<i>Используйте /analyze {call_id} для подробного анализа</i>
"""
        
        return await send_message(chat_id, message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Failed to send analysis result: {e}")
        return False


def format_daily_report(report_data: Dict[str, Any]) -> str:
    """Format daily report for Telegram"""
    date = report_data.get("date", "сегодня")
    total_calls = report_data.get("total_calls", 0)
    analyzed_calls = report_data.get("analyzed_calls", 0)
    avg_score = report_data.get("average_score", 0)
    top_score = report_data.get("top_score", 0)
    
    return f"""
📋 <b>Отчет за {date}</b>

📞 <b>Звонков:</b> {total_calls}
✅ <b>Проанализировано:</b> {analyzed_calls}
📈 <b>Средний балл:</b> {avg_score:.1f}/100
🏆 <b>Лучший результат:</b> {top_score}/100

{'⚠️ Рекомендуется провести больше звонков' if total_calls < 5 else '✅ Хорошая активность!'}
"""


# Background task to run bot
_bot_task: Optional[asyncio.Task] = None


async def start_bot_background():
    """Start bot in background"""
    global _bot_task
    
    if _bot_task and not _bot_task.done():
        logger.warning("Bot already running")
        return
    
    _bot_task = asyncio.create_task(start_polling())
    logger.info("Bot background task started")


async def stop_bot_background():
    """Stop background bot task"""
    global _bot_task
    
    if _bot_task:
        _bot_task.cancel()
        try:
            await _bot_task
        except asyncio.CancelledError:
            pass
        logger.info("Bot background task stopped")
    
    await stop_bot()
