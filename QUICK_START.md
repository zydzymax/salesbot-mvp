# Quick Start

## Prerequisites

- Python 3.10+
- Redis
- AmoCRM account (for full functionality)

## 1. Clone & Setup

```bash
git clone https://github.com/zydzymax/salesbot-mvp.git
cd salesbot-mvp

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your values
```

Required variables:
- `REDIS_URL` - Redis connection
- `OPENAI_API_KEY` - For AI analysis
- `AMOCRM_*` - AmoCRM credentials
- `TG_BOT_TOKEN` - Telegram bot

## 3. Start Services

```bash
# Start Redis (if not running)
redis-server &

# Start API
uvicorn app.main:app --host 0.0.0.0 --port 8001

# Start Telegram bot (optional)
python -m app.bot.telegram_bot
```

## 4. Verify

```bash
# Health check
curl http://localhost:8001/health

# API docs
open http://localhost:8001/docs
```

## Integration with AmoCRM

1. Create integration in AmoCRM
2. Set webhook URL: `https://your-domain/api/amocrm/webhook`
3. Configure in .env:
   - `AMOCRM_CLIENT_ID`
   - `AMOCRM_CLIENT_SECRET`
   - `AMOCRM_REDIRECT_URI`

## Useful Commands

```bash
# View logs
pm2 logs sovani_ai_seller

# Test analysis
curl -X POST http://localhost:8001/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"call_url": "https://example.com/call.mp3"}'
```

## Features

- AI call analysis
- Manager coaching
- Deal health scoring
- AmoCRM integration
- Telegram notifications

See [docs/](docs/) for detailed documentation.
