# 📊 Интеграция Дашборда в AmoCRM

## Обзор

Этот гайд показывает как встроить дашборд менеджеров прямо в интерфейс AmoCRM через виджет.

## 🎯 Что получим

- **Вкладка в AmoCRM** с дашбордом команды
- **Карточки менеджеров** с их метриками
- **Автообновление** данных каждые 30 секунд
- **Доступ из любого места** в AmoCRM

## 📋 Методы интеграции

### Метод 1: Приватный виджет (Рекомендуется для начала)

Это самый быстрый способ - создать приватный виджет только для вашего аккаунта.

### Метод 2: Публичный виджет в Marketplace

Для публикации в каталоге виджетов AmoCRM (требует модерации).

---

## 🚀 Метод 1: Приватный виджет

### Шаг 1: Создать структуру виджета

```bash
cd /root/salesbot-mvp
mkdir -p widget
cd widget

# Создать файлы виджета
```

### Шаг 2: Создать manifest.json

```bash
cat > manifest.json << 'EOF'
{
  "widget": {
    "name": "widget.salesbot_dashboard",
    "description": "Дашборд команды продаж с аналитикой менеджеров",
    "short_description": "Дашборд продаж",
    "version": "1.0.0",
    "init_once": false,
    "locale": ["ru"],
    "installation": true,
    "settings": {
      "server_url": {
        "name": "settings.server_url",
        "type": "text",
        "required": true
      }
    }
  },
  "locations": [
    "settings",
    "advanced_settings"
  ],
  "tour": {
    "is_tour": false
  }
}
EOF
```

### Шаг 3: Создать i18n/ru.json (локализация)

```bash
mkdir i18n
cat > i18n/ru.json << 'EOF'
{
  "widget": {
    "name": "SalesBot Dashboard",
    "description": "Дашборд команды продаж с метриками качества и активности",
    "short_description": "Дашборд продаж"
  },
  "settings": {
    "server_url": "URL сервера (например: http://your-server:8000)"
  }
}
EOF
```

### Шаг 4: Создать script.js

```bash
cat > script.js << 'EOF'
define(['jquery'], function($) {
    var CustomWidget = function() {
        this.callbacks = {
            settings: function() {
                // Настройки виджета
                return true;
            },
            init: function() {
                // Инициализация виджета
                return true;
            },
            bind_actions: function() {
                // Привязка действий
                return true;
            },
            render: function() {
                var self = this;
                var server_url = self.get_settings().server_url || 'http://localhost:8000';

                // Добавляем вкладку в меню настроек
                if (this.system().area === 'settings' || this.system().area === 'advanced_settings') {
                    var $container = $('.widget_settings_block__descr');

                    // Создаем iframe с дашбордом
                    var iframe_html = '<div style="width: 100%; height: 800px; margin-top: 20px;">' +
                        '<h2 style="margin-bottom: 15px;">📊 Дашборд Команды Продаж</h2>' +
                        '<iframe src="' + server_url + '/admin/" ' +
                        'style="width: 100%; height: 750px; border: 1px solid #ddd; border-radius: 4px;">' +
                        '</iframe>' +
                        '</div>';

                    $container.append(iframe_html);
                }

                return true;
            },
            destroy: function() {
                // Очистка при удалении
            }
        };
        return this;
    };

    return CustomWidget;
});
EOF
```

### Шаг 5: Создать style.css

```bash
cat > style.css << 'EOF'
.salesbot-dashboard-widget {
    width: 100%;
    min-height: 600px;
}

.salesbot-dashboard-widget iframe {
    border: none;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.salesbot-widget-header {
    padding: 15px;
    background: #f8f9fa;
    border-bottom: 1px solid #dee2e6;
    font-weight: 600;
}
EOF
```

### Шаг 6: Упаковать виджет

```bash
cd /root/salesbot-mvp
zip -r salesbot-widget.zip widget/
```

---

## 📥 Установка виджета в AmoCRM

### Шаг 1: Открыть настройки AmoCRM

1. Зайдите в AmoCRM: https://sovanidirektor.amocrm.ru
2. Перейдите в **Настройки** → **Интеграции** → **Виджеты**
3. Нажмите **Установить виджет**

### Шаг 2: Загрузить ZIP

1. Выберите **Установить свой виджет**
2. Загрузите файл `salesbot-widget.zip`
3. Нажмите **Установить**

### Шаг 3: Настроить виджет

1. После установки откроется окно настроек
2. В поле **URL сервера** введите:
   ```
   http://ВНЕШНИЙ_IP_СЕРВЕРА:8000
   ```
   Или если есть домен:
   ```
   https://app.justbusiness.lol
   ```
