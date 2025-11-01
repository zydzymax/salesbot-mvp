## Prompt Analysis & CI

- Системные промпты: app/prompts/system/analysis/*.yml
- Валидация схем: app/llm/validators.py
- Пайплайн анализа: app/analysis/pipeline.py
- Offline eval: eval/*
- CI: Secret scan + Prompt eval

### Локальный запуск eval
bash eval/run_eval.sh

### Внимание по секретам
Секретные файлы (.env, SERVER_INFO.txt) запрещены к коммиту. История очищена. Ротацию ключей выполняем отдельно.
