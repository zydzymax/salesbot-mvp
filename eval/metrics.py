import json
from app.llm.validators import CallScoring

def check_required_keys(obj, required):
    return all(k in obj for k in required)

def main():
    expected = json.load(open("eval/expected/call_scoring.v1.json", "r"))
    required = expected["required_keys"]
    sample = {
      "lead_profile": {},
      "need_summary": "",
      "buying_stage": "evaluation",
      "budget": {"stated_range": None, "inferred_monthly": {"value":0,"currency":None,"confidence":0.0}},
      "decision_maker": {"is_dm": False, "role": None, "confidence": 0.0},
      "timeline": {"urgency_days": None, "deadline_date": None},
      "objections": [],
      "risk_flags": [],
      "next_actions": [],
      "scores": {},
      "evidence_spans": [],
      "framework_signals": {"spin":{},"neat":{},"voss":{}},
      "meta": {"prompt_version":"call_scoring.v1"}
    }
    assert check_required_keys(sample, required)
    CallScoring(**sample)
    print("OK")
if __name__ == "__main__":
    main()
