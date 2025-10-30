# AmoCRM Интеграция - Пуш-уведомления и Виджеты

## Обзор Возможностей AmoCRM API v4

### 1. Методы "Пуш-уведомлений" в AmoCRM

AmoCRM не имеет классических push notifications, но есть 4 способа показать информацию менеджеру:

#### ✅ Способ 1: Примечания (Notes) - САМОЕ ПРОСТОЕ
**Что это:** Заметки в карточке сделки/контакта
**Сложность:** Очень низкая (1 день)
**Видимость:** Средняя (менеджер должен открыть карточку)

```python
# Пример использования
await amocrm_client.update_lead_note(
    lead_id="12345",
    note_text="""
🤖 AI АНАЛИЗ ЗВОНКА - 24.10.2025 15:30

📊 Оценка качества: 8.2/10

✅ Что хорошо:
• Отлично выявил потребности клиента
• Профессиональный тон
• Четкое следование скрипту

⚠️ Что улучшить:
• Слишком быстро согласился на скидку 15%
• Не использовал технику работы с возражениями
• Не зафиксировал конкретную дату следующего контакта

💡 Рекомендации:
1. Изучить технику "Понимаю вас, и..."
2. Всегда фиксировать следующий шаг с датой
3. Скидки давать только после обоснования ценности

🎯 Следующий шаг: Позвонить 25.10 до 12:00
    """
)
```

**Плюсы:**
- Просто реализовать
- Вся история в карточке
- Руководитель видит все AI анализы

**Минусы:**
- Менеджер не получает активное уведомление
- Нужно открыть карточку

---

#### ✅ Способ 2: Задачи (Tasks) - ОЧЕНЬ ЭФФЕКТИВНО
**Что это:** Создание задач менеджеру
**Сложность:** Низкая (1-2 дня)
**Видимость:** Высокая (задачи видны везде + уведомления)

```python
# app/amocrm/smart_tasks.py

class SmartTaskCreator:
    """Создает умные задачи на основе AI рекомендаций"""

    async def create_ai_task(self, deal_id: int, recommendation: Dict):
        """Создать задачу из AI рекомендации"""

        # Определить тип задачи
        task_type_id = self._get_task_type(recommendation['action'])

        # Определить дедлайн на основе urgency
        if recommendation['urgency'] == 'immediate':
            deadline = datetime.now() + timedelta(hours=2)
        elif recommendation['urgency'] == 'this_week':
            deadline = datetime.now() + timedelta(days=1)
        else:
            deadline = datetime.now() + timedelta(days=7)

        # Текст задачи
        task_text = f"""
🤖 AI РЕКОМЕНДАЦИЯ

{recommendation['action']}

Почему это важно:
{recommendation['why']}

Как выполнить:
{recommendation.get('how', 'См. детали в Telegram')}

Сделка: {recommendation['deal_name']}
Бюджет: {recommendation['budget']:,.0f} ₽
Приоритет: {recommendation['priority'].upper()}
        """

        # Создать задачу в AmoCRM
        result = await amocrm_client.add_task(
            responsible_user_id=deal['responsible_user_id'],
            text=task_text,
            complete_till=deadline,
            entity_id=deal_id,
            entity_type='leads'
        )

        return result

# Пример использования
recommendations = analysis['recommendations']['recommendations']
for rec in recommendations[:3]:  # Топ-3 рекомендации
    await smart_task_creator.create_ai_task(deal_id, rec)
```

**AmoCRM API endpoint:**
```
POST https://subdomain.amocrm.ru/api/v4/tasks

Body:
[
  {
    "task_type_id": 1,  // 1 = Звонок, 2 = Встреча, 3 = Написать
    "text": "Задача с AI рекомендацией",
    "complete_till": 1698156000,  // Unix timestamp
    "entity_id": 12345,
    "entity_type": "leads",
    "responsible_user_id": 456
  }
]
```

**Плюсы:**
- Менеджер получает уведомление
- Видно в списке задач
- Можно установить дедлайн
- Автоматические напоминания AmoCRM

**Минусы:**
- Ограниченное форматирование текста
- Нельзя добавить кнопки действий

---

#### ✅ Способ 3: Теги (Tags) - ДЛЯ СЕГМЕНТАЦИИ
**Что это:** Автоматическая установка тегов на сделки
**Сложность:** Низкая (1 день)
**Видимость:** Высокая (теги видны везде)

