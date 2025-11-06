"""
Простой тест GPT-5 API для отладки
"""
import asyncio
import sys
import json

sys.path.insert(0, '/root/salesbot-mvp')

from app.config import get_settings
from app.analysis.pipeline import call_gpt5_responses_api

async def main():
    settings = get_settings()

    print("=" * 80)
    print("GPT-5 API DEBUG TEST")
    print("=" * 80)

    system = "Ты — эксперт по продажам. Анализируй диалоги."
    user = "Менеджер: Здравствуйте! Клиент: Привет. О чем речь?"

    print("\nSystem prompt:", system[:50], "...")
    print("User message:", user)
    print("\nОтправка запроса к GPT-5...")

    try:
        response = await call_gpt5_responses_api(
            system=system,
            user=user,
            api_key=settings.openai_api_key,
            model="gpt-5-pro",
            temperature=0.3
        )

        print("\n✅ УСПЕХ!")
        print("Response:", response[:200], "...")

    except Exception as e:
        print(f"\n❌ ОШИБКА: {type(e).__name__}")
        print(f"Сообщение: {str(e)}")

        import traceback
        print("\nПолный traceback:")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
