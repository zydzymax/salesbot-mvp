"""
Демонстрация полного анализа сделки №21327065 (2 реальных звонка)
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.database.models import Call
from app.config import get_settings
from app.audio.transcriber import WhisperTranscriber
from app.audio.diarization import diarize_transcript
from app.analysis.pipeline import analyze_dialog
import httpx
import json

settings = get_settings()
DEAL_ID = "21327065"

async def main():
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Получить звонки для сделки
        calls_query = (
            select(Call)
            .where(Call.amocrm_lead_id == DEAL_ID)
            .where(Call.audio_url != None)
            .where(Call.audio_url != '')
            .where(Call.duration_seconds > 60)
            .order_by(Call.created_at)
        )
        calls_result = await session.execute(calls_query)
        calls = calls_result.scalars().all()

        print("=" * 80)
        print(f"СДЕЛКА №{DEAL_ID} - ПОЛНЫЙ АНАЛИЗ")
        print("=" * 80)
        print(f"Найдено звонков: {len(calls)}\n")

        for idx, call in enumerate(calls, 1):
            print("\n" + "=" * 80)
            print(f"ЗВОНОК #{idx} из {len(calls)}")
            print("=" * 80)
            print(f"Call ID: {call.amocrm_call_id}")
            print(f"Дата: {call.created_at}")
            print(f"Длительность: {call.duration_seconds} секунд ({int(call.duration_seconds/60)} мин {call.duration_seconds%60} сек)")

            # Скачать аудио
            print("\n🔄 Скачивание аудио...")
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                response = await client.get(call.audio_url)
                response.raise_for_status()
                audio_data = response.content
            print(f"✅ Аудио загружено: {len(audio_data)} байт")

            # Транскрибация
            print("\n🔄 Транскрибация (Whisper)...")
            transcriber = WhisperTranscriber()
            transcription_result = await transcriber.transcribe(
                audio_data=audio_data,
                language="ru",
                response_format="verbose_json",
                temperature=0.0
            )
            transcript = transcription_result.get('text', '')
            print(f"✅ Транскрибация завершена: {len(transcript)} символов")

            # Проверка на автоответчик
            if len(transcript) < 100 or "недоступен" in transcript.lower():
                print(f"⚠️  ПРОПУЩЕНО: Автоответчик или короткий звонок\n")
                continue

            print("\n" + "-" * 80)
            print("ТРАНСКРИПЦИЯ:")
            print("-" * 80)
            print(transcript)
            print("-" * 80)

            # Диаризация
            print("\n🔄 Разделение на роли (GPT-4o)...")
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

            # Анализ с GPT-5
            print("\n🔄 Глубокий анализ (GPT-5 Pro)...")
            print("⏳ Это может занять 2-5 минут...")

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
            print(f"РЕЗУЛЬТАТЫ АНАЛИЗА - ЗВОНОК #{idx}")
            print("=" * 80)

            # Ключевые метрики
            print(f"\n📊 ОБЩАЯ ОЦЕНКА: {analysis.get('scores', {}).get('overall_quality', 'N/A')}/100")
            print(f"📈 Стадия сделки: {analysis.get('buying_stage', 'N/A')}")
            print(f"🎯 Готовность к покупке: {analysis.get('scores', {}).get('closing_readiness', 'N/A')}/100")

            # Резюме
            summary = analysis.get('need_summary', 'N/A')
            print(f"\n📝 РЕЗЮМЕ:")
            print(f"{summary}")

            # Red flags
            red_flags = analysis.get('risk_flags', [])
            if red_flags:
                print(f"\n⚠️  RED FLAGS ({len(red_flags)}):")
                for flag in red_flags[:3]:
                    print(f"  • {flag.get('description')} (severity: {flag.get('severity')})")

            # Рекомендации
            recommendations = analysis.get('coaching_recommendations', [])
            if recommendations:
                print(f"\n💡 РЕКОМЕНДАЦИИ ДЛЯ УЛУЧШЕНИЯ ({len(recommendations)}):")
                for i, rec in enumerate(recommendations[:3], 1):
                    print(f"\n  {i}. Тема: {rec.get('topic', 'N/A')}")
                    print(f"     Совет: {rec.get('specific_advice', 'N/A')}")
                    if rec.get('example_script'):
                        script = rec.get('example_script', '')[:200]
                        print(f"     Пример: \"{script}...\"")

            # Следующие шаги
            next_actions = analysis.get('next_actions', [])
            if next_actions:
                print(f"\n📋 СЛЕДУЮЩИЕ ШАГИ:")
                for action in next_actions[:3]:
                    priority = action.get('priority', 'medium').upper()
                    print(f"  • [{priority}] {action.get('action', 'N/A')}")

        print("\n" + "=" * 80)
        print("✅ ВСЕ ЗВОНКИ ОБРАБОТАНЫ!")
        print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
