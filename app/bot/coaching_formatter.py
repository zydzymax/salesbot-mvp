"""
Coaching Recommendations Formatter for Telegram
Formats AI recommendations in user-friendly Telegram messages
"""

from typing import Dict, Any, List
from datetime import datetime


class CoachingFormatter:
    """Format coaching recommendations for Telegram"""
    
    @staticmethod
    def format_deal_analysis(analysis: Dict[str, Any], manager_name: str = None) -> str:
        """
        Форматировать анализ сделки для отправки в Telegram
        """
        
        deal_name = analysis.get("deal_name", "Без названия")
        deal_id = analysis.get("deal_id")
        budget = analysis.get("budget", 0)
        recommendations = analysis.get("recommendations", {})
        metrics = analysis.get("metrics", {})
        
        # Иконка приоритета
        priority = recommendations.get("priority", "medium")
        priority_icon = {
            "high": "🔴",
            "medium": "🟡",
            "low": "🟢"
        }.get(priority, "🟡")
        
        # Вероятность конверсии
        conversion_prob = recommendations.get("estimated_conversion_probability", "50")
        
        message = f"""
{priority_icon} <b>АНАЛИЗ СДЕЛКИ</b>

📋 <b>Сделка:</b> {deal_name}
💰 <b>Бюджет:</b> {budget:,.0f} ₽
📊 <b>Вероятность закрытия:</b> {conversion_prob}%
"""
        
        if manager_name:
            message += f"👤 <b>Менеджер:</b> {manager_name}\n"
        
        # Метрики
        message += f"""
⏱ <b>В работе:</b> {metrics.get('deal_age_days', 0)} дн.
📞 <b>Звонков:</b> {metrics.get('total_calls', 0)} ({metrics.get('total_call_duration_seconds', 0)//60} мин)
💬 <b>Касаний:</b> {metrics.get('total_communications', 0)}
⚠️ <b>Дней без активности:</b> {metrics.get('days_since_last_update', 0)}

"""
        
        # Оценка ситуации
        assessment = recommendations.get("assessment", "")
        if assessment:
            message += f"<b>📝 ОЦЕНКА:</b>\n{assessment}\n\n"
        
        # Что хорошо
        strengths = recommendations.get("strengths", [])
        if strengths:
            message += "<b>✅ ЧТО ХОРОШО:</b>\n"
            for strength in strengths[:3]:
                message += f"  • {strength}\n"
            message += "\n"
        
        # Что беспокоит
        concerns = recommendations.get("concerns", [])
        if concerns:
            message += "<b>⚠️ ЧТО ВЫЗЫВАЕТ БЕСПОКОЙСТВО:</b>\n"
            for concern in concerns[:3]:
                message += f"  • {concern}\n"
            message += "\n"
        
        # Критичные проблемы
        red_flags = recommendations.get("red_flags", [])
        if red_flags:
            message += "<b>🚨 КРИТИЧНО:</b>\n"
            for flag in red_flags:
                message += f"  ⛔️ {flag}\n"
            message += "\n"
        
        # Рекомендации
        recs = recommendations.get("recommendations", [])
        if recs:
            message += "<b>💡 РЕКОМЕНДАЦИИ:</b>\n\n"
            
            for i, rec in enumerate(recs[:3], 1):
                urgency = rec.get("urgency", "planned")
                urgency_text = {
                    "immediate": "🔥 СРОЧНО",
                    "this_week": "⏰ НА ЭТОЙ НЕДЕЛЕ",
                    "planned": "📅 ЗАПЛАНИРОВАТЬ"
                }.get(urgency, "📅")
                
                message += f"{urgency_text}\n"
                message += f"<b>{i}. {rec.get('action', 'Действие')}</b>\n"
                message += f"   <i>Почему:</i> {rec.get('why', 'N/A')}\n"
                
                how = rec.get('how', '')
                if how:
                    message += f"   <i>Как:</i> {how}\n"
                
                message += "\n"
        
        # Предложенные фразы
        phrases = recommendations.get("suggested_phrases", [])
        if phrases:
            message += "<b>💬 ЧТО СКАЗАТЬ КЛИЕНТУ:</b>\n"
            for phrase in phrases[:3]:
                message += f"  • <i>\"{phrase}\"</i>\n"
            message += "\n"
        
        # Следующие шаги
        next_steps = recommendations.get("next_steps", [])
        if next_steps:
            message += "<b>🎯 ПЛАН ДЕЙСТВИЙ (2-3 дня):</b>\n"
            for step in next_steps[:3]:
                message += f"  ✓ {step}\n"
        
        message += f"\n<i>🤖 Анализ от {datetime.now().strftime('%d.%m.%Y %H:%M')}</i>"
        
        return message.strip()
    
    @staticmethod
    def format_deals_summary(
        manager_analysis: Dict[str, Any],
        manager_name: str = None
    ) -> str:
        """
        Форматировать общий отчёт по сделкам менеджера
        """
        
        total_deals = manager_analysis.get("total_deals", 0)
        total_budget = manager_analysis.get("total_budget", 0)
        deals_needing_attention = manager_analysis.get("deals_needing_attention", 0)
        
        message = f"""
📊 <b>ОБЗОР СДЕЛОК</b>
"""
        
        if manager_name:
            message += f"👤 <b>Менеджер:</b> {manager_name}\n"
        
        message += f"""
📁 <b>Сделок в работе:</b> {total_deals}
💰 <b>Общий бюджет:</b> {total_budget:,.0f} ₽
⚠️ <b>Требуют внимания:</b> {deals_needing_attention}

"""
        
        # Сделки требующие внимания
        attention_deals = manager_analysis.get("attention_deals", [])
        if attention_deals:
            message += "<b>🔔 СРОЧНО ПРОВЕРИТЬ:</b>\n\n"
            
            for deal in attention_deals[:5]:  # Топ 5
                deal_name = deal.get("deal_name", "Без названия")
                budget = deal.get("budget", 0)
                days_idle = deal.get("metrics", {}).get("days_since_last_update", 0)
                overdue = deal.get("metrics", {}).get("overdue_tasks", 0)
                
                priority = deal.get("recommendations", {}).get("priority", "medium")
                icon = "🔴" if priority == "high" else "🟡" if priority == "medium" else "🟢"
                
                message += f"{icon} <b>{deal_name}</b>\n"
                message += f"   💰 {budget:,.0f} ₽\n"
                
                if days_idle > 0:
                    message += f"   ⏰ {days_idle} дн. без активности\n"
                if overdue > 0:
                    message += f"   ⚠️ {overdue} просроченных задач\n"
                
                # Главная рекомендация
                recs = deal.get("recommendations", {}).get("recommendations", [])
                if recs:
                    main_rec = recs[0]
                    message += f"   💡 {main_rec.get('action', 'Требуется действие')}\n"
                
                message += "\n"
        
        message += f"<i>🤖 Анализ от {datetime.now().strftime('%d.%m.%Y %H:%M')}</i>"
        
        return message.strip()
    
    @staticmethod
    def format_quick_alert(
        deal_name: str,
        issue: str,
        action: str,
        urgency: str = "high"
    ) -> str:
        """
        Быстрое уведомление о проблеме
        """
        
        icon = "🔴" if urgency == "high" else "🟡"
        
        return f"""
{icon} <b>ВНИМАНИЕ</b>

📋 <b>Сделка:</b> {deal_name}
⚠️ <b>Проблема:</b> {issue}
💡 <b>Действие:</b> {action}

<i>Проверьте как можно скорее</i>
"""


# Global instance
coaching_formatter = CoachingFormatter()