```python
# app/amocrm/auto_tagging.py

class AutoTagger:
    """Автоматически проставляет теги на основе AI анализа"""

    async def tag_deal_by_ai_analysis(self, deal_id: int, analysis: Dict):
        """Проставить теги на основе анализа"""

        tags_to_add = []

        # Тег вероятности
        probability = analysis['recommendations']['estimated_conversion_probability']
        if probability >= 70:
            tags_to_add.append('🔥 Горячая')
        elif probability >= 40:
            tags_to_add.append('🌡 Теплая')
        else:
            tags_to_add.append('❄️ Холодная')

        # Тег приоритета
        priority = analysis['recommendations']['priority']
        if priority == 'high':
            tags_to_add.append('⚠️ Требует внимания')

        # Тег по активности
        days_idle = analysis['metrics']['days_since_last_update']
        if days_idle >= 7:
            tags_to_add.append('😴 Спящая')
        elif days_idle >= 3:
            tags_to_add.append('⏰ Давно без контакта')

        # Тег качества работы
        if 'call_quality_score' in analysis:
            score = analysis['call_quality_score']
            if score >= 8:
                tags_to_add.append('✅ Отличная работа')
            elif score < 5:
                tags_to_add.append('⚠️ Проблемы качества')

        # Проставить теги в AmoCRM
        await self._update_lead_tags(deal_id, tags_to_add)

    async def _update_lead_tags(self, lead_id: int, tags: List[str]):
        """Обновить теги сделки"""
        # AmoCRM API для обновления тегов
        data = {
            "_embedded": {
                "tags": [{"name": tag} for tag in tags]
            }
        }

        await amocrm_client._make_request(
            "PATCH",
            f"leads/{lead_id}",
            data=[data]
        )
```

**Применение:**
- Автофильтрация по тегам в AmoCRM
- Визуальные индикаторы состояния
- Триггеры для автоматизаций

**Плюсы:**
- Быстрая визуальная индикация
- Удобная фильтрация
- Можно настроить автоматизации AmoCRM по тегам

**Минусы:**
- Не показывает детали
- Слишком много тегов = визуальный шум

---

#### ✅ Способ 4: Кастомные Поля (Custom Fields) - ДЛЯ ДАННЫХ
**Что это:** Дополнительные поля в карточке сделки
**Сложность:** Низкая (1-2 дня)
**Видимость:** Высокая (всегда видно в карточке)

```python
# app/amocrm/custom_fields.py

class CustomFieldsManager:
    """Управление кастомными полями"""

    # Создать поля при установке (делается один раз)
    CUSTOM_FIELDS = {
        'ai_conversion_probability': {
            'name': '🤖 AI: Вероятность закрытия',
            'type': 'numeric',
            'code': 'AI_CONVERSION_PROB'
        },
        'ai_quality_score': {
            'name': '📊 AI: Качество звонков',
            'type': 'numeric',
            'code': 'AI_QUALITY_SCORE'
        },
        'ai_last_analysis': {
            'name': '🕐 AI: Последний анализ',
            'type': 'date_time',
            'code': 'AI_LAST_ANALYSIS'
        },
        'ai_next_action': {
            'name': '💡 AI: Рекомендация',
            'type': 'text',
            'code': 'AI_NEXT_ACTION'
        },
        'best_call_time': {
            'name': '📞 Лучшее время звонка',
            'type': 'text',
            'code': 'BEST_CALL_TIME'
        }
    }

    async def create_custom_fields(self):
        """Создать кастомные поля (один раз при установке)"""
        for field_code, field_config in self.CUSTOM_FIELDS.items():
            await amocrm_client._make_request(
                'POST',
                'leads/custom_fields',
                data=[{
                    'name': field_config['name'],
                    'type': field_config['type'],
                    'code': field_config['code']
                }]
            )

    async def update_ai_fields(self, deal_id: int, analysis: Dict):
        """Обновить AI поля в сделке"""

        field_updates = {
            'AI_CONVERSION_PROB': analysis['recommendations']['estimated_conversion_probability'],
            'AI_QUALITY_SCORE': analysis.get('call_quality_score', 0),
            'AI_LAST_ANALYSIS': int(datetime.now().timestamp()),
            'AI_NEXT_ACTION': analysis['recommendations']['recommendations'][0]['action']
        }

        # Получить ID полей
        fields = await self._get_field_ids()

        # Сформировать обновление
        custom_fields_values = [
            {
                'field_id': fields[code],
                'values': [{'value': value}]
            }
            for code, value in field_updates.items()
        ]

        # Обновить сделку
        await amocrm_client._make_request(
            'PATCH',
            f'leads/{deal_id}',
            data=[{
                'id': deal_id,
                'custom_fields_values': custom_fields_values
            }]
        )
```

