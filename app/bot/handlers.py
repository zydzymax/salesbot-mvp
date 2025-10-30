"""
Telegram bot handlers for commands and callbacks
Handles user registration, commands, and interactions
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from aiogram import Dispatcher, Bot, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import structlog

from ..database.init_db import db_manager
from ..database.crud import ManagerCRUD, CallCRUD
from ..analysis.analyzer import CallAnalyzer
from .keyboards import *
from ..utils.helpers import format_analysis_summary, truncate_text

logger = structlog.get_logger("salesbot.bot.handlers")


class RegistrationStates(StatesGroup):
    """Registration FSM states"""
    waiting_for_name = State()
    waiting_for_confirmation = State()


class AnalysisStates(StatesGroup):
    """Analysis FSM states"""
    waiting_for_call_id = State()


def setup_handlers(dp: Dispatcher, bot: Bot):
    """Setup all bot handlers"""
    
    # Command handlers
    dp.message.register(start_command, CommandStart())
    dp.message.register(help_command, Command("help"))
    dp.message.register(stats_command, Command("stats"))
    dp.message.register(analyze_command, Command("analyze"))
    dp.message.register(report_command, Command("report"))
    
    # Text message handlers
    dp.message.register(handle_stats_request, F.text == "📊 Моя статистика")
    dp.message.register(handle_daily_report, F.text == "📋 Отчет за день")
    dp.message.register(handle_weekly_report, F.text == "📈 Отчет за неделю")
    dp.message.register(handle_analyze_request, F.text == "🔍 Анализ звонка")
    dp.message.register(handle_settings, F.text == "⚙️ Настройки")
    dp.message.register(handle_help_request, F.text == "❓ Помощь")
    
    # Callback handlers
    dp.callback_query.register(handle_stats_callback, F.data.startswith("stats:"))
    dp.callback_query.register(handle_analysis_callback, F.data.startswith("analysis:"))
    dp.callback_query.register(handle_report_callback, F.data.startswith("report:"))
    dp.callback_query.register(handle_admin_callback, F.data.startswith("admin:"))
    dp.callback_query.register(handle_settings_callback, F.data.startswith("settings:"))
    dp.callback_query.register(handle_help_callback, F.data.startswith("help:"))
    dp.callback_query.register(handle_menu_callback, F.data.startswith("menu:"))
    dp.callback_query.register(handle_noop_callback, F.data == "noop")
    
    # FSM handlers
    dp.message.register(handle_registration_name, RegistrationStates.waiting_for_name)
    dp.message.register(handle_analyze_call_id, AnalysisStates.waiting_for_call_id)
    
    # Catch-all handler
    dp.message.register(handle_unknown_message)


async def start_command(message: Message, state: FSMContext):
    """Handle /start command"""
    user_id = str(message.from_user.id)
    user_name = message.from_user.full_name
    
    logger.info(f"Start command", user_id=user_id, user_name=user_name)
    
    # Check if user is already registered
    async with db_manager.get_session() as session:
        manager = await ManagerCRUD.get_manager_by_telegram_id(session, user_id)
        
        if manager:
            # User already registered
            await message.answer(
                f"👋 Добро пожаловать обратно, {manager.name}!\n\n"
                f"Выберите действие из меню ниже:",
                reply_markup=get_main_menu_keyboard()
            )
        else:
            # New user registration
            await message.answer(
                f"👋 Добро пожаловать в SalesBot!\n\n"
                f"🤖 Я помогу анализировать ваши звонки и повышать эффективность продаж.\n\n"
                f"📋 Для начала работы нужно связать ваш Telegram с аккаунтом в AmoCRM.\n\n"
                f"✍️ Введите ваше полное имя, как оно указано в AmoCRM:",
                reply_markup=ReplyKeyboardRemove()
            )
            await state.set_state(RegistrationStates.waiting_for_name)


async def handle_registration_name(message: Message, state: FSMContext):
    """Handle name input during registration"""
    name = message.text.strip()
    
    if len(name) < 2:
        await message.answer("❌ Имя слишком короткое. Попробуйте еще раз:")
        return
    
    # Try to find manager in AmoCRM
    async with db_manager.get_session() as session:
        # Search by name (simplified - in production use better matching)
        managers = await ManagerCRUD.get_active_managers(session)
        matched_manager = None
        
        for manager in managers:
            if name.lower() in manager.name.lower() or manager.name.lower() in name.lower():
                matched_manager = manager
                break
        
        if matched_manager:
            # Link Telegram account
            success = await ManagerCRUD.link_telegram(
                session, matched_manager.id, str(message.from_user.id)
            )
            
            if success:
                await message.answer(
                    f"✅ Отлично! Ваш аккаунт связан.\n\n"
                    f"👤 {matched_manager.name}\n"
                    f"📧 {matched_manager.email or 'Email не указан'}\n\n"
                    f"Теперь вы можете пользоваться всеми функциями бота:",
                    reply_markup=get_main_menu_keyboard()
                )
                await state.clear()
            else:
                await message.answer(
                    "❌ Ошибка при связывании аккаунта. Попробуйте позже."
                )
        else:
            # Manager not found
            await message.answer(
                f"❌ Менеджер с именем '{name}' не найден в системе.\n\n"
                f"🔍 Проверьте правильность написания или обратитесь к администратору.\n\n"
                f"✍️ Попробуйте еще раз:"
            )


async def help_command(message: Message):
    """Handle /help command"""
    help_text = """
