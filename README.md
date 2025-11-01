# SalesBot MVP

AI-powered sales call analysis system for B2B apparel/knitwear manufacturing (SoVAni).

## Architecture

**Single-model approach:** Uses ChatGPT (gpt-4o) for all analysis.  
No orchestrator needed - one powerful model handles everything in a single pass.

## Prompt Analysis & CI

- Системные промпты: `app/prompts/system/analysis/*.yml`
- Валидация схем: `app/llm/validators.py`
- Пайплайн анализа: `app/analysis/pipeline.py` (прямой вызов OpenAI API)
- Offline eval: `eval/*`
- CI: Secret scan + Prompt eval

### Модель и параметры

- **Модель:** `gpt-4o` (или `gpt-4-turbo`)
- **Temperature:** `0.15` (стабильный reasoning)
- **Top-p:** По умолчанию (0.9-1.0)
- **Max tokens:** `2000`
- **Response format:** `{"type": "json_object"}` (принудительный JSON)

### Почему ChatGPT (одна модель)?

1. **Мощный reasoning:** gpt-4o справляется с комплексным анализом в один проход
2. **Структурированный вывод:** Нативная поддержка `response_format: json_object`
3. **Нет оркестратора:** Проще архитектура, меньше latency
4. **Retry logic:** Встроен в пайплайн на случай невалидного JSON
5. **Consistency checks:** Автоматическая проверка согласованности после валидации

### Локальный запуск eval

```bash
bash eval/run_eval.sh
```

### Внимание по секретам

Секретные файлы (.env, SERVER_INFO.txt) запрещены к коммиту. История очищена. Ротацию ключей выполняем отдельно.

## Usage Example

```python
from app.analysis.pipeline import analyze_dialog

result = await analyze_dialog(
    dialogue_text="MGR: Какой объём?\nCL: 500 худи. Решение у совладельца.",
    api_key="sk-...",
    model="gpt-4o",
    temperature=0.15
)

# result - validated dict with all fields:
# lead_profile, buying_stage, budget, decision_maker, timeline,
# objections, risk_flags, next_actions, scores, evidence_spans, etc.
```

## Post-validation Checks

Пайплайн автоматически проверяет согласованность:

- `buying_stage` ↔ `next_actions` соответствие
- `budget_clarity` score ↔ реальные данные бюджета
- Наличие `evidence_spans` для ключевых полей

При несогласованности выбрасывается `ValueError`.
