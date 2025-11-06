"""
Simplified pipeline for ChatGPT-only analysis.
No orchestrator needed - single model handles everything.
With caching support for cost optimization.
"""
import json
import pathlib
import yaml
import hashlib
from typing import Dict, Optional
import httpx
from app.llm.validators import CallScoring

PROMPTS_DIR = pathlib.Path("app/prompts/system/analysis")

def load_prompt(name: str) -> Dict:
    """Load YAML prompt file"""
    p = PROMPTS_DIR / name
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def enforce_json_only(text: str) -> Dict:
    """Parse strict JSON from LLM response"""
    # Strip markdown code blocks if present
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return json.loads(text.strip())

def validate_call_scoring(data: Dict) -> CallScoring:
    """Validate against Pydantic schema"""
    return CallScoring(**data)

async def call_gpt5_responses_api(
    system: str,
    user: str,
    api_key: str,
    model: str = "gpt-5-pro",
    temperature: float = 0.3
) -> str:
    """
    GPT-5 API call via /v1/responses endpoint.
    Uses gpt-5-pro for MAXIMUM reasoning depth and accuracy.

    GPT-5 features:
    - Deep reasoning (hundreds of reasoning tokens)
    - Superior accuracy for complex analysis
    - Better understanding of nuanced B2B contexts
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Combine system and user into single input
    # ВАЖНО: Для json_object формата ОБЯЗАТЕЛЬНО должно быть слово "json" в input
    combined_input = f"{system}\n\n=== ЗАДАЧА ===\n{user}\n\nОТВЕТ В ФОРМАТЕ JSON:"

    payload = {
        "model": model,
        "input": combined_input,
        # GPT-5 does not support temperature parameter
        "text": {
            "format": {"type": "json_object"}  # Force JSON output
        }
    }

    async with httpx.AsyncClient(timeout=600.0) as client:  # GPT-5 with deep reasoning can take 5-10 minutes
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers=headers,
            json=payload
        )

        # Log error details if request fails
        if response.status_code != 200:
            import structlog
            logger = structlog.get_logger("salesbot.gpt5")
            logger.error(f"GPT-5 API error: {response.status_code}", error_body=response.text[:500])

        response.raise_for_status()
        data = response.json()

        # Extract text from output array
        for item in data.get("output", []):
            if item.get("type") == "message":
                content = item.get("content", [])
                for content_item in content:
                    if content_item.get("type") == "output_text":
                        return content_item.get("text", "")

        raise ValueError("No text output found in GPT-5 response")


async def call_openai_api(
    system: str,
    user: str,
    api_key: str,
    model: str = "chatgpt-4o-latest",
    temperature: float = 0.3,
    max_tokens: int = 4000
) -> str:
    """
    Universal OpenAI API call - routes to correct endpoint based on model.

    GPT-5 models (gpt-5-pro, gpt-5-nano, etc) → /v1/responses endpoint
    GPT-4 models (gpt-4o, chatgpt-4o-latest, etc) → /v1/chat/completions endpoint
    """
    # Check if GPT-5 model - route to /v1/responses
    if model.startswith("gpt-5"):
        return await call_gpt5_responses_api(system, user, api_key, model, temperature)

    # GPT-4 and older via chat/completions
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"}  # Force JSON output
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

async def analyze_dialog(
    dialogue_text: str,
    api_key: str,
    model: str = "gpt-5-pro",
    temperature: float = 0.3,
    max_retries: int = 3,
    prompt_version: str = "v2",
    use_cache: bool = True
) -> Dict:
    """
    Deep analysis with GPT-5 Pro (or GPT-4o) for high-quality insights and recommendations.
    With intelligent caching to avoid duplicate API calls and save costs.

    Args:
        dialogue_text: Transcript with speaker roles (Менеджер:/Клиент: format)
        api_key: OpenAI API key
        model: gpt-5-pro (DEFAULT - most powerful for deep reasoning)
              Can also use: chatgpt-4o-latest, gpt-4o, gpt-4-turbo
        temperature: 0.3 for balance between accuracy and creative recommendations
        max_retries: Retry on invalid JSON/validation errors
        prompt_version: "v1" or "v2" (v2 recommended for maximum detail)
        use_cache: Enable caching to save costs (default: True)

    Returns:
        Validated CallScoring dict with deep insights and actionable recommendations
    """
    # Generate cache key based on dialogue + model + prompt version
    cache_key = None
    if use_cache:
        cache_str = f"{dialogue_text}|{model}|{prompt_version}"
        cache_key = hashlib.sha256(cache_str.encode()).hexdigest()

        # Try to get from cache (simple file-based for now, can upgrade to Redis)
        try:
            cache_file = pathlib.Path(f".cache/analysis_{cache_key}.json")
            if cache_file.exists():
                import structlog
                logger = structlog.get_logger("salesbot.pipeline")
                logger.info("Cache hit - reusing previous analysis", cache_key=cache_key[:8])
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass  # Cache miss or error, continue with fresh analysis

    prompt_file = f"call_scoring.{prompt_version}.yml" if prompt_version == "v2" else "call_scoring.v1.yml"
    prompt = load_prompt(prompt_file)
    
    # Build comprehensive system prompt
    system_parts = [
        prompt.get('task', ''),
        prompt.get('role', ''),
        prompt.get('critical_rules', ''),
        f"\n\nСХЕМА JSON:\n{prompt.get('schema_json', '')}",
        f"\n\nЛОГИКА SCORING:\n{prompt.get('scoring_logic', '')}",
        f"\n\nОПРЕДЕЛЕНИЯ:\n{prompt.get('definitions', '')}",
        f"\n\nКОНТЕКСТ B2B ТРИКОТАЖ:\n{prompt.get('b2b_knitwear_context', '')}",
        f"\n\nFRAMEWORK КОУЧИНГА:\n{prompt.get('coaching_framework', '')}",
        f"\n\nПРОЦЕСС REASONING:\n{prompt.get('reasoning_process', '')}",
        f"\n\nПРОВЕРКИ КАЧЕСТВА:\n{prompt.get('quality_checks', '')}",
        f"\n\nАНТИ-ГАЛЛЮЦИНАЦИИ:\n{prompt.get('anti_hallucination', '')}",
    ]

    # Add few-shot examples if present
    if "few_shot_examples" in prompt:
        system_parts.append("\n\nПРИМЕРЫ АНАЛИЗА:")
        examples = prompt["few_shot_examples"]
        for key, ex in examples.items():
            system_parts.append(f"\n{key.upper()}:")
            system_parts.append(f"Диалог:\n{ex.get('dialogue', '')}")
            if "expected_scores" in ex:
                system_parts.append(f"Ожидаемые scores: {ex['expected_scores']}")
            if "critical_mistakes" in ex:
                system_parts.append(f"Критические ошибки: {ex['critical_mistakes']}")

    system = "\n".join(filter(None, system_parts))
    
    # Retry logic for invalid JSON
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            # Call OpenAI API with increased token limit for detailed analysis
            raw = await call_openai_api(
                system=system,
                user=dialogue_text,
                api_key=api_key,
                model=model,
                temperature=temperature,
                max_tokens=4000
            )
            
            # Parse JSON
            data = enforce_json_only(raw)

            # Save to cache if enabled
            if use_cache and cache_key:
                try:
                    cache_file = pathlib.Path(f".cache/analysis_{cache_key}.json")
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(cache_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass  # Cache save error is not critical

            # For v2, skip Pydantic validation (schema is much richer)
            # Just return the dict directly
            if prompt_version == "v2":
                return data

            # For v1, use Pydantic validation
            validated = validate_call_scoring(data)
            _check_consistency(validated)
            return validated.dict()
            
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            if attempt < max_retries:
                # Retry with slightly higher temperature
                temperature = min(temperature + 0.05, 0.3)
                continue
            raise Exception(f"Failed after {max_retries} retries: {last_error}")

def _check_consistency(result: CallScoring) -> None:
    """
    Post-validation consistency checks.
    Raises ValueError if inconsistent.
    """
    # Check: stage ↔ next_actions
    stage = result.buying_stage
    actions = [a.action for a in result.next_actions]
    
    if stage == "evaluation" and not any(a in actions for a in ["request_specs", "send_samples"]):
        raise ValueError(f"Stage '{stage}' but no relevant next_actions")
    
    # Check: budget_clarity score vs actual budget data
    if result.scores.get("budget_clarity_0_3") == 3:
        if not result.budget.stated_range and result.budget.inferred_monthly.confidence < 0.5:
            raise ValueError("budget_clarity=3 but no clear budget data")
    
    # Check: evidence_spans for key fields
    evidence_labels = {e.label for e in result.evidence_spans}
    if result.budget.stated_range and "budget" not in evidence_labels:
        raise ValueError("Budget stated but no evidence_spans.budget")
