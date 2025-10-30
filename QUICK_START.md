# ⚡ Быстрый Старт

## 1. Настройка Telegram Бота (5 минут)

### Шаг 1: Создать бота
```bash
# 1. Открыть Telegram
# 2. Найти @BotFather
# 3. Отправить /newbot
# 4. Следовать инструкциям
# 5. Получить TOKEN (например: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11)
```

### Шаг 2: Получить Chat ID
```bash
# 1. Написать боту /start
# 2. Выполнить команду (замените TOKEN):
curl "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates"

# 3. Найти в ответе "chat":{"id":123456789}
# 4. Скопировать chat_id (например: 123456789)
```

### Шаг 3: Обновить .env
```bash
cd /root/salesbot-mvp
nano .env

# Добавить строки:
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_ADMIN_CHAT_IDS=["123456789"]

# Сохранить: Ctrl+O, Enter, Ctrl+X
```

## 2. Запуск Системы (2 минуты)

```bash
cd /root/salesbot-mvp

# Проверить зависимости
pip install -r requirements.txt

# Запустить
python -m app.main
```

## 3. Проверка Работы (1 минута)

### Проверка 1: Health Check
```bash
curl http://localhost:8000/health
# Должно вернуть: {"status": "healthy", ...}
```

### Проверка 2: Веб-панель
```bash
# Открыть в браузере:
http://localhost:8000/admin/

# Должна открыться админ-панель с дашбордом
```

### Проверка 3: Telegram Алерты
```bash
# Отправить тестовое сообщение
python3 << 'EOF'
import asyncio
from app.alerts.telegram_alerts import telegram_alerts

async def test():
    result = await telegram_alerts.send_telegram_message(
        "ВАШ_CHAT_ID",  # Замените на свой chat_id
        "✅ <b>Тест успешен!</b>\n\nSalesBot подключен и работает"
    )
    print(f"Результат: {'✅ Успех' if result else '❌ Ошибка'}")

asyncio.run(test())
EOF
```

## 4. Что Происходит Автоматически

После запуска система автоматически:

✅ **Каждый час:**
- Проверяет просроченные обещания
- Отправляет алерты в Telegram

✅ **Каждые 15 минут (9-18 МСК):**
- Проверяет необработанные лиды
- Отправляет уведомления

✅ **Каждые 30 минут:**
- Отправляет напоминания о приближающихся дедлайнах

✅ **Каждый день в 18:00:**
- Отправляет ежедневную сводку

## 5. Доступ к Функциям

### Веб-Панель
```
http://localhost:8000/admin/
```

**Функции:**
- Статистика команды
- Рейтинги менеджеров
- Таблица сравнения
- Алерты

### API Endpoints
```bash
# QA оценка звонка
POST http://localhost:8000/api/calls/{call_id}/score-quality

# Извлечь обещания
POST http://localhost:8000/api/calls/{call_id}/extract-commitments

# Проверка fraud
POST http://localhost:8000/api/managers/{manager_id}/check-fraud

# KPI менеджера
GET http://localhost:8000/api/dashboard/manager/{manager_id}

# Рейтинг команды
GET http://localhost:8000/api/dashboard/leaderboard?metric=quality

# Алерты
GET http://localhost:8000/api/dashboard/alerts
```

### Документация API
```
http://localhost:8000/docs
```

## 6. Production Deployment

### Создать systemd service
```bash
sudo nano /etc/systemd/system/salesbot.service
```

```ini
[Unit]
Description=SalesBot MVP
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/salesbot-mvp
ExecStart=/usr/bin/python3 -m app.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Запустить
```bash
sudo systemctl daemon-reload
sudo systemctl enable salesbot
sudo systemctl start salesbot
sudo systemctl status salesbot
```

### Логи
```bash
# Все логи
sudo journalctl -u salesbot -f

# Только ошибки
sudo journalctl -u salesbot -p err

# За последний час
sudo journalctl -u salesbot --since "1 hour ago"
```

## 7. Troubleshooting

### Проблема: Алерты не отправляются

**Решение:**
```bash
# 1. Проверить .env
cat /root/salesbot-mvp/.env | grep TELEGRAM

# 2. Проверить логи
sudo journalctl -u salesbot | grep telegram

# 3. Тест отправки вручную (см. Проверка 3 выше)
```

### Проблема: Веб-панель не открывается

**Решение:**
```bash
# 1. Проверить запущено ли приложение
curl http://localhost:8000/health

# 2. Проверить логи
sudo journalctl -u salesbot | grep "dashboard"

# 3. Должно быть: "Admin dashboard router loaded"
```

### Проблема: Планировщик не работает

**Решение:**
```bash
# Проверить логи планировщика
sudo journalctl -u salesbot | grep "scheduler"

# Должны быть записи:
# "Starting task scheduler"
# "Started periodic task: ..."
```

## 8. Полезные Команды

```bash
# Перезапуск
sudo systemctl restart salesbot

# Остановка
sudo systemctl stop salesbot

# Статус
sudo systemctl status salesbot

# Проверка health
curl http://localhost:8000/health

# Проверка metrics
curl http://localhost:8000/metrics

# Обновление кода
cd /root/salesbot-mvp
git pull  # если используется git
sudo systemctl restart salesbot
```

## 9. Дополнительная Документация

- **DEPLOYMENT_GUIDE.md** - Полное руководство по деплою
- **NEW_FEATURES_GUIDE.md** - Описание всех функций
- **TESTING_REPORT.md** - Отчет о тестировании
- **RUN_TESTS.md** - Запуск тестов

## 10. Поддержка

**Логи для диагностики:**
```bash
sudo journalctl -u salesbot --since "1 hour ago" > logs.txt
cat logs.txt
```

**Проверка конфигурации:**
```bash
cat /root/salesbot-mvp/.env
python3 -m app.config  # Проверить настройки
```

---

**🎉 Готово! Система запущена и работает!**

Откройте http://localhost:8000/admin/ чтобы увидеть дашборд.