**Пример отображения в AmoCRM:**
```
┌─────────────────────────────────────────┐
│ Сделка: ООО "Рога и Копыта"            │
├─────────────────────────────────────────┤
│ Бюджет: 450,000 ₽                      │
│ Ответственный: Иванов И.И.             │
│                                         │
│ 🤖 AI: Вероятность закрытия: 73%       │
│ 📊 AI: Качество звонков: 8.2/10        │
│ 🕐 AI: Последний анализ: 24.10 15:30   │
│ 💡 AI: Рекомендация: Позвонить сегодня │
│ 📞 Лучшее время: Вт-Чт 10:00-12:00     │
└─────────────────────────────────────────┘
```

**Плюсы:**
- Всегда видно в карточке
- Структурированные данные
- Можно использовать в фильтрах и отчетах

**Минусы:**
- Статичные данные (нет интерактива)
- Ограниченное форматирование

---

#### ⭐ Способ 5: Виджеты (Widgets) - САМОЕ МОЩНОЕ
**Что это:** Интерактивный блок в карточке сделки
**Сложность:** Высокая (5-7 дней)
**Видимость:** Максимальная (интерактивный UI)

### Полная Реализация AmoCRM Виджета

#### Шаг 1: Структура проекта виджета

```
salesbot-widget/
├── manifest.json           # Манифест виджета
├── widget.php             # Точка входа
├── i18n/
│   └── ru.json            # Переводы
├── templates/
│   ├── settings.twig      # Настройки виджета
│   └── advanced.twig      # Расширенные настройки
├── js/
│   ├── script.js          # Основная логика
│   └── i18n/
│       └── ru.js          # Переводы JS
├── css/
│   └── style.css          # Стили
└── images/
    ├── logo.svg           # Иконка виджета
    └── icon.png           # Иконка в маркетплейсе
```

#### Шаг 2: manifest.json

```json
{
    "widget": {
        "name": "widget.name",
        "description": "widget.description",
        "short_description": "widget.short_description",
        "version": "1.0.0",
        "init_once": false,
        "locale": ["ru", "en"],
        "installation": true,
        "support": {
            "link": "https://app.justbusiness.lol/support",
            "email": "support@justbusiness.lol"
        }
    },
    "locations": [
        "lcard-1",      // Карточка сделки - правая панель
        "comcard-1",    // Карточка компании
        "ccard-1",      // Карточка контакта
        "llist-1",      // Список сделок
        "settings"      // Настройки
    ],
    "settings": {
        "login": {
            "name": "settings.login",
            "type": "text"
        },
        "api_key": {
            "name": "settings.api_key",
            "type": "pass"
        },
        "api_url": {
            "name": "settings.api_url",
            "type": "text",
            "default": "https://app.justbusiness.lol/salesbot/api"
        },
        "enable_auto_tasks": {
            "name": "settings.enable_auto_tasks",
            "type": "checkbox"
        },
        "analysis_interval": {
            "name": "settings.analysis_interval",
            "type": "select",
            "values": [
                {"1": "Ежедневно"},
                {"3": "Каждые 3 дня"},
                {"7": "Еженедельно"}
            ]
        }
    },
    "sources": {
        "path": {
            "js": "/js/script.js",
            "css": "/css/style.css",
            "i18n": "/js/i18n"
        }
    }
}
```

#### Шаг 3: i18n/ru.json

