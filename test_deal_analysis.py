"""
Найти сделку с несколькими звонками и проанализировать все
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, func
from app.database.models import Call
from app.config import get_settings
from app.audio.transcriber import WhisperTranscriber
from app.audio.diarization import diarize_transcript
from app.analysis.pipeline import analyze_dialog
import httpx

settings = get_settings()

async def main():
    # Подключение к БД
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Найти сделку с наибольшим количеством звонков
        query = (
            select(Call.amocrm_lead_id, func.count(Call.id).label('call_count'))
            .where(Call.audio_url != None)
            .where(Call.audio_url != '')
            .where(Call.amocrm_lead_id != None)
            .group_by(Call.amocrm_lead_id)
            .having(func.count(Call.id) >= 2)
            .order_by(func.count(Call.id).desc())
            .limit(1)
        )

        result = await session.execute(query)
        lead_data = result.first()

        if not lead_data:
            print("❌ Не найдено сделок с несколькими звонками")
            return

        lead_id = lead_data[0]
        call_count = lead_data[1]

        print("=" * 80)
        print(f"СДЕЛКА №{lead_id}")
        print(f"Количество звонков: {call_count}")
        print("=" * 80)

        # Получить все звонки для этой сделки
        calls_query = (
            select(Call)
            .where(Call.amocrm_lead_id == lead_id)
            .where(Call.audio_url != None)
            .where(Call.audio_url != '')
            .order_by(Call.created_at)
        )
        calls_result = await session.execute(calls_query)
        calls = calls_result.scalars().all()

        print(f"\nНайдено {len(calls)} звонков для обработки\n")

        # Обработать каждый звонок
        for idx, call in enumerate(calls, 1):
            print("\n" + "=" * 80)
            print(f"ЗВОНОК #{idx} из {len(calls)}")
            print("=" * 80)
            print(f"Call ID: {call.amocrm_call_id}")
            print(f"Дата: {call.created_at}")
            print(f"Длительность: {call.duration_seconds} секунд")
            print(f"URL: {call.audio_url}")

            # Шаг 1: Скачать аудио
            print("\n🔄 Скачивание аудио...")
            try:
                async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                    response = await client.get(call.audio_url)
                    response.raise_for_status()
                    audio_data = response.content
                print(f"✅ Аудио загружено: {len(audio_data)} байт")
            except Exception as e:
                print(f"❌ Ошибка загрузки: {e}")
                continue

            # Шаг 2: Транскрибация
            print("\n🔄 Транскрибация (Whisper)...")
            try:
                transcriber = WhisperTranscriber()
                transcription_result = await transcriber.transcribe(
                    audio_data=audio_data,
                    language="ru",
                    response_format="verbose_json",
                    temperature=0.0
                )
                transcript = transcription_result.get('text', '')
                print(f"✅ Транскрибация завершена: {len(transcript)} символов")

                # ПРОВЕРКА: Пропускаем автоответчики и короткие звонки
                if len(transcript) < 100:
                    print(f"⚠️  ПРОПУЩЕНО: Слишком короткая транскрипция ({len(transcript)} символов)")
                    print("   Вероятно автоответчик или недозвон\n")
                    continue

                if "недоступен" in transcript.lower() or "автоответчик" in transcript.lower():
                    print(f"⚠️  ПРОПУЩЕНО: Обнаружен автоответчик")
                    print(f"   Текст: {transcript[:100]}...\n")
                    continue

                print("\n" + "-" * 80)
                print("ТРАНСКРИПЦИЯ:")
                print("-" * 80)
                print(transcript)
                print("-" * 80)

            except Exception as e:
                print(f"❌ Ошибка транскрибации: {e}")
                continue

            # Шаг 3: Диаризация
            print("\n🔄 Разделение на роли (GPT-4o)...")
            try:
                diarization_result = await diarize_transcript(
                    transcript=transcript,
                    api_key=settings.openai_api_key,
                    model="gpt-4o"
                )

                dialogue = diarization_result['formatted_dialogue']
                turns = diarization_result['turns']
                print(f"✅ Диаризация завершена: {len(turns)} реплик")

                print("\n" + "-" * 80)
                print("ДИАЛОГ С РОЛЯМИ:")
                print("-" * 80)
                print(dialogue)
                print("-" * 80)

            except Exception as e:
                print(f"❌ Ошибка диаризации: {e}")
                dialogue = f"Разговор менеджера с клиентом:\n\n{transcript}"

            # Шаг 4: Анализ с GPT-5
            print("\n🔄 Глубокий анализ (GPT-5 Pro)...")
            print("⏳ Это может занять 2-5 минут...")

            try:
                analysis = await analyze_dialog(
                    dialogue_text=dialogue,
                    api_key=settings.openai_api_key,
                    model="gpt-5-pro",
                    temperature=0.3,
                    max_retries=3,
                    prompt_version="v2"
                )

                print("\n✅ Анализ завершен!")
                print("\n" + "=" * 80)
                print("РЕЗУЛЬТАТЫ АНАЛИЗА")
                print("=" * 80)

                # Вывести ключевые метрики
                print(f"\n📊 ОБЩАЯ ОЦЕНКА: {analysis.get('overall_quality_score', 'N/A')}/100")
                print(f"📈 Стадия сделки: {analysis.get('buying_stage', 'N/A')}")
                print(f"🎯 Готовность к покупке: {analysis.get('readiness_to_buy', 'N/A')}")

                # Бюджет
                budget = analysis.get('budget', {})
                if budget.get('amount'):
                    print(f"💰 Бюджет: {budget.get('amount')} {budget.get('currency')} (уверенность: {budget.get('confidence')})")

                # Краткое резюме
                print(f"\n📝 РЕЗЮМЕ:")
                print(analysis.get('summary', 'N/A'))

                # Сильные стороны
                strengths = analysis.get('call_strengths', [])
                if strengths:
                    print(f"\n✅ СИЛЬНЫЕ СТОРОНЫ ({len(strengths)}):")
                    for i, strength in enumerate(strengths[:3], 1):
                        print(f"  {i}. {strength}")

                # Слабые стороны
                weaknesses = analysis.get('call_weaknesses', [])
                if weaknesses:
                    print(f"\n⚠️  СЛАБЫЕ СТОРОНЫ ({len(weaknesses)}):")
                    for i, weakness in enumerate(weaknesses[:3], 1):
                        print(f"  {i}. {weakness}")

                # Рекомендации
                recommendations = analysis.get('coaching_recommendations', [])
                if recommendations:
                    print(f"\n💡 РЕКОМЕНДАЦИИ ДЛЯ УЛУЧШЕНИЯ ({len(recommendations)}):")
                    for i, rec in enumerate(recommendations, 1):
                        print(f"\n  {i}. Тема: {rec.get('topic', 'N/A')}")
                        print(f"     Совет: {rec.get('specific_advice', 'N/A')}")
                        if rec.get('example_script'):
                            print(f"     Пример: \"{rec.get('example_script')}\"")

                # Next steps
                next_steps = analysis.get('next_steps', [])
                if next_steps:
                    print(f"\n📋 СЛЕДУЮЩИЕ ШАГИ:")
                    for i, step in enumerate(next_steps, 1):
                        print(f"  {i}. {step}")

            except Exception as e:
                print(f"❌ Ошибка анализа: {e}")
                import traceback
                traceback.print_exc()
                continue

        print("\n" + "=" * 80)
        print("ВСЕ ЗВОНКИ ОБРАБОТАНЫ!")
        print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
