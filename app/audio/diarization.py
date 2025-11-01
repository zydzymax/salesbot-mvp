"""
Speaker Diarization using GPT-4o
Разделение транскрипции на роли: менеджер и клиент
"""

import json
from typing import Dict, List
import structlog
import httpx

logger = structlog.get_logger("salesbot.audio.diarization")


async def diarize_transcript(
    transcript: str,
    api_key: str,
    model: str = "gpt-4o"
) -> Dict:
    """
    Разделить транскрипцию на роли: менеджер и клиент

    Args:
        transcript: Сплошной текст транскрипции
        api_key: OpenAI API key
        model: Модель для диаризации (default: gpt-4o)

    Returns:
        Dict с полями:
        - formatted_dialogue: str - отформатированный диалог с ролями
        - turns: List[Dict] - список реплик с метаданными
    """

    system_prompt = """Ты — эксперт по анализу B2B телефонных разговоров.

ЗАДАЧА: Разбей транскрипцию телефонного звонка на реплики и определи роли (Менеджер или Клиент).

КОНТЕКСТ:
- Это звонок менеджера швейного производства SoVAni клиенту
- Менеджер обычно представляется первым ("Меня зовут...", "Представляю...")
- Клиент отвечает на вопросы и задает свои

ФОРМАТ ВЫВОДА — СТРОГО JSON:
{
  "turns": [
    {"speaker": "Менеджер", "text": "реплика"},
    {"speaker": "Клиент", "text": "реплика"}
  ]
}

ПРАВИЛА:
1. Определи по содержанию кто менеджер, кто клиент
2. Раздели на логические реплики
3. Короткие междометия ("Да", "Угу", "Понятно") объедини с предыдущей репликой того же спикера
4. Вернуть ТОЛЬКО валидный JSON, без дополнительного текста
5. Если непонятно кто говорит — используй "Менеджер" для активной стороны"""

    user_prompt = f"""Транскрипция звонка:

{transcript}

Разбей на реплики и определи роли. Верни JSON."""

    try:
        logger.info("Starting diarization", transcript_length=len(transcript))

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.1,  # Низкая температура для стабильности
                    "response_format": {"type": "json_object"}
                }
            )

            response.raise_for_status()
            result = response.json()

            content = result["choices"][0]["message"]["content"]
            diarized = json.loads(content)

            # Форматировать в читаемый вид
            formatted_lines = []
            for turn in diarized.get("turns", []):
                speaker = turn.get("speaker", "Unknown")
                text = turn.get("text", "")
                formatted_lines.append(f"{speaker}: {text}")

            formatted_dialogue = "\n".join(formatted_lines)

            logger.info(
                "Diarization completed",
                turns_count=len(diarized.get("turns", [])),
                formatted_length=len(formatted_dialogue)
            )

            return {
                "formatted_dialogue": formatted_dialogue,
                "turns": diarized.get("turns", []),
                "status": "success"
            }

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse diarization JSON: {e}", content=content[:200])
        return {
            "formatted_dialogue": transcript,
            "turns": [],
            "status": "error",
            "error": f"JSON parse error: {e}"
        }

    except Exception as e:
        logger.error(f"Diarization failed: {e}")
        return {
            "formatted_dialogue": transcript,
            "turns": [],
            "status": "error",
            "error": str(e)
        }