🤖 <b>SalesBot - Помощник по анализу звонков</b>

<b>📋 Основные команды:</b>
/start - Начать работу с ботом
/stats - Моя статистика
/analyze - Анализ конкретного звонка
/report - Создать отчет
/help - Эта справка

<b>🎯 Возможности:</b>
• 📊 Анализ качества звонков с оценками
• 📈 Статистика и отчеты по продажам
• 💡 Персональные рекомендации
• 🔔 Уведомления о важных событиях

<b>🚀 Быстрые действия:</b>
Используйте кнопки меню для быстрого доступа к функциям.

<b>❓ Нужна помощь?</b>
Обратитесь к администратору системы.
"""
    
    await message.answer(help_text, reply_markup=get_help_keyboard())


async def stats_command(message: Message):
    """Handle /stats command"""
    await handle_stats_request(message)


async def analyze_command(message: Message, state: FSMContext):
    """Handle /analyze command"""
    # Check if call ID provided
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    
    if args:
        call_id = args[0]
        await process_call_analysis(message, call_id)
    else:
        await message.answer(
            "🔍 <b>Анализ звонка</b>\n\n"
            "Введите ID звонка из AmoCRM для анализа:"
        )
        await state.set_state(AnalysisStates.waiting_for_call_id)


async def handle_analyze_call_id(message: Message, state: FSMContext):
    """Handle call ID input for analysis"""
    call_id = message.text.strip()
    await process_call_analysis(message, call_id)
    await state.clear()


async def process_call_analysis(message: Message, call_id: str):
    """Process call analysis request"""
    user_id = str(message.from_user.id)
    
    async with db_manager.get_session() as session:
        # Check if user is registered
        manager = await ManagerCRUD.get_manager_by_telegram_id(session, user_id)
        if not manager:
            await message.answer("❌ Сначала зарегистрируйтесь с помощью /start")
            return
        
        # Find call
        call = await CallCRUD.get_call_by_amocrm_id(session, call_id)
        if not call:
            await message.answer(f"❌ Звонок с ID {call_id} не найден")
            return
        
        # Check if call belongs to this manager (or if admin)
        if call.manager_id != manager.id:
            # TODO: Add admin check
            await message.answer("❌ У вас нет доступа к этому звонку")
            return
        
        # Check analysis status
        if not call.analysis_result:
            await message.answer(
                "⏳ Анализ звонка еще не завершен.\n"
                "Попробуйте позже или запросите повторный анализ."
            )
            return
        
        # Send analysis result
        from ..bot.telegram_bot import send_analysis_result
        await send_analysis_result(
            chat_id=user_id,
            call_id=str(call.id),
            analysis_result=call.analysis_result
        )


async def report_command(message: Message):
    """Handle /report command"""
    await handle_daily_report(message)


async def handle_stats_request(message: Message):
    """Handle statistics request"""
    user_id = str(message.from_user.id)
    
    async with db_manager.get_session() as session:
        manager = await ManagerCRUD.get_manager_by_telegram_id(session, user_id)
        if not manager:
            await message.answer("❌ Сначала зарегистрируйтесь с помощью /start")
            return
        
        # Get recent calls
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        calls = await CallCRUD.get_manager_calls(
            session, manager.id, date_from=today, limit=100
        )
        
        # Calculate stats
        total_calls = len(calls)
        analyzed_calls = sum(1 for call in calls if call.analysis_result)
        
        if analyzed_calls > 0:
            scores = [
                call.analysis_result.get("overall_score", 0) 
                for call in calls if call.analysis_result
            ]
            avg_score = sum(scores) / len(scores)
            max_score = max(scores)
        else:
            avg_score = 0
            max_score = 0
        
        stats_text = f"""