```json
{
    "widget": {
        "name": "SalesBot AI Assistant",
        "description": "AI-ассистент для анализа сделок и коучинга менеджеров",
        "short_description": "AI анализ сделок"
    },
    "settings": {
        "login": "Email",
        "api_key": "API ключ",
        "api_url": "URL API",
        "enable_auto_tasks": "Автоматически создавать задачи",
        "analysis_interval": "Частота автоанализа"
    },
    "labels": {
        "analyze_now": "🔄 Анализировать сейчас",
        "conversion_probability": "Вероятность закрытия",
        "recommendations": "Рекомендации",
        "metrics": "Метрики",
        "last_update": "Обновлено",
        "apply": "Применить",
        "create_task": "Создать задачу",
        "add_note": "Добавить заметку"
    }
}
```

#### Шаг 4: js/script.js (полная версия)

```javascript
define(['jquery', 'lib/components/base/modal'], function($, Modal) {
    var CustomWidget = function() {
        var self = this;

        // Настройки из AmoCRM
        this.settings = {};
        this.apiUrl = '';
        this.apiKey = '';

        // Callbacks виджета
        this.callbacks = {
            // Загрузка настроек
            settings: function($modal_body) {
                console.log('Widget settings loaded');
                return true;
            },

            // Инициализация виджета
            init: function() {
                console.log('Widget initialized');

                // Получить настройки
                self.settings = self.get_settings();
                self.apiUrl = self.settings.api_url || 'https://app.justbusiness.lol/salesbot/api';
                self.apiKey = self.settings.api_key;

                return true;
            },

            // Привязка действий
            bind_actions: function() {
                console.log('Binding actions');

                // Кнопка "Анализировать"
                $(document).on('click', '.salesbot-analyze-btn', function() {
                    self.analyzeCurrentDeal();
                });

                // Кнопка "Создать задачу"
                $(document).on('click', '.salesbot-create-task', function() {
                    var action = $(this).data('action');
                    var why = $(this).data('why');
                    self.createTaskFromRecommendation(action, why);
                });

                // Кнопка "Показать лучшее время"
                $(document).on('click', '.salesbot-best-time', function() {
                    self.showBestCallTime();
                });

                // Кнопка "Добавить заметку"
                $(document).on('click', '.salesbot-add-note', function() {
                    var text = $(this).data('note-text');
                    self.add_note(text);
                });

                return true;
            },

            // Рендеринг виджета
            render: function() {
                console.log('Rendering widget', self.params);

                // Определить где мы
                var location = self.params.location || self.params.page;

                if (location === 'lcard' || location === 'lcard-1') {
                    // Карточка сделки
                    self.renderDealCard();
                } else if (location === 'llist' || location === 'llist-1') {
                    // Список сделок
                    self.renderDealsList();
                }

                return true;
            },

            // Деинициализация
            destroy: function() {
                console.log('Widget destroyed');
            },

            // Обработка контактов
            contacts: {
                selected: function() {
                    console.log('Contacts selected', arguments);
                }
            },

            // Обработка сделок
            leads: {
                selected: function() {
                    console.log('Leads selected', arguments);
                }
            },

            // Продвинутые настройки
            advancedSettings: function() {
                console.log('Advanced settings');
                return true;
            },

            // Деинсталляция
            onSave: function() {
                console.log('Widget settings saved');
                return true;
            }
        };

        // МЕТОДЫ ВИДЖЕТА

        /**
         * Рендер виджета в карточке сделки
         */
        this.renderDealCard = function() {
            var leadId = self.params.lead_id || self.params.leads[0];

            if (!leadId) {
                self.render_error('Не удалось получить ID сделки');
                return;
            }

            // Показать лоадер
            self.render_loader();

            // Запросить данные
            self.fetchWidgetData(leadId, function(data) {
                if (data.error) {
                    self.render_error(data.error);
                    return;
                }

                self.renderWidgetUI(data);
            });
        };

        /**
         * Запросить данные для виджета
         */
        this.fetchWidgetData = function(leadId, callback) {
            $.ajax({
                url: self.apiUrl + '/deals/' + leadId + '/widget-data',
                method: 'GET',
                headers: {
                    'Authorization': 'Bearer ' + self.apiKey
                },
                success: function(data) {
                    callback(data);
                },
                error: function(xhr) {
                    callback({
                        error: 'Ошибка загрузки данных: ' + xhr.statusText
                    });
                }
            });
        };

        /**
         * Отрисовать UI виджета
         */
        this.renderWidgetUI = function(data) {
            var priorityClass = {
                'high': 'salesbot-high',
                'medium': 'salesbot-medium',
                'low': 'salesbot-low'
            }[data.priority] || 'salesbot-medium';

            var html = `
                <div class="salesbot-widget">
                    <div class="salesbot-header">
                        <img src="${self.params.path}/images/logo.svg" class="salesbot-logo">
                        <h3>AI Sales Coach</h3>
                    </div>

                    <div class="salesbot-score ${priorityClass}">
                        <div class="score-circle">
                            <span class="score-value">${data.conversion_probability}%</span>
                        </div>
                        <span class="score-label">Вероятность закрытия</span>
                    </div>

                    <div class="salesbot-section">
                        <h4>🎯 Рекомендации</h4>
                        ${self.renderRecommendations(data.recommendations)}
                    </div>

                    <div class="salesbot-metrics">
                        <div class="metric">
                            <span class="metric-value">${data.metrics.days_idle}</span>
                            <span class="metric-label">дней без активности</span>
                        </div>
                        <div class="metric">
                            <span class="metric-value">${data.metrics.calls_count}</span>
                            <span class="metric-label">звонков</span>
                        </div>
                    </div>

                    <div class="salesbot-actions">
                        <button class="salesbot-analyze-btn salesbot-btn salesbot-btn-primary">
                            🔄 Обновить анализ
                        </button>
                        <button class="salesbot-best-time salesbot-btn salesbot-btn-secondary">
                            📞 Лучшее время
                        </button>
                    </div>

                    <div class="salesbot-footer">
                        <small>Обновлено: ${data.updated_at}</small>
                    </div>
                </div>
            `;

            // Вставить в виджет
            self.render_template({
                caption: '',
                body: html
            });
        };

        /**
         * Отрисовать рекомендации
         */
        this.renderRecommendations = function(recommendations) {
            if (!recommendations || recommendations.length === 0) {
                return '<p class="salesbot-no-data">Нет рекомендаций</p>';
            }

            var html = '';
            recommendations.slice(0, 3).forEach(function(rec) {
                var urgencyIcon = {
                    'immediate': '🔥',
                    'this_week': '⏰',
                    'planned': '📅'
                }[rec.urgency] || '💡';

                html += `
                    <div class="salesbot-recommendation salesbot-urgency-${rec.urgency}">
                        <p class="rec-header">${urgencyIcon} <strong>${rec.action}</strong></p>
                        <p class="rec-why">${rec.why}</p>
                        <div class="rec-actions">
                            <button class="salesbot-create-task salesbot-btn-sm"
                                    data-action="${rec.action}"
                                    data-why="${rec.why}">
                                Создать задачу
                            </button>
                            <button class="salesbot-add-note salesbot-btn-sm"
                                    data-note-text="${rec.action}: ${rec.why}">
                                Заметка
                            </button>
                        </div>
                    </div>
                `;
            });

            return html;
        };

        /**
         * Показать лоадер
         */
        this.render_loader = function() {
            self.render_template({
                caption: '',
                body: '<div class="salesbot-loader">⏳ Загрузка...</div>'
            });
        };

        /**
         * Показать ошибку
         */
        this.render_error = function(message) {
            self.render_template({
                caption: 'Ошибка',
                body: '<div class="salesbot-error">⚠️ ' + message + '</div>'
            });
        };

        /**
         * Анализировать текущую сделку
         */
        this.analyzeCurrentDeal = function() {
            var leadId = self.params.lead_id || self.params.leads[0];

            // Показать процесс
            $('.salesbot-analyze-btn').html('⏳ Анализирую...').prop('disabled', true);

            $.ajax({
                url: self.apiUrl + '/deals/' + leadId + '/analyze',
                method: 'POST',
                headers: {
                    'Authorization': 'Bearer ' + self.apiKey
                },
                success: function() {
                    // Показать уведомление
                    self.crm_notification('Анализ запущен! Результат придет в Telegram через 30 сек.');

                    // Обновить виджет через 5 сек
                    setTimeout(function() {
                        self.callbacks.render();
                    }, 5000);
                },
                error: function(xhr) {
                    self.crm_notification('Ошибка: ' + xhr.statusText, 'error');
                    $('.salesbot-analyze-btn').html('🔄 Обновить анализ').prop('disabled', false);
                }
            });
        };

        /**
         * Создать задачу из рекомендации
         */
        this.createTaskFromRecommendation = function(action, why) {
            var leadId = self.params.lead_id || self.params.leads[0];

            // Текст задачи
            var taskText = '🤖 AI Рекомендация\n\n' + action + '\n\nПочему: ' + why;

            // Создать задачу через AmoCRM API
            self.add_task({
                element_id: parseInt(leadId),
                element_type: 2,  // Сделка
                task_type: 1,     // Звонок
                text: taskText,
                complete_till: Math.floor(Date.now() / 1000) + 86400  // Завтра
            });

            self.crm_notification('Задача создана!');
        };

        /**
         * Показать лучшее время для звонка
         */
        this.showBestCallTime = function() {
            var leadId = self.params.lead_id || self.params.leads[0];

            $.ajax({
                url: self.apiUrl + '/deals/' + leadId + '/best-time',
                method: 'GET',
                headers: {
                    'Authorization': 'Bearer ' + self.apiKey
                },
                success: function(data) {
                    // Показать модальное окно
                    var modal = new Modal({
                        class_name: 'salesbot-best-time-modal',
                        init: function($modal_body) {
                            var html = `
                                <h3>📞 Оптимальное время для звонка</h3>
                                <div class="salesbot-best-time-content">
                                    <div class="best-time-card">
                                        <h4>Рекомендуемое время:</h4>
                                        <p class="best-time-value">${data.best_day_of_week}</p>
                                        <p class="best-time-value">${data.best_time_range}</p>
                                    </div>
                                    <div class="best-time-details">
                                        <p><strong>Избегать:</strong> ${data.worst_time}</p>
                                        <p><strong>Ответ на звонок:</strong> ${(data.answer_rate * 100).toFixed(0)}%</p>
                                    </div>
                                    <button class="salesbot-btn salesbot-btn-primary" onclick="createTaskBestTime()">
                                        Создать задачу на это время
                                    </button>
                                </div>
                            `;

                            $modal_body.html(html);

                            // Функция создания задачи
                            window.createTaskBestTime = function() {
                                var taskText = 'Позвонить клиенту\n\nЛучшее время: ' +
                                               data.best_day_of_week + ' ' + data.best_time_range;

                                self.add_task({
                                    element_id: parseInt(leadId),
                                    element_type: 2,
                                    task_type: 1,
                                    text: taskText,
                                    complete_till: self.getNextTimestamp(data.best_day_of_week, data.best_time_range)
                                });

                                modal.destroy();
                                self.crm_notification('Задача создана на оптимальное время!');
                            };

                            return true;
                        },
                        destroy: function() {}
                    });
                },
                error: function() {
                    self.crm_notification('Недостаточно данных для определения лучшего времени', 'error');
                }
            });
        };

        /**
         * Получить timestamp следующего оптимального времени
         */
        this.getNextTimestamp = function(day, timeRange) {
            // Упрощенная версия - завтра в 10:00
            var tomorrow = new Date();
            tomorrow.setDate(tomorrow.getDate() + 1);
            tomorrow.setHours(10, 0, 0, 0);
            return Math.floor(tomorrow.getTime() / 1000);
        };

        /**
         * Показать CRM уведомление
         */
        this.crm_notification = function(message, type) {
            type = type || 'success';

            if (typeof AMOCRM !== 'undefined' && AMOCRM.notifications) {
                AMOCRM.notifications.show_message({
                    header: 'SalesBot AI',
                    text: message,
                    date: Math.floor(Date.now() / 1000),
                    type: type
                });
            } else {
                alert(message);
            }
        };

        return this;
    };

    return CustomWidget;
});
```

