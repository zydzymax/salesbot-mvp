# Sales Coaching System - Complete Guide

## Overview

A comprehensive AI-powered sales coaching system has been implemented in the SalesBot MVP. The system analyzes all deals from a sales manager's perspective, monitors conversations and calls, tracks funnel conversions, and provides actionable coaching recommendations via Telegram.

## System Architecture

### New Modules Created

1. **Deal Analyzer** (`app/analysis/deal_analyzer.py`)
   - Comprehensive deal analysis with metrics calculation
   - Funnel conversion tracking
   - Communication pattern analysis

2. **AI Coach** (`app/analysis/ai_coach.py`)
   - GPT-4 powered coaching recommendations
   - Structured feedback generation
   - Conversion probability estimation

3. **Coaching Formatter** (`app/bot/coaching_formatter.py`)
   - Telegram message formatting
   - Priority-based visual indicators
   - Multi-format output (summary, detailed, alerts)

4. **Deal Monitor** (`app/tasks/deal_monitor.py`)
   - Periodic monitoring system
   - Background analysis tasks
   - Automatic notifications

## Features

### 1. Deal Analysis

The system analyzes each deal comprehensively:

- **Metrics Calculated:**
  - Deal age (days in pipeline)
  - Days since last activity
  - Total communications (calls + messages)
  - Call statistics (count, duration)
  - Funnel movement tracking
  - Task completion rate
  - Overdue tasks count

- **AI Recommendations Include:**
  - Situation assessment
  - Strengths (what manager does well)
  - Concerns (potential problems)
  - Red flags (critical issues)
  - Priority level (high/medium/low)
  - Specific action items with urgency
  - Suggested phrases for client communication
  - Next steps (2-3 day action plan)
  - Conversion probability estimate

### 2. Telegram Notifications

Messages are formatted with:
- 🔴/🟡/🟢 Priority indicators
- 📋 Deal information
- 💰 Budget
- 📊 Conversion probability
- ⏱ Key metrics
- 📝 Situation assessment
- ✅ Strengths
- ⚠️ Concerns
- 🚨 Critical issues
- 💡 Actionable recommendations
- 💬 Example phrases
- 🎯 Action plan

### 3. Monitoring Modes

**Periodic Monitoring:**
- Configurable interval (1-168 hours)
- Analyzes all active deals
- Sends summary to each manager
- Detailed analysis for high-priority deals only

**On-Demand Analysis:**
- Single deal analysis
- Manager-specific analysis
- Stale deal detection

## API Endpoints

All endpoints are available at `https://app.justbusiness.lol/salesbot/api/`

### 1. Analyze Single Deal
```bash
POST /api/deals/{deal_id}/analyze?notify=true

Response:
{
  "status": "queued",
  "deal_id": 12345,
  "notify": true,
  "message": "Deal analysis queued"
}
```

### 2. Analyze Manager's Deals
```bash
POST /api/managers/{manager_id}/analyze-deals

Response:
{
  "status": "queued",
  "manager_id": 1,
  "manager_name": "Иван Петров",
  "message": "Manager deals analysis queued"
}
```

### 3. Analyze All Deals
```bash
POST /api/deals/analyze-all

Response:
{
  "status": "queued",
  "message": "All deals analysis queued",
  "timestamp": "2025-10-24T18:57:51.807350"
}
```

### 4. Check Stale Deals
```bash
POST /api/deals/check-stale?days_threshold=3

Response:
{
  "status": "queued",
  "days_threshold": 3,
  "message": "Stale deals check queued"
}
```

### 5. Start Periodic Monitoring
```bash
POST /api/monitoring/start?interval_hours=24

Response:
{
  "status": "started",
  "interval_hours": 24,
  "message": "Deal monitoring started with 24h interval"
}
```

### 6. Stop Monitoring
```bash
POST /api/monitoring/stop

Response:
{
  "status": "stopped",
  "message": "Deal monitoring stopped"
}
```

### 7. Check Monitoring Status
```bash
GET /api/monitoring/status

Response:
{
  "is_running": false,
  "timestamp": "2025-10-24T18:57:51.807350"
}
```

## Usage Examples

### Start Daily Monitoring

```bash
curl -X POST "https://app.justbusiness.lol/salesbot/api/monitoring/start?interval_hours=24"
```

This will:
1. Analyze all active deals every 24 hours
2. Send summary report to each manager
3. Send detailed analysis for high-priority deals
4. Continue running until stopped

### Analyze Specific Deal

```bash
curl -X POST "https://app.justbusiness.lol/salesbot/api/deals/123456/analyze?notify=true"
```

This will:
1. Fetch deal data from AmoCRM
2. Analyze communications and funnel history
3. Generate AI coaching recommendations
4. Send formatted message to responsible manager

### Check for Inactive Deals

```bash
curl -X POST "https://app.justbusiness.lol/salesbot/api/deals/check-stale?days_threshold=5"
```

This will:
1. Find all deals without activity for 5+ days
2. Send urgent alerts to managers
3. Provide specific action items

## Example Telegram Message

