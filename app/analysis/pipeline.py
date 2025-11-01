"""
Simplified pipeline for ChatGPT-only analysis.
No orchestrator needed - single model handles everything.
"""
import json
import pathlib
import yaml
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

async def call_openai_api(
    system: str,
    user: str,
    api_key: str,
    model: str = "gpt-4o",
    temperature: float = 0.2,
    max_tokens: int = 2000
) -> str:
    """
    Direct OpenAI API call.
    Uses gpt-4o (or gpt-4-turbo) for best reasoning + structured output.
    """
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
    model: str = "gpt-4o",
    temperature: float = 0.15,
    max_retries: int = 2
) -> Dict:
    """
    Single-pass analysis with ChatGPT.
    
    Args:
        dialogue_text: Transcript with speaker roles
        api_key: OpenAI API key
        model: gpt-4o (recommended) or gpt-4-turbo
        temperature: 0.15 for stable reasoning (range: 0.1-0.2)
        max_retries: Retry on invalid JSON
    
    Returns:
        Validated CallScoring dict
    """
    prompt = load_prompt("call_scoring.v1.yml")
    
    # Build system prompt with schema
    system = f"{prompt['role']}\n\nСхема:\n{prompt['schema_json']}\n"
    
    # Add few-shot examples
    if "few_shot" in prompt:
        system += "\n\nПримеры:\n"
        for ex_type, examples in prompt["few_shot"].items():
            system += f"\n{ex_type.upper()}:\n"
            for ex in examples:
                system += f"- {ex.get('dialogue', '')}\n  {ex.get('expect_note', '')}\n"
    
    # Retry logic for invalid JSON
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            # Call OpenAI API
            raw = await call_openai_api(
                system=system,
                user=dialogue_text,
                api_key=api_key,
                model=model,
                temperature=temperature,
                max_tokens=2000
            )
            
            # Parse and validate
            data = enforce_json_only(raw)
            validated = validate_call_scoring(data)
            
            # Post-validation consistency checks
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