#### Шаг 5: css/style.css

```css
/* Основные стили виджета */
.salesbot-widget {
    padding: 15px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}

.salesbot-header {
    display: flex;
    align-items: center;
    margin-bottom: 20px;
    padding-bottom: 15px;
    border-bottom: 2px solid #f0f0f0;
}

.salesbot-logo {
    width: 32px;
    height: 32px;
    margin-right: 12px;
}

.salesbot-header h3 {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
    color: #333;
}

/* Вероятность закрытия */
.salesbot-score {
    text-align: center;
    margin: 25px 0;
    padding: 20px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border-radius: 12px;
    color: white;
}

.salesbot-score.salesbot-high {
    background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
}

.salesbot-score.salesbot-medium {
    background: linear-gradient(135deg, #ee0979 0%, #ff6a00 100%);
}

.salesbot-score.salesbot-low {
    background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
}

.score-circle {
    margin-bottom: 10px;
}

.score-value {
    display: block;
    font-size: 42px;
    font-weight: bold;
    line-height: 1;
}

.score-label {
    font-size: 13px;
    opacity: 0.9;
}

/* Секции */
.salesbot-section {
    margin: 20px 0;
}

.salesbot-section h4 {
    margin: 0 0 12px 0;
    font-size: 14px;
    font-weight: 600;
    color: #555;
}

/* Рекомендации */
.salesbot-recommendation {
    background: #f8f9fa;
    padding: 12px;
    margin-bottom: 10px;
    border-radius: 8px;
    border-left: 4px solid #667eea;
}

.salesbot-recommendation.salesbot-urgency-immediate {
    border-left-color: #f5576c;
    background: #fff5f7;
}

.salesbot-recommendation.salesbot-urgency-this_week {
    border-left-color: #ffa726;
    background: #fff8f0;
}

.rec-header {
    margin: 0 0 8px 0;
    font-size: 14px;
}

.rec-header strong {
    color: #333;
}

.rec-why {
    margin: 0 0 10px 0;
    font-size: 12px;
    color: #666;
    line-height: 1.5;
}

.rec-actions {
    display: flex;
    gap: 8px;
}

/* Метрики */
.salesbot-metrics {
    display: flex;
    justify-content: space-around;
    margin: 20px 0;
    padding: 15px;
    background: #f8f9fa;
    border-radius: 8px;
}

.metric {
    text-align: center;
}

.metric-value {
    display: block;
    font-size: 28px;
    font-weight: bold;
    color: #667eea;
    line-height: 1;
}

.metric-label {
    display: block;
    font-size: 11px;
    color: #888;
    margin-top: 5px;
}

/* Кнопки */
.salesbot-btn {
    padding: 10px 16px;
    border: none;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s;
}

.salesbot-btn-primary {
    background: #667eea;
    color: white;
}

.salesbot-btn-primary:hover {
    background: #5568d3;
}

.salesbot-btn-secondary {
    background: #f0f0f0;
    color: #333;
}

.salesbot-btn-secondary:hover {
    background: #e0e0e0;
}

.salesbot-btn-sm {
    padding: 6px 12px;
    font-size: 11px;
}

.salesbot-actions {
    display: flex;
    gap: 10px;
    margin: 20px 0;
}

.salesbot-actions .salesbot-btn {
    flex: 1;
}

/* Footer */
.salesbot-footer {
    margin-top: 20px;
    padding-top: 15px;
    border-top: 1px solid #f0f0f0;
    text-align: center;
}

.salesbot-footer small {
    color: #999;
    font-size: 11px;
}

/* Loader */
.salesbot-loader {
    text-align: center;
    padding: 40px 20px;
    font-size: 16px;
    color: #666;
}

/* Error */
.salesbot-error {
    text-align: center;
    padding: 20px;
    background: #fff5f5;
    border: 1px solid #ffebee;
    border-radius: 8px;
    color: #c62828;
}

/* Модальное окно лучшего времени */
.salesbot-best-time-modal .best-time-card {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 20px;
    border-radius: 12px;
    text-align: center;
    margin-bottom: 20px;
}

.best-time-value {
    font-size: 24px;
    font-weight: bold;
    margin: 10px 0;
}

.best-time-details {
    margin: 15px 0;
}

.salesbot-no-data {
    text-align: center;
    color: #999;
    padding: 20px;
    font-style: italic;
}
```

