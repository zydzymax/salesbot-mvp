"""
Полный тест: транскрибация звонка + анализ с новыми промптами
"""
import asyncio
import json
import sys
import os
import httpx

sys.path.insert(0, '/root/salesbot-mvp')

from app.config import get_settings
from app.audio.transcriber import WhisperTranscriber
from app.audio.diarization import diarize_transcript
from app.analysis.pipeline import analyze_dialog

async def download_audio(url: str) -> bytes:
    """Скачать аудио файл"""
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content

async def main():
    settings = get_settings()

    # ID звонка для тестирования (129 секунд)
    call_id = "df41bf58bec94511a9f2c2f09ea418a9"
    audio_url = "https://amocrm.mango-office.ru/calls/recording/download/31851746/MToxMDIyNjg3NzoyNTA5Njk2MjY5MDow/NDA1MjgwMDMy"

    print("=" * 80)
    print("ПОЛНЫЙ ТЕСТ: ТРАНСКРИБАЦИЯ + АНАЛИЗ")
    print("=" * 80)
    print(f"\nCall ID: {call_id}")
    print(f"Audio URL: {audio_url}")
    print(f"Duration: 129 seconds")

    # Шаг 1: Скачивание аудио
    print("\n" + "=" * 80)
    print("ШАГ 1: СКАЧИВАНИЕ АУДИО")
    print("=" * 80)

    try:
        print("\n🔄 Скачивание аудио файла...")
        audio_data = await download_audio(audio_url)
        print(f"✅ Аудио загружено: {len(audio_data)} байт")

    except Exception as e:
        print(f"\n❌ ОШИБКА СКАЧИВАНИЯ: {e}")
        return

    # Шаг 2: Транскрибация
    print("\n" + "=" * 80)
    print("ШАГ 2: ТРАНСКРИБАЦИЯ (Whisper API)")
    print("=" * 80)
    print("\nПараметры:")
    print("  • Model: whisper-1")
    print("  • Language: ru")
    print("  • Temperature: 0.0")
    print("  • Response format: verbose_json")

    try:
        print("\n🔄 Отправка на транскрибацию...")

        transcriber = WhisperTranscriber()

        # Используем verbose_json для получения сегментов с таймингами
        transcript_data = await transcriber.transcribe(
            audio_data=audio_data,
            language="ru",
            response_format="verbose_json",
            temperature=0.0
        )

        if not transcript_data:
            print("\n❌ ОШИБКА: Транскрибация не удалась")
            return

        # Если вернулся просто текст (не JSON)
        if isinstance(transcript_data, str):
            transcript = transcript_data
            print("\n✅ Транскрибация завершена!")
            print(f"Длина текста: {len(transcript)} символов")
        else:
            # Если вернулся JSON
            transcript = transcript_data.get('text', '')
            segments = transcript_data.get('segments', [])
            print("\n✅ Транскрибация завершена!")
            print(f"Длина текста: {len(transcript)} символов")
            print(f"Количество сегментов: {len(segments)}")

        print("\n" + "-" * 80)
        print("ТРАНСКРИПЦИЯ (сплошной текст):")
        print("-" * 80)
        print(transcript)
        print("-" * 80)

        # Шаг 3: Диаризация (разделение на роли)
        print("\n" + "=" * 80)
        print("ШАГ 3: ДИАРИЗАЦИЯ - РАЗДЕЛЕНИЕ НА РОЛИ (GPT-4o)")
        print("=" * 80)
        print("\nПараметры:")
        print("  • Model: gpt-4o")
        print("  • Temperature: 0.1")
        print("  • Task: speaker role identification")

        print("\n🔄 Определение ролей (Менеджер/Клиент)...")

        diarization_result = await diarize_transcript(
            transcript=transcript,
            api_key=settings.openai_api_key,
            model="gpt-4o"
        )

        if diarization_result['status'] != 'success':
            print(f"\n⚠️  Диаризация не удалась: {diarization_result.get('error')}")
            print("Продолжаем с оригинальной транскрипцией...")
            dialogue_text = f"Разговор менеджера с клиентом:\n\n{transcript}"
        else:
            dialogue_text = diarization_result['formatted_dialogue']
            turns_count = len(diarization_result['turns'])
            print(f"\n✅ Диаризация завершена! Определено {turns_count} реплик")

            print("\n" + "-" * 80)
            print("ДИАЛОГ С РОЛЯМИ:")
            print("-" * 80)
            print(dialogue_text)
            print("-" * 80)

        # Шаг 4: Анализ
        print("\n" + "=" * 80)
        print("ШАГ 4: АНАЛИЗ С НОВЫМИ ПРОМПТАМИ (GPT-4o)")
        print("=" * 80)
        print("\nПараметры анализа (МАКСИМАЛЬНОЕ КАЧЕСТВО):")
        print("  • Model: chatgpt-4o-latest ⭐ (LATEST & MOST POWERFUL)")
        print("  • Temperature: 0.3 (баланс точность/креативность)")
        print("  • Prompt version: call_scoring.v2.yml (РАСШИРЕННЫЙ)")
        print("  • Max tokens: 4000 (детальный анализ)")
        print("  • Max retries: 3")
        print("  • Response format: strict JSON")
        print("  • Includes: B2B context, coaching framework, scoring logic")

        print("\n🔄 Запуск анализа с ChatGPT-4o (latest)...")

        analysis_result = await analyze_dialog(
            dialogue_text=dialogue_text,
            api_key=settings.openai_api_key,
            model="chatgpt-4o-latest",
            temperature=0.3,
            max_retries=3,
            prompt_version="v2"
        )

        print("\n✅ Анализ завершен!")
        print("\n" + "=" * 80)
        print("РЕЗУЛЬТАТ АНАЛИЗА")
        print("=" * 80)

        # Красивый вывод ключевых метрик
        print(f"\n📊 КРАТКАЯ СВОДКА:")
        print(f"  • Стадия сделки: {analysis_result.get('buying_stage')}")

        budget = analysis_result.get('budget', {})
        if budget.get('amount'):
            print(f"  • Бюджет: {budget.get('amount')} {budget.get('currency')} (confidence: {budget.get('confidence')})")
        else:
            print(f"  • Бюджет: не указан")

        dm = analysis_result.get('decision_maker', {})
        print(f"  • ЛПР: {dm.get('title', 'не определен')} (is_decision_maker: {dm.get('is_decision_maker')})")

        timeline = analysis_result.get('timeline', {})
        print(f"  • Timeline: {timeline.get('timing', 'не указан')}")

        objections = analysis_result.get('objections', [])
        print(f"\n💬 ВОЗРАЖЕНИЯ ({len(objections)}):")
        for obj in objections:
            print(f"  • {obj.get('type')}: {obj.get('text')}")
            if obj.get('manager_response'):
                print(f"    Ответ: {obj.get('manager_response')}")
            if obj.get('is_resolved'):
                print(f"    ✅ Решено")
            else:
                print(f"    ❌ Не решено")

        risk_flags = analysis_result.get('risk_flags', [])
        print(f"\n⚠️  RED FLAGS ({len(risk_flags)}):")
        for flag in risk_flags:
            print(f"  • {flag.get('type')}: {flag.get('description')}")
            print(f"    Severity: {flag.get('severity')}")

        next_actions = analysis_result.get('next_actions', [])
        print(f"\n✅ РЕКОМЕНДАЦИИ ({len(next_actions)}):")
        for i, action in enumerate(next_actions, 1):
            print(f"  {i}. {action.get('action')}")
            print(f"     Причина: {action.get('reason')}")
            print(f"     Priority: {action.get('priority')}")

        scores = analysis_result.get('scores', {})
        print(f"\n🎯 ОЦЕНКИ:")
        print(f"  • Качество разговора: {scores.get('overall_quality', 0)}/100")
        print(f"  • Работа с возражениями: {scores.get('objection_handling', 0)}/100")
        print(f"  • Полнота квалификации: {scores.get('qualification_completeness', 0)}/100")

        # Метаданные
        meta = analysis_result.get('meta', {})
        print(f"\n📝 МЕТАДАННЫЕ:")
        print(f"  • Model: {meta.get('model')}")
        print(f"  • Prompt version: {meta.get('prompt_version')}")
        print(f"  • Language: {meta.get('lang')}")

        print("\n" + "=" * 80)
        print("ПОЛНЫЙ JSON РЕЗУЛЬТАТ")
        print("=" * 80)
        print(json.dumps(analysis_result, indent=2, ensure_ascii=False))

    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
