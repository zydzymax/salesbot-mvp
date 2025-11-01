from pydantic import BaseModel, Field, conint, confloat
from typing import List, Optional, Literal, Dict

Stage = Literal["awareness","consideration","evaluation","negotiation","closed_won","closed_lost"]

class InferredBudget(BaseModel):
    value: conint(ge=0)
    currency: Optional[str]
    confidence: confloat(ge=0.0, le=1.0)

class Budget(BaseModel):
    stated_range: Optional[str]
    inferred_monthly: InferredBudget

class DecisionMaker(BaseModel):
    is_dm: bool
    role: Optional[str]
    confidence: confloat(ge=0.0, le=1.0)

class Timeline(BaseModel):
    urgency_days: Optional[int]
    deadline_date: Optional[str]

class Objection(BaseModel):
    type: Literal["price","quality","timeline","other"]
    text: str

class RiskFlag(BaseModel):
    code: Literal["no_dm","no_budget","vague_specs","price_sensitive","prompt_injection"]
    evidence: str

class NextAction(BaseModel):
    action: Literal["send_quote","schedule_call","request_specs","send_samples"]
    owner: Literal["AM","Client"]
    due_days: conint(ge=0)

class EvidenceSpan(BaseModel):
    quote: str
    label: Literal["budget","dm","need","timeline","stage"]

class FrameworkSignals(BaseModel):
    spin: Dict
    neat: Dict
    voss: Dict

class Meta(BaseModel):
    model: Optional[str] = None
    prompt_version: str
    lang: Optional[str] = None

class CallScoring(BaseModel):
    lead_profile: Dict
    need_summary: str
    buying_stage: Stage
    budget: Budget
    decision_maker: DecisionMaker
    timeline: Timeline
    objections: List[Objection]
    risk_flags: List[RiskFlag]
    next_actions: List[NextAction]
    scores: Dict
    evidence_spans: List[EvidenceSpan]
    framework_signals: FrameworkSignals
    meta: Meta