---

## Backend API Endpoints для Виджета

```python
# app/main.py - добавить endpoints

@app.get("/api/deals/{deal_id}/widget-data")
async def get_widget_data(
    deal_id: int,
    authorization: str = Header(None)
):
    """Данные для AmoCRM виджета"""

    # Проверка API ключа
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, "Missing or invalid authorization header")

    api_key = authorization.replace('Bearer ', '')
    settings = get_settings()

    if api_key != settings.widget_api_key:
        raise HTTPException(401, "Invalid API key")

    try:
        # Получить кэшированный анализ
        from .analysis.deal_analyzer import deal_analyzer

        analysis = await deal_analyzer.get_cached_analysis(deal_id)

        if not analysis:
            # Быстрый анализ без уведомлений
            analysis = await deal_analyzer.analyze_deal_comprehensive(deal_id)

        # Форматировать для виджета
        return {
            'conversion_probability': analysis['recommendations'].get('estimated_conversion_probability', 50),
            'priority': analysis['recommendations'].get('priority', 'medium'),
            'recommendations': [
                {
                    'action': rec['action'],
                    'why': rec['why'],
                    'urgency': rec.get('urgency', 'planned')
                }
                for rec in analysis['recommendations']['recommendations'][:3]
            ],
            'metrics': {
                'days_idle': analysis['metrics']['days_since_last_update'],
                'calls_count': analysis['metrics']['total_calls']
            },
            'updated_at': datetime.now().strftime('%d.%m %H:%M')
        }

    except Exception as e:
        logger.error(f"Widget data error: {e}", deal_id=deal_id)
        raise HTTPException(500, f"Failed to get widget data: {str(e)}")


@app.get("/api/deals/{deal_id}/best-time")
async def get_best_call_time(
    deal_id: int,
    authorization: str = Header(None)
):
    """Получить оптимальное время для звонка"""

    # Проверка авторизации (аналогично)
    ...

    try:
        from .analysis.timing_optimizer import timing_optimizer

        timing = await timing_optimizer.analyze_client_patterns(deal_id)

        return {
            'best_day_of_week': timing['best_day_of_week'],
            'best_time_range': timing['best_time_range'],
            'worst_time': timing['worst_time'],
            'answer_rate': timing['answer_rate']
        }

    except Exception as e:
        raise HTTPException(500, str(e))
```

