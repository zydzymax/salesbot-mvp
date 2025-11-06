"""
Quick test to check if GPT-5 API is accessible
"""
import asyncio
import httpx
from app.config import settings

async def test_gpt5():
    """Test simple GPT-5 request"""

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "gpt-5-pro",
        "input": "Hello, can you respond with a simple JSON: {\"status\": \"ok\", \"message\": \"GPT-5 works\"}",
        "text": {
            "format": {"type": "json_object"}
        }
    }

    print("Testing GPT-5 API...")
    print(f"Endpoint: https://api.openai.com/v1/responses")
    print(f"Model: gpt-5-pro")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers=headers,
                json=payload
            )

            print(f"\nStatus Code: {response.status_code}")

            if response.status_code != 200:
                print(f"Error: {response.text}")
                return False

            data = response.json()
            print(f"Response: {data}")
            return True

    except Exception as e:
        print(f"Exception: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_gpt5())
    if result:
        print("\n✅ GPT-5 API works!")
    else:
        print("\n❌ GPT-5 API failed!")
