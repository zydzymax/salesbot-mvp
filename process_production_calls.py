"""
Обработка реальных звонков из production с фильтрацией и кэшированием
"""
import asyncio
import sys
import json
import sqlite3
from datetime import datetime

sys.path.insert(0, '/root/salesbot-mvp')

from app.config import get_settings
from app.analysis.pipeline import analyze_dialog

# ФИЛЬТРЫ ДЛЯ ИСКЛЮЧЕНИЯ АВТООТВЕТЧИКОВ
MIN_DURATION_SECONDS = 60  # Минимум 1 минута
MIN_TRANSCRIPT_LENGTH = 200  # Минимум 200 символов

# Ключевые слова автоответчиков
AUTORESPONDER_KEYWORDS = [
    "недоступен",
    "не могу ответить",
    "перезвоните позже",
    "оставьте сообщение",
    "голосовая почта",
    "абонент временно недоступен",
    "находится вне зоны действия"
]

def is_autoresponder(transcript: str) -> bool:
    """Проверка на автоответчик"""
    if not transcript:
        return True

    transcript_lower = transcript.lower()
    for keyword in AUTORESPONDER_KEYWORDS:
        if keyword in transcript_lower:
            return True

    return False

async def analyze_call(call_id: str, transcript: str, settings) -> dict:
    """Анализ одного звонка с GPT-5"""
    print(f"\n{'='*80}")
    print(f"Анализ звонка: {call_id}")
    print(f"{'='*80}")

    try:
        result = await analyze_dialog(
            dialogue_text=transcript,
            api_key=settings.openai_api_key,
            model="gpt-5-pro",
            temperature=0.3,
            prompt_version="v2"
        )

        print(f"✅ Анализ завершен успешно!")
        print(f"   Стадия: {result.get('buying_stage')}")
        print(f"   Качество: {result.get('scores', {}).get('overall_quality')}/100")

        return {
            "status": "success",
            "result": result,
            "error": None
        }

    except Exception as e:
        print(f"❌ ОШИБКА: {e}")
        return {
            "status": "error",
            "result": None,
            "error": str(e)
        }

async def main():
    settings = get_settings()
    db = sqlite3.connect('salesbot.db')
    cursor = db.cursor()

    print("="*80)
    print("ОБРАБОТКА PRODUCTION ЗВОНКОВ С ФИЛЬТРАЦИЕЙ")
    print("="*80)

    # ШАБЛОН 1: ФИЛЬТРАЦИЯ
    print(f"\n📋 ФИЛЬТРЫ:")
    print(f"  • Минимальная длительность: {MIN_DURATION_SECONDS} секунд")
    print(f"  • Минимальная длина транскрипции: {MIN_TRANSCRIPT_LENGTH} символов")
    print(f"  • Исключение автоответчиков: {len(AUTORESPONDER_KEYWORDS)} ключевых слов")

    # Получить звонки
    cursor.execute("""
        SELECT id, duration_seconds, transcription_text, amocrm_lead_id
        FROM calls
        WHERE transcription_text IS NOT NULL
          AND transcription_status = 'completed'
          AND analysis_status IN ('pending', 'failed')
        ORDER BY created_at DESC
        LIMIT 5
    """)

    calls = cursor.fetchall()
    print(f"\n📊 Найдено звонков для обработки: {len(calls)}")

    # Фильтрация
    filtered_calls = []
    autoresponders_count = 0
    too_short_count = 0

    for call_id, duration, transcript, lead_id in calls:
        # Фильтр 1: Длительность
        if duration < MIN_DURATION_SECONDS:
            print(f"  ⚠️  {call_id}: Пропущен (слишком короткий: {duration}с)")
            too_short_count += 1
            continue

        # Фильтр 2: Длина транскрипции
        if len(transcript) < MIN_TRANSCRIPT_LENGTH:
            print(f"  ⚠️  {call_id}: Пропущен (короткая транскрипция: {len(transcript)} символов)")
            too_short_count += 1
            continue

        # Фильтр 3: Автоответчик
        if is_autoresponder(transcript):
            print(f"  ⚠️  {call_id}: Пропущен (автоответчик)")
            autoresponders_count += 1
            continue

        filtered_calls.append((call_id, transcript, lead_id))
        print(f"  ✅ {call_id}: Подходит для анализа ({duration}с, {len(transcript)} символов)")

    print(f"\n📊 СТАТИСТИКА ФИЛЬТРАЦИИ:")
    print(f"  • Всего звонков: {len(calls)}")
    print(f"  • Автоответчиков: {autoresponders_count}")
    print(f"  • Слишком коротких: {too_short_count}")
    print(f"  • Прошли фильтры: {len(filtered_calls)}")

    if not filtered_calls:
        print("\n⚠️  Нет звонков для обработки после фильтрации")
        return

    # Обработка первых 2-3 звонков для теста
    test_limit = min(3, len(filtered_calls))
    print(f"\n🚀 ЗАПУСК АНАЛИЗА ({test_limit} звонков):")

    results = []
    for i, (call_id, transcript, lead_id) in enumerate(filtered_calls[:test_limit], 1):
        print(f"\n[{i}/{test_limit}] Обработка звонка {call_id}...")

        # Анализ
        analysis = await analyze_call(call_id, transcript, settings)

        # Сохранение результата в БД
        if analysis["status"] == "success":
            cursor.execute("""
                UPDATE calls
                SET analysis_status = 'completed',
                    analysis_result = ?,
                    quality_score = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                json.dumps(analysis["result"]),
                analysis["result"].get("scores", {}).get("overall_quality"),
                datetime.now().isoformat(),
                call_id
            ))
            db.commit()
            print(f"  💾 Результат сохранен в БД")
        else:
            cursor.execute("""
                UPDATE calls
                SET analysis_status = 'failed',
                    analysis_error = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                analysis["error"],
                datetime.now().isoformat(),
                call_id
            ))
            db.commit()

        results.append({
            "call_id": call_id,
            "lead_id": lead_id,
            **analysis
        })

        # Задержка между запросами
        if i < test_limit:
            print(f"  ⏳ Ожидание 3 секунды перед следующим...")
            await asyncio.sleep(3)

    # Итоговая статистика
    print(f"\n{'='*80}")
    print(f"ИТОГИ ОБРАБОТКИ")
    print(f"{'='*80}")

    successful = sum(1 for r in results if r["status"] == "success")
    failed = sum(1 for r in results if r["status"] == "error")

    print(f"✅ Успешно проанализировано: {successful}")
    print(f"❌ Ошибок: {failed}")

    if successful > 0:
        avg_quality = sum(
            r["result"].get("scores", {}).get("overall_quality", 0)
            for r in results if r["status"] == "success"
        ) / successful
        print(f"📊 Средняя оценка качества: {avg_quality:.1f}/100")

    db.close()

if __name__ == "__main__":
    asyncio.run(main())
