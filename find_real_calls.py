"""
Найти звонки с реальными разговорами (длительность > 60 сек)
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, func, and_
from app.database.models import Call
from app.config import get_settings

settings = get_settings()

async def main():
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Найти звонки длительностью больше 60 секунд (реальные разговоры)
        query = (
            select(Call.amocrm_lead_id, func.count(Call.id).label('call_count'), func.sum(Call.duration_seconds).label('total_duration'))
            .where(Call.audio_url != None)
            .where(Call.audio_url != '')
            .where(Call.amocrm_lead_id != None)
            .where(Call.duration_seconds > 60)  # Минимум 60 секунд
            .group_by(Call.amocrm_lead_id)
            .having(func.count(Call.id) >= 2)
            .order_by(func.count(Call.id).desc())
            .limit(5)
        )

        result = await session.execute(query)
        deals = result.all()

        if not deals:
            print("❌ Не найдено сделок с реальными разговорами (>60 сек, >=2 звонка)")
            return

        print("=" * 80)
        print("СДЕЛКИ С РЕАЛЬНЫМИ РАЗГОВОРАМИ")
        print("=" * 80)

        for idx, (lead_id, call_count, total_duration) in enumerate(deals, 1):
            print(f"\n{idx}. Сделка №{lead_id}")
            print(f"   Звонков: {call_count}")
            print(f"   Общая длительность: {int(total_duration)} сек ({int(total_duration/60)} мин)")

            # Показать детали звонков
            calls_query = (
                select(Call)
                .where(Call.amocrm_lead_id == lead_id)
                .where(Call.audio_url != None)
                .where(Call.audio_url != '')
                .where(Call.duration_seconds > 60)
                .order_by(Call.created_at)
            )
            calls_result = await session.execute(calls_query)
            calls = calls_result.scalars().all()

            for call in calls:
                print(f"      - {call.created_at.strftime('%Y-%m-%d %H:%M')} | {call.duration_seconds} сек | {call.amocrm_call_id}")

if __name__ == "__main__":
    asyncio.run(main())