---

## Деплой Виджета

### 1. Упаковка виджета

```bash
cd salesbot-widget
zip -r salesbot-widget.zip *
```

### 2. Установка в AmoCRM

1. Зайти в настройки AmoCRM → Интеграции → Создать интеграцию
2. Выбрать "Виджет"
3. Загрузить ZIP файл
4. Настроить доступы
5. Установить виджет в аккаунт

### 3. Настройка после установки

Менеджер заходит в настройки виджета и вводит:
- API URL: `https://app.justbusiness.lol/salesbot/api`
- API Key: (сгенерировать уникальный)
- Включить автозадачи: ☑
- Интервал анализа: 1 день

---

## Сравнение Всех Методов

| Метод | Сложность | Видимость | Интерактив | Эффект | Рекомендация |
|-------|-----------|-----------|------------|--------|--------------|
| **Заметки** | ⭐ | ⭐⭐ | ❌ | ⭐⭐ | Начать с этого |
| **Задачи** | ⭐ | ⭐⭐⭐ | ❌ | ⭐⭐⭐ | Обязательно |
| **Теги** | ⭐ | ⭐⭐⭐ | ❌ | ⭐⭐ | Для сегментации |
| **Кастомные поля** | ⭐⭐ | ⭐⭐⭐ | ❌ | ⭐⭐ | Для данных |
| **Виджет** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ✅ | ⭐⭐⭐⭐⭐ | Максимум |

---

## Рекомендованная Последовательность

### Неделя 1: Базовая интеграция
1. Авто-заметки после звонков (1 день)
2. Умные автозадачи (1 день)
3. Автотеги по AI анализу (1 день)

**Результат:** Прозрачность 100%, менеджеры видят AI рекомендации

### Неделя 2: Кастомные поля
4. Создать кастомные поля (1 день)
5. Автообновление полей после анализа (1 день)

**Результат:** Структурированные AI данные в каждой сделке

### Неделя 3-4: Виджет
6. Разработка виджета (5-7 дней)
7. Тестирование и деплой

**Результат:** Интерактивный AI прямо в AmoCRM

---

## Резюме

**Самые простые и эффективные методы:**
1. ✅ Автоматические заметки (1 день, высокий эффект)
2. ✅ Умные автозадачи (1 день, высокий эффект)
3. ✅ Теги по AI анализу (1 день, средний эффект)

**Максимальная интеграция:**
4. ⭐ AmoCRM виджет (7 дней, максимальный эффект)

**С чего начать завтра:**
Автоматические заметки + Умные задачи = 2 дня работы, моментальный результат
