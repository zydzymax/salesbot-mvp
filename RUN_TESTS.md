# Запуск Тестов для Новых Модулей

## Быстрый старт

### 1. Установка зависимостей
```bash
cd /root/salesbot-mvp
pip install pytest pytest-asyncio pytest-mock
```

### 2. Запуск тестов

#### Activity Validator (Fraud Detection) - РАБОТАЕТ ✅
```bash
python -m pytest tests/test_activity_validator.py -v
```

**Результат:** 17/20 тестов проходят успешно (85%)

#### Все тесты (с игнорированием импортов)
```bash
python -m pytest tests/test_activity_validator.py -v --tb=short
```

## Структура тестов

```
tests/
├── __init__.py                    # Инициализация
├── conftest.py                    # Общие фикстуры
├── test_call_quality_scorer.py    # 15 тестов для QA Scoring
├── test_commitment_tracker.py     # 20 тестов для Commitment Tracker
├── test_activity_validator.py     # 20 тестов для Fraud Detection ✅
└── test_manager_dashboard.py      # 16 тестов для Manager Dashboard
```

## Что протестировано

### ✅ Activity Validator (Детектор Мертвых Душ)
- [x] Детекция повторных звонков на один номер
- [x] Детекция коротких звонков
- [x] Детекция звонков в нерабочее время
- [x] AI-анализ осмысленности разговоров
- [x] Подозрительные паттерны времени
- [x] Рекомендации по действиям
- [x] Конфигурация порогов

### ⚠️ Call Quality Scorer (Оценка Качества)
- [x] Тесты созданы (15 штук)
- [ ] Требуется исправление циклических импортов

### ⚠️ Commitment Tracker (Обещания)
- [x] Тесты созданы (20 штук)
- [ ] Требуется исправление циклических импортов

### ⚠️ Manager Dashboard (Дашборд)
- [x] Тесты созданы (16 штук)
- [ ] Требуется доработка моков БД

## Известные проблемы

### 1. Циклические импорты
**Проблема:** `app/analysis/__init__.py` создает циклическую зависимость

**Временное решение:**
```bash
# Запускать только тесты, которые не зависят от всего приложения
python -m pytest tests/test_activity_validator.py -v
```

**Постоянное решение:**
Требуется рефакторинг структуры импортов:
1. Использовать lazy imports
2. Разбить большие модули
3. Использовать dependency injection

### 2. Async моки
**Проблема:** Некоторые тесты с AsyncClient требуют корректной настройки

**Решение:**
```bash
pip install respx  # Для мокирования HTTP запросов
```

## Примеры запуска

### Запустить конкретный тест
```bash
python -m pytest tests/test_activity_validator.py::TestActivityValidator::test_check_same_number_repeatedly_normal -v
```

### Запустить с подробным выводом
```bash
python -m pytest tests/test_activity_validator.py -vv -s
```

### Запустить с покрытием
```bash
python -m pytest tests/test_activity_validator.py --cov=app/fraud --cov-report=term-missing
```

## Результаты

### Успешные тесты (Activity Validator)
```
PASSED test_check_same_number_repeatedly_normal
PASSED test_check_same_number_repeatedly_suspicious
PASSED test_check_same_number_repeatedly_no_phones
PASSED test_check_too_many_short_calls_normal
PASSED test_check_too_many_short_calls_suspicious
PASSED test_check_calls_outside_hours_normal
PASSED test_check_calls_outside_hours_suspicious
PASSED test_validate_single_conversation_real
PASSED test_check_suspicious_time_pattern_normal
PASSED test_check_suspicious_time_pattern_suspicious
PASSED test_check_suspicious_time_pattern_too_few_calls
PASSED test_check_activity_without_results_normal
PASSED test_get_recommended_action
PASSED test_thresholds_configuration
PASSED test_check_conversation_validity_no_transcriptions
PASSED test_check_too_many_short_calls_empty_list
```

**17 тестов прошли ✅**

## Следующие шаги

1. **Исправить циклические импорты** в `app/`
   - Рефакторинг `app/analysis/__init__.py`
   - Рефакторинг `app/tasks/__init__.py`

2. **Доработать async моки** для HTTP клиентов
   - Использовать `respx` или правильно настроить `AsyncMock`

3. **Добавить интеграционные тесты**
   - Тесты с реальной тестовой БД
   - E2E тесты полного пайплайна

4. **Настроить CI/CD**
   - Автоматический запуск тестов при коммите
   - Coverage отчеты
   - Качество кода (pylint, mypy)

## Полезные команды

```bash
# Показать список всех тестов
python -m pytest tests/ --collect-only

# Запустить только быстрые тесты
python -m pytest tests/ -m "not slow"

# Остановиться на первой ошибке
python -m pytest tests/ -x

# Показать traceback полностью
python -m pytest tests/ --tb=long

# Запустить в quiet mode
python -m pytest tests/ -q
```

## Контакты

Для вопросов по тестам смотрите `TESTING_REPORT.md`
