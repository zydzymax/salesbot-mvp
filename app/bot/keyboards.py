"""
Telegram inline keyboards and reply markups
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from typing import List, Dict, Any


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Main menu keyboard"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Моя статистика")],
            [KeyboardButton(text="📋 Отчет за день"), KeyboardButton(text="📈 Отчет за неделю")],
            [KeyboardButton(text="🔍 Анализ звонка"), KeyboardButton(text="⚙️ Настройки")],
            [KeyboardButton(text="❓ Помощь")]
        ],
        resize_keyboard=True,
        persistent=True
    )
    return keyboard


def get_manager_stats_keyboard(manager_id: int) -> InlineKeyboardMarkup:
    """Manager statistics keyboard"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Сегодня",
                    callback_data=f"stats:daily:{manager_id}"
                ),
                InlineKeyboardButton(
                    text="📈 Неделя", 
                    callback_data=f"stats:weekly:{manager_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📅 Месяц",
                    callback_data=f"stats:monthly:{manager_id}"
                ),
                InlineKeyboardButton(
                    text="🔄 Обновить",
                    callback_data=f"stats:refresh:{manager_id}"
                )
            ]
        ]
    )
    return keyboard


def get_call_analysis_keyboard(call_id: str) -> InlineKeyboardMarkup:
    """Call analysis keyboard"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📝 Подробный анализ",
                    callback_data=f"analysis:detailed:{call_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💡 Рекомендации",
                    callback_data=f"analysis:recommendations:{call_id}"
                ),
                InlineKeyboardButton(
                    text="🎯 Возражения",
                    callback_data=f"analysis:objections:{call_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Оценки",
                    callback_data=f"analysis:scores:{call_id}"
                ),
                InlineKeyboardButton(
                    text="🔄 Повторить анализ",
                    callback_data=f"analysis:rerun:{call_id}"
                )
            ]
        ]
    )
    return keyboard


def get_report_keyboard(report_type: str, manager_id: int = None) -> InlineKeyboardMarkup:
    """Report generation keyboard"""
    keyboard_buttons = []
    
    if report_type == "daily":
        keyboard_buttons = [
            [
                InlineKeyboardButton(
                    text="📄 Получить отчет",
                    callback_data=f"report:generate:daily:{manager_id or 'all'}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Сводка",
                    callback_data=f"report:summary:daily:{manager_id or 'all'}"
                ),
                InlineKeyboardButton(
                    text="📈 Графики",
                    callback_data=f"report:charts:daily:{manager_id or 'all'}"
                )
            ]
        ]
    elif report_type == "weekly":
        keyboard_buttons = [
            [
                InlineKeyboardButton(
                    text="📄 Недельный отчет",
                    callback_data=f"report:generate:weekly:{manager_id or 'all'}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Динамика",
                    callback_data=f"report:trends:weekly:{manager_id or 'all'}"
                ),
                InlineKeyboardButton(
                    text="🏆 Топ звонков",
                    callback_data=f"report:top:weekly:{manager_id or 'all'}"
                )
            ]
        ]
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)


def get_admin_keyboard(manager_id: int) -> InlineKeyboardMarkup:
    """Admin/ROP keyboard with team management"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👥 Отчет по команде",
                    callback_data="admin:team_report"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚠️ Проблемные звонки",
                    callback_data="admin:issues"
                ),
                InlineKeyboardButton(
                    text="🏆 Лучшие менеджеры",
                    callback_data="admin:top_performers"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Аналитика",
                    callback_data="admin:analytics"
                ),
                InlineKeyboardButton(
                    text="⚙️ Настройки",
                    callback_data="admin:settings"
                )
            ]
        ]
    )
    return keyboard


def get_settings_keyboard(manager_id: int) -> InlineKeyboardMarkup:
    """Settings keyboard"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔔 Уведомления",
                    callback_data=f"settings:notifications:{manager_id}"
                ),
                InlineKeyboardButton(
                    text="🕐 Время отчетов",
                    callback_data=f"settings:schedule:{manager_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📱 Связать аккаунт",
                    callback_data=f"settings:link_account:{manager_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❓ Помощь",
                    callback_data="help:settings"
                ),
                InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data="menu:main"
                )
            ]
        ]
    )
    return keyboard


def get_help_keyboard() -> InlineKeyboardMarkup:
    """Help keyboard"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Быстрый старт",
                    callback_data="help:quickstart"
                ),
                InlineKeyboardButton(
                    text="📋 Команды",
                    callback_data="help:commands"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Анализ звонков",
                    callback_data="help:analysis"
                ),
                InlineKeyboardButton(
                    text="📈 Отчеты",
                    callback_data="help:reports"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔧 Настройка",
                    callback_data="help:setup"
                ),
                InlineKeyboardButton(
                    text="❓ FAQ",
                    callback_data="help:faq"
                )
            ]
        ]
    )
    return keyboard


def get_pagination_keyboard(
    current_page: int,
    total_pages: int,
    prefix: str,
    extra_data: str = ""
) -> InlineKeyboardMarkup:
    """Pagination keyboard"""
    buttons = []
    
    # Navigation buttons
    nav_buttons = []
    
    if current_page > 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️ Пред",
                callback_data=f"{prefix}:page:{current_page-1}:{extra_data}"
            )
        )
    
    nav_buttons.append(
        InlineKeyboardButton(
            text=f"{current_page}/{total_pages}",
            callback_data="noop"  # No operation
        )
    )
    
    if current_page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(
                text="След ➡️",
                callback_data=f"{prefix}:page:{current_page+1}:{extra_data}"
            )
        )
    
    buttons.append(nav_buttons)
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_call_list_keyboard(calls: List[Dict[str, Any]], page: int = 1) -> InlineKeyboardMarkup:
    """Keyboard for call list with pagination"""
    buttons = []
    
    # Add call buttons (max 5 per page)
    start_idx = (page - 1) * 5
    end_idx = start_idx + 5
    page_calls = calls[start_idx:end_idx]
    
    for call in page_calls:
        call_id = call.get("id", "")
        client_phone = call.get("client_phone", "Неизвестен")
        score = call.get("analysis_result", {}).get("overall_score", 0)
        
        button_text = f"📞 {client_phone} ({score}/100)"
        buttons.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"call:view:{call_id}"
            )
        ])
    
    # Add pagination if needed
    total_pages = (len(calls) + 4) // 5  # Ceiling division
    if total_pages > 1:
        pagination = get_pagination_keyboard(page, total_pages, "calls", "")
        buttons.extend(pagination.inline_keyboard)
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_confirmation_keyboard(action: str, data: str = "") -> InlineKeyboardMarkup:
    """Confirmation keyboard"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да",
                    callback_data=f"confirm:{action}:{data}"
                ),
                InlineKeyboardButton(
                    text="❌ Нет",
                    callback_data="cancel"
                )
            ]
        ]
    )
    return keyboard


def get_back_keyboard(callback_data: str = "menu:main") -> InlineKeyboardMarkup:
    """Simple back button keyboard"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=callback_data
                )
            ]
        ]
    )
    return keyboard


def get_loading_keyboard() -> InlineKeyboardMarkup:
    """Loading keyboard"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⏳ Загрузка...",
                    callback_data="noop"
                )
            ]
        ]
    )
    return keyboard