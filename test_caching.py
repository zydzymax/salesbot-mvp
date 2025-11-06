"""
Тест кэширования - проверяем что повторные анализы берутся из кэша мгновенно
"""
import asyncio
import sys
import sqlite3
import time

sys.path.insert(0, '/root/salesbot-mvp')

from app.config import get_settings
from app.analysis.pipeline import analyze_dialog

async def main():
    settings = get_settings()
    db = sqlite3.connect('salesbot.db')
    cursor = db.cursor()

    print("="*80)
    print("ТЕСТ КЭШИРОВАНИЯ")
    print("="*80)

    # Получить один обработанный звонок
    cursor.execute("""
        SELECT id, transcription_text
        FROM calls
        WHERE transcription_text IS NOT NULL
          AND LENGTH(transcription_text) > 200
          AND duration_seconds >= 60
        LIMIT 1
    """)

    call_id, transcript = cursor.fetchone()

    print(f"\nЗвонок для теста: {call_id}")
    print(f"Длина транскрипции: {len(transcript)} символов")

    # ПЕРВЫЙ ЗАПУСК - без кэша
    print(f"\n{'='*80}")
    print("1️⃣  ПЕРВЫЙ ЗАПУСК (без кэша)")
    print(f"{'='*80}")

    start = time.time()
    result1 = await analyze_dialog(
        dialogue_text=transcript,
        api_key=settings.openai_api_key,
        model="gpt-5-pro",
        temperature=0.3,
        prompt_version="v2",
        use_cache=True
    )
    elapsed1 = time.time() - start

    print(f"\n✅ Анализ завершен")
    print(f"⏱️  Время: {elapsed1:.2f} секунд")
    print(f"📊 Качество: {result1.get('scores', {}).get('overall_quality')}/100")

    # ВТОРОЙ ЗАПУСК - с кэшем
    print(f"\n{'='*80}")
    print("2️⃣  ВТОРОЙ ЗАПУСК (с кэшем)")
    print(f"{'='*80}")

    start = time.time()
    result2 = await analyze_dialog(
        dialogue_text=transcript,
        api_key=settings.openai_api_key,
        model="gpt-5-pro",
        temperature=0.3,
        prompt_version="v2",
        use_cache=True
    )
    elapsed2 = time.time() - start

    print(f"\n✅ Анализ завершен")
    print(f"⏱️  Время: {elapsed2:.2f} секунд")
    print(f"📊 Качество: {result2.get('scores', {}).get('overall_quality')}/100")

    # ПРОВЕРКА
    print(f"\n{'='*80}")
    print("РЕЗУЛЬТАТЫ ТЕСТА")
    print(f"{'='*80}")

    speedup = elapsed1 / elapsed2 if elapsed2 > 0 else 0
    savings = ((elapsed1 - elapsed2) / elapsed1 * 100) if elapsed1 > 0 else 0

    print(f"\n⏱️  Первый запуск: {elapsed1:.2f}с")
    print(f"⏱️  Второй запуск: {elapsed2:.2f}с (из кэша)")
    print(f"🚀 Ускорение: {speedup:.1f}x")
    print(f"💰 Экономия времени: {savings:.1f}%")

    if elapsed2 < 1.0:
        print(f"\n✅ КЭШИРОВАНИЕ РАБОТАЕТ! Результат получен мгновенно из кэша")
    else:
        print(f"\n⚠️  Кэширование может не работать - второй запрос занял {elapsed2:.2f}с")

    # Проверка идентичности результатов
    same_quality = result1.get('scores', {}).get('overall_quality') == result2.get('scores', {}).get('overall_quality')
    print(f"\n🔍 Результаты идентичны: {'✅ ДА' if same_quality else '❌ НЕТ'}")

    db.close()

if __name__ == "__main__":
    asyncio.run(main())
