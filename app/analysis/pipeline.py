import json, pathlib, yaml
from typing import Dict
from app.llm.validators import CallScoring

PROMPTS_DIR = pathlib.Path("app/prompts/system/analysis")

def load_prompt(name: str) -> Dict:
    p = PROMPTS_DIR / name
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def enforce_json_only(text: str) -> Dict:
    # Модель обязана вернуть чистый JSON. Парсим строго.
    return json.loads(text)

def validate_call_scoring(data: Dict) -> CallScoring:
    return CallScoring(**data)

def analyze_dialog(llm_call, dialogue_text: str) -> Dict:
    """
    llm_call(system: str, user: str, temperature: float, top_p: float, max_tokens: int) -> str(JSON)
    """
    prompt = load_prompt("call_scoring.v1.yml")
    system = f"{prompt['role']}\nСхема:\n{prompt['schema_json']}\n"
    raw = llm_call(system=system, user=dialogue_text, temperature=0.2, top_p=0.9, max_tokens=1400)
    data = enforce_json_only(raw)
    validated = validate_call_scoring(data)
    return validated.dict()