📊 <b>Статистика за сегодня</b>

👤 <b>Менеджер:</b> {manager.name}
📅 <b>Дата:</b> {today.strftime('%d.%m.%Y')}

📞 <b>Звонков:</b> {total_calls}
✅ <b>Проанализировано:</b> {analyzed_calls}
📈 <b>Средняя оценка:</b> {avg_score:.1f}/100
🏆 <b>Лучший результат:</b> {max_score}/100
"""
        
        await message.answer(
            stats_text,
            reply_markup=get_manager_stats_keyboard(manager.id)
        )


async def handle_daily_report(message: Message):
    """Handle daily report request"""
    user_id = str(message.from_user.id)
    
    async with db_manager.get_session() as session:
        manager = await ManagerCRUD.get_manager_by_telegram_id(session, user_id)
        if not manager:
            await message.answer("❌ Сначала зарегистрируйтесь с помощью /start")
            return
    
    await message.answer(
        "📋 <b>Дневной отчет</b>\n\n"
        "Создаю отчет за сегодня...",
        reply_markup=get_loading_keyboard()
    )
    
    # Queue report generation
    from ..tasks.workers import GenerateReportTask
    from ..tasks.queue import task_queue
    
    try:
        task = GenerateReportTask("daily", manager.id)
        await task_queue.add_task(task.execute, priority=6)
        
        # For demo, create simple report
        await asyncio.sleep(1)  # Simulate processing
        
        # Get calls for today
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        async with db_manager.get_session() as session:
            calls = await CallCRUD.get_manager_calls(
                session, manager.id, date_from=today
            )
        
        report_data = {
            "date": today.strftime('%d.%m.%Y'),
            "total_calls": len(calls),
            "analyzed_calls": sum(1 for call in calls if call.analysis_result),
            "average_score": 0,
            "top_score": 0
        }
        
        if calls:
            analyzed = [call for call in calls if call.analysis_result]
            if analyzed:
                scores = [call.analysis_result.get("overall_score", 0) for call in analyzed]
                report_data["average_score"] = sum(scores) / len(scores)
                report_data["top_score"] = max(scores)
        
        from ..bot.telegram_bot import format_daily_report
        report_text = format_daily_report(report_data)
        
        await message.answer(report_text)
        
    except Exception as e:
        logger.error(f"Failed to generate daily report: {e}")
        await message.answer("❌ Ошибка при создании отчета. Попробуйте позже.")


async def handle_weekly_report(message: Message):
    """Handle weekly report request"""
    await message.answer(
        "📈 <b>Недельный отчет</b>\n\n"
        "Функция в разработке. Пока доступен только дневной отчет."
    )


async def handle_analyze_request(message: Message, state: FSMContext):
    """Handle analyze request from menu"""
    await message.answer(
        "🔍 <b>Анализ звонка</b>\n\n"
        "Введите ID звонка из AmoCRM:"
    )
    await state.set_state(AnalysisStates.waiting_for_call_id)


async def handle_settings(message: Message):
    """Handle settings request"""
    user_id = str(message.from_user.id)
    
    async with db_manager.get_session() as session:
        manager = await ManagerCRUD.get_manager_by_telegram_id(session, user_id)
        if not manager:
            await message.answer("❌ Сначала зарегистрируйтесь с помощью /start")
            return
    
    await message.answer(
        "⚙️ <b>Настройки</b>\n\n"
        "Выберите раздел настроек:",
        reply_markup=get_settings_keyboard(manager.id)
    )


async def handle_help_request(message: Message):
    """Handle help request from menu"""
    await help_command(message)


# Callback handlers
async def handle_stats_callback(callback: CallbackQuery):
    """Handle statistics callbacks"""
    data_parts = callback.data.split(":")
    if len(data_parts) < 3:
        await callback.answer("❌ Неверные данные")
        return
    
    action = data_parts[1]  # daily, weekly, monthly, refresh
    manager_id = int(data_parts[2])
    
    if action == "refresh":
        await callback.answer("🔄 Обновляю статистику...")
        # Refresh and resend stats
        await handle_stats_request(callback.message)
    else:
        await callback.answer(f"📊 {action.title()} статистика в разработке")


async def handle_analysis_callback(callback: CallbackQuery):
    """Handle analysis callbacks"""
    data_parts = callback.data.split(":")
    if len(data_parts) < 3:
        await callback.answer("❌ Неверные данные")
        return
    
    action = data_parts[1]  # detailed, recommendations, objections, scores, rerun
    call_id = data_parts[2]
    
    if action == "detailed":
        await show_detailed_analysis(callback, call_id)
    elif action == "recommendations":
        await show_recommendations(callback, call_id)
    elif action == "objections":
        await show_objections(callback, call_id)
    elif action == "scores":
        await show_scores(callback, call_id)
    elif action == "rerun":
        await rerun_analysis(callback, call_id)
    
    await callback.answer()


async def show_detailed_analysis(callback: CallbackQuery, call_id: str):
    """Show detailed analysis"""
    # Implementation here
    await callback.message.edit_text(
        "📝 <b>Подробный анализ</b>\n\n"
        "Функция в разработке..."
    )


async def show_recommendations(callback: CallbackQuery, call_id: str):
    """Show recommendations"""
    # Implementation here
    await callback.message.edit_text(
        "💡 <b>Рекомендации</b>\n\n"
        "• Больше задавайте открытых вопросов\n"
        "• Активнее слушайте клиента\n"
        "• Конкретизируйте потребности"
    )


async def show_objections(callback: CallbackQuery, call_id: str):
    """Show objections analysis"""
    await callback.message.edit_text(
        "🎯 <b>Анализ возражений</b>\n\n"
        "Функция в разработке..."
    )


async def show_scores(callback: CallbackQuery, call_id: str):
    """Show detailed scores"""
    await callback.message.edit_text(
        "📊 <b>Детальные оценки</b>\n\n"
        "Функция в разработке..."
    )


async def rerun_analysis(callback: CallbackQuery, call_id: str):
    """Rerun call analysis"""
    await callback.message.edit_text(
        "🔄 <b>Повторный анализ</b>\n\n"
        "Запускаю анализ заново..."
    )


async def handle_report_callback(callback: CallbackQuery):
    """Handle report callbacks"""
    await callback.answer("📊 Генерирую отчет...")


async def handle_admin_callback(callback: CallbackQuery):
    """Handle admin callbacks"""
    await callback.answer("👥 Админ функции в разработке")


async def handle_settings_callback(callback: CallbackQuery):
    """Handle settings callbacks"""
    await callback.answer("⚙️ Настройки в разработке")


async def handle_help_callback(callback: CallbackQuery):
    """Handle help callbacks"""
    await callback.answer("❓ Справка загружается...")


async def handle_menu_callback(callback: CallbackQuery):
    """Handle menu callbacks"""
    if callback.data == "menu:main":
        await callback.message.edit_text(
            "🏠 Главное меню",
            reply_markup=get_main_menu_keyboard()
        )
    await callback.answer()


async def handle_noop_callback(callback: CallbackQuery):
    """Handle no-operation callbacks"""
    await callback.answer()


async def handle_unknown_message(message: Message):
    """Handle unknown messages"""
    await message.answer(
        "🤔 Не понимаю эту команду.\n\n"
        "Используйте /help для просмотра доступных команд или кнопки меню."
    )