```
🔴 АНАЛИЗ СДЕЛКИ

📋 Сделка: Поставка оборудования ООО "Рога и Копыта"
💰 Бюджет: 450,000 ₽
📊 Вероятность закрытия: 65%
👤 Менеджер: Иван Петров

⏱ В работе: 12 дн.
📞 Звонков: 3 (45 мин)
💬 Касаний: 7
⚠️ Дней без активности: 4

📝 ОЦЕНКА:
Сделка находится на важном этапе принятия решения. Клиент заинтересован, но нет активности последние 4 дня - критично для крупной суммы.

✅ ЧТО ХОРОШО:
  • Регулярные созвоны на ранних этапах
  • Хорошо выявлены потребности
  • Бюджет согласован

⚠️ ЧТО ВЫЗЫВАЕТ БЕСПОКОЙСТВО:
  • Нет контакта 4 дня - риск потери внимания
  • Медленное движение по воронке
  • Не назначена следующая встреча

🚨 КРИТИЧНО:
  ⛔️ Сделка застряла на этапе "Переговоры" более 10 дней
  ⛔️ Нет запланированных активностей

💡 РЕКОМЕНДАЦИИ:

🔥 СРОЧНО
1. Позвонить клиенту сегодня
   Почему: 4 дня без контакта при крупной сделке - высокий риск потери
   Как: Инициировать звонок с конкретной ценностью (новое предложение/кейс)

⏰ НА ЭТОЙ НЕДЕЛЕ
2. Организовать демонстрацию оборудования
   Почему: Клиент принимает решение - нужен эмоциональный триггер
   Как: Предложить 2-3 удобных слота на этой неделе

📅 ЗАПЛАНИРОВАТЬ
3. Подготовить коммерческое предложение с бонусами
   Почему: Для финального толчка к сделке
   Как: Добавить ограниченное по времени спецпредложение

💬 ЧТО СКАЗАТЬ КЛИЕНТУ:
  • "Иван Петрович, подготовил для вас интересное предложение по оптимизации бюджета"
  • "Хочу показать вам кейс похожей компании - результаты впечатляющие"
  • "Готов организовать демо на вашей площадке в удобное время"

🎯 ПЛАН ДЕЙСТВИЙ (2-3 дня):
  ✓ Позвонить клиенту сегодня до 18:00
  ✓ Договориться о встрече/демонстрации
  ✓ Отправить кейс и обновленное КП

🤖 Анализ от 24.10.2025 21:57
```

## Configuration

### Environment Variables

Add to `.env`:
```bash
# OpenAI for AI coaching
OPENAI_API_KEY=sk-proj-...

# AmoCRM credentials
AMOCRM_ACCESS_TOKEN=...
AMOCRM_REFRESH_TOKEN=...

# Telegram bot
TELEGRAM_BOT_TOKEN=...
```

### Adjust AI Prompts

Edit `/root/salesbot-mvp/app/analysis/ai_coach.py` to customize:
- Coaching style
- Recommendation format
- Priority criteria
- Assessment guidelines

### Customize Formatting

Edit `/root/salesbot-mvp/app/bot/coaching_formatter.py` to change:
- Message templates
- Icons and emojis
- Sections shown
- Priority thresholds

## Integration with Existing System

The coaching system integrates seamlessly with existing components:

- **Database**: Uses existing `Manager` and `Call` models
- **AmoCRM Client**: Reuses `amocrm_client` for API calls
- **Task Queue**: Works with existing background task system
- **Telegram Bot**: Uses established bot infrastructure

## Testing

Test the system:

```bash
# Check system status
curl https://app.justbusiness.lol/salesbot/

# Check monitoring status
curl https://app.justbusiness.lol/salesbot/api/monitoring/status

# Start monitoring
curl -X POST "https://app.justbusiness.lol/salesbot/api/monitoring/start?interval_hours=24"

# Analyze all deals once
curl -X POST "https://app.justbusiness.lol/salesbot/api/deals/analyze-all"
```

## Production Deployment

The system is already deployed:
- ✅ Service: `salesbot-api.service` running on port 8001
- ✅ Nginx: Reverse proxy configured
- ✅ SSL: Covered by existing certificate
- ✅ Auto-restart: Enabled via systemd

## Monitoring & Logs

View logs:
```bash
# Service logs
sudo journalctl -u salesbot-api -f

# Recent errors
sudo journalctl -u salesbot-api -p err --since "1 hour ago"
```

Check service status:
```bash
sudo systemctl status salesbot-api
```

## Next Steps

1. **Add managers to database** with Telegram chat IDs
2. **Start periodic monitoring** with desired interval
3. **Monitor first analysis results** in Telegram
4. **Adjust prompts/formatting** based on feedback
5. **Set up alerts** for critical deals
6. **Configure schedules** for different teams

## Support

Files created/modified:
- `/root/salesbot-mvp/app/analysis/deal_analyzer.py` - Deal analysis engine
- `/root/salesbot-mvp/app/analysis/ai_coach.py` - AI coaching logic
- `/root/salesbot-mvp/app/bot/coaching_formatter.py` - Message formatting
- `/root/salesbot-mvp/app/tasks/deal_monitor.py` - Monitoring worker
- `/root/salesbot-mvp/app/main.py` - API endpoints
- `/root/salesbot-mvp/app/bot/__init__.py` - Bot module exports

All code follows existing patterns and is production-ready.