3. Сохраните настройки

### Шаг 4: Открыть дашборд

1. Перейдите в **Настройки** → **Расширенные настройки**
2. Вы увидите встроенный дашборд с метриками команды!

---

## 🌐 Метод 2: Внешний доступ через iframe

Если виджет не подходит, можно просто добавить закладку или настроить прямой доступ.

### Вариант A: Через внешний IP

```bash
# Узнать внешний IP сервера
curl ifconfig.me

# Открыть в браузере:
http://ВАШ_IP:8000/admin/
```

### Вариант B: Настроить домен и HTTPS

Создайте nginx конфигурацию:

```bash
sudo nano /etc/nginx/sites-available/salesbot
```

```nginx
server {
    listen 80;
    server_name dashboard.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Активировать:
```bash
sudo ln -s /etc/nginx/sites-available/salesbot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Настроить SSL
sudo certbot --nginx -d dashboard.yourdomain.com
```

Теперь доступ по: `https://dashboard.yourdomain.com/admin/`

---

## 🔒 Добавить аутентификацию (опционально)

Если хотите защитить дашборд паролем:

### Шаг 1: Создать файл с паролями

```bash
sudo apt-get install apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd admin
# Введите пароль
```

### Шаг 2: Обновить nginx конфиг

```nginx
location /admin/ {
    auth_basic "SalesBot Dashboard";
    auth_basic_user_file /etc/nginx/.htpasswd;

    proxy_pass http://127.0.0.1:8000;
    # ... остальные настройки
}
```

---

## 📱 Альтернатива: Встроить в AmoCRM через Custom Fields

### Использовать поле типа "Текст" с HTML

1. В AmoCRM создайте кастомное поле типа "Текст"
2. В скрипте виджета добавьте HTML с iframe:

```javascript
var iframe_code = '<iframe src="http://your-server:8000/admin/" width="100%" height="600px"></iframe>';
// Вставить в кастомное поле
```

---

## 🎨 Кастомизация дашборда для AmoCRM

Если нужно изменить внешний вид под AmoCRM:

```bash
# Создать отдельный роутер для AmoCRM
nano /root/salesbot-mvp/app/web/routers/amocrm_dashboard.py
```

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/amocrm", tags=["AmoCRM Dashboard"])
templates = Jinja2Templates(directory="app/web/templates")

@router.get("/dashboard", response_class=HTMLResponse)
async def amocrm_dashboard(request: Request):
    """Дашборд оптимизированный для встраивания в AmoCRM"""
    # Убрать header, footer для чистого iframe
    return templates.TemplateResponse(
        "amocrm_dashboard.html",
        {"request": request, "embed_mode": True}
    )
```

Добавить в main.py:
```python
from .web.routers.amocrm_dashboard import router as amocrm_router
app.include_router(amocrm_router)
```

Теперь используйте: `http://server:8000/amocrm/dashboard`

---

## ✅ Проверка работы

### Тест 1: Прямой доступ
```bash
curl http://localhost:8000/admin/ | head -20
```

### Тест 2: Из браузера
Откройте: `http://ВАШ_СЕРВЕР:8000/admin/`

### Тест 3: В iframe
Создайте test.html:
```html
<!DOCTYPE html>
<html>
<head><title>Test Dashboard</title></head>
<body>
    <h1>Test Embed</h1>
    <iframe src="http://ВАШ_СЕРВЕР:8000/admin/"
            width="100%" height="800px"
            style="border: 1px solid #ccc;">
    </iframe>
</body>
</html>
```

---

## 🔧 Troubleshooting

### Проблема: CORS ошибка в iframe

Добавьте в main.py:
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://sovanidirektor.amocrm.ru"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Проблема: X-Frame-Options блокирует iframe

Добавьте middleware:
```python
@app.middleware("http")
async def remove_x_frame_options(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "ALLOWALL"
    return response
```

---

## 📊 Итог

После настройки вы получите:

✅ **Встроенный дашборд** прямо в AmoCRM
✅ **Метрики команды** в реальном времени
✅ **Автообновление** каждые 30 секунд
✅ **Доступ из любого места** AmoCRM

**Рекомендуемый путь:**
1. Сначала протестируйте прямой доступ: `http://server:8000/admin/`
2. Настройте домен с HTTPS
3. Создайте приватный виджет для AmoCRM
4. При необходимости опубликуйте в Marketplace

---

📝 **Следующий шаг:** Протестируйте доступ и настройте виджет!
