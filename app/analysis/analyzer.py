"""
GPT-powered call analysis engine
Structured analysis with caching and error handling
"""

import json
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from enum import Enum

import httpx
import structlog

from ..config import get_settings
from ..utils.security import SecurityManager
from ..utils.helpers import retry_async, clean_text_for_analysis
from ..utils.api_budget import api_budget, BudgetExceededError
from .prompts import ANALYSIS_PROMPTS, SYSTEM_INSTRUCTIONS, SPECIAL_PROMPTS
from .cache import AnalysisCache

logger = structlog.get_logger("salesbot.analysis.analyzer")


class CallType(str, Enum):
    GENERAL = "general"
    COLD_CALL = "cold_call" 
    INCOMING = "incoming_call"
    FOLLOW_UP = "follow_up"
    COMPLAINT = "complaint"
    PRESENTATION = "presentation"


@dataclass
class AnalysisResult:
    """Structured analysis result"""
    overall_score: float
    scores: Dict[str, float]
    strengths: List[str]
    weaknesses: List[str]
    recommendations: List[str]
    key_phrases: List[str]
    missed_opportunities: List[str]
    follow_up_required: bool
    client_sentiment: str
    call_outcome: str
    summary: str
    confidence: float = 1.0
    analysis_timestamp: datetime = None
    
    def __post_init__(self):
        if self.analysis_timestamp is None:
            self.analysis_timestamp = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AnalysisResult':
        """Create from dictionary"""
        if 'analysis_timestamp' in data and isinstance(data['analysis_timestamp'], str):
            data['analysis_timestamp'] = datetime.fromisoformat(data['analysis_timestamp'])
        return cls(**data)


class CallAnalyzer:
    """GPT-powered call analysis"""
    
    def __init__(self):
        self.settings = get_settings()
        self.security = SecurityManager()
        self.cache = AnalysisCache()
        
        self.api_url = "https://api.openai.com/v1/chat/completions"
        self.model = "gpt-3.5-turbo"
        self.max_tokens = 2000
        self.temperature = 0.3  # Lower for more consistent analysis
    
    async def analyze_call(
        self,
        transcription: str,
        call_type: str = "general",
        use_cache: bool = True
    ) -> Optional[AnalysisResult]:
        """Analyze call transcription"""
        
        if not self.settings.openai_api_key:
            logger.error("OpenAI API key not configured")
            return None
        
        if not transcription or len(transcription.strip()) < 10:
            logger.error("Transcription too short for analysis")
            return None
        
        # Clean transcription
        clean_transcription = clean_text_for_analysis(transcription)
        
        # Check cache if enabled
        cache_key = None
        if use_cache:
            cache_key = self.security.hash_text_for_cache(
                f"{clean_transcription}:{call_type}:{self.model}"
            )
            cached_result = await self.cache.get_analysis(cache_key, "call_analysis")
            if cached_result:
                logger.info("Using cached analysis result")
                return AnalysisResult.from_dict(cached_result)
        
        logger.info(f"Starting call analysis", call_type=call_type, text_length=len(clean_transcription))
        
        try:
            # Perform analysis
            analysis_data = await self._perform_gpt_analysis(clean_transcription, call_type)
            
            if not analysis_data:
                logger.error("GPT analysis returned no data")
                return None
            
            # Parse and validate result
            result = self._parse_analysis_result(analysis_data)
            
            if result and cache_key:
                # Cache the result
                await self.cache.save_analysis(
                    cache_key, 
                    "call_analysis", 
                    result.to_dict(),
                    ttl_seconds=self.settings.cache_ttl_seconds
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Call analysis failed: {e}")
            return None
    
    async def _perform_gpt_analysis(
        self,
        transcription: str,
        call_type: str
    ) -> Optional[Dict[str, Any]]:
        """Perform GPT analysis with retries"""
        
        # Get prompt for call type
        if call_type not in ANALYSIS_PROMPTS:
            logger.warning(f"Unknown call type: {call_type}, using general")
            call_type = "general"
        
        prompt = ANALYSIS_PROMPTS[call_type] + transcription
        system_prompt = SYSTEM_INSTRUCTIONS["general"]
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        try:
            result = await retry_async(
                lambda: self._make_openai_request(messages),
                max_retries=3,
                delay=2.0,
                backoff_factor=2.0,
                exceptions=(httpx.HTTPError,)
            )
            
            return result
            
        except Exception as e:
            logger.error(f"GPT analysis request failed: {e}")
            return None
    
    async def _make_openai_request(self, messages: List[Dict]) -> Optional[Dict[str, Any]]:
        """Make request to OpenAI API with budget protection"""

        # Check budget before making request
        estimated_cost = 0.05  # Rough estimate for gpt-3.5-turbo
        allowed, reason = api_budget.can_make_request(estimated_cost)
        if not allowed:
            logger.error(f"Budget exceeded: {reason}")
            raise BudgetExceededError(reason)

        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "response_format": {"type": "json_object"}  # Ensure JSON response
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                response = await client.post(
                    self.api_url,
                    headers=headers,
                    json=payload
                )
                
                logger.info(
                    f"OpenAI API request completed",
                    status_code=response.status_code,
                    tokens_used=response.headers.get("x-tokens-used", "unknown")
                )
                
                response.raise_for_status()

                data = response.json()

                if "choices" not in data or not data["choices"]:
                    logger.error("No choices in OpenAI response")
                    return None

                # Record API usage
                usage = data.get("usage", {})
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)
                if input_tokens or output_tokens:
                    await api_budget.record_request(
                        model=self.model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        request_type="call_analysis"
                    )

                content = data["choices"][0]["message"]["content"]

                # Parse JSON response
                try:
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse GPT JSON response: {e}")
                    logger.debug(f"Raw response: {content}")
                    return None
                    
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.warning("OpenAI rate limit hit, will retry")
                    raise
                elif e.response.status_code == 400:
                    logger.error(f"Bad request to OpenAI: {e.response.text}")
                    return None
                else:
                    logger.error(f"OpenAI HTTP error {e.response.status_code}: {e.response.text}")
                    raise
            except httpx.TimeoutException:
                logger.error("OpenAI request timed out")
                raise
    
    def _parse_analysis_result(self, analysis_data: Dict[str, Any]) -> Optional[AnalysisResult]:
        """Parse and validate analysis result from GPT"""
        
        try:
            # Validate required fields
            required_fields = ["overall_score", "scores", "strengths", "weaknesses", "recommendations"]
            for field in required_fields:
                if field not in analysis_data:
                    logger.error(f"Missing required field in analysis: {field}")
                    return None
            
            # Extract and validate scores
            overall_score = float(analysis_data.get("overall_score", 0))
            scores = analysis_data.get("scores", {})
            
            # Ensure scores are valid
            if not isinstance(scores, dict):
                logger.error("Scores must be a dictionary")
                return None
            
            for key, value in scores.items():
                try:
                    scores[key] = max(0.0, min(100.0, float(value)))
                except (ValueError, TypeError):
                    logger.warning(f"Invalid score value for {key}: {value}")
                    scores[key] = 0.0
            
            # Validate overall score
            overall_score = max(0.0, min(100.0, overall_score))
            
            # Extract other fields with defaults
            result = AnalysisResult(
                overall_score=overall_score,
                scores=scores,
                strengths=analysis_data.get("strengths", []),
                weaknesses=analysis_data.get("weaknesses", []),
                recommendations=analysis_data.get("recommendations", []),
                key_phrases=analysis_data.get("key_phrases", []),
                missed_opportunities=analysis_data.get("missed_opportunities", []),
                follow_up_required=analysis_data.get("follow_up_required", False),
                client_sentiment=analysis_data.get("client_sentiment", "neutral"),
                call_outcome=analysis_data.get("call_outcome", "unknown"),
                summary=analysis_data.get("summary", "Анализ завершен"),
                confidence=analysis_data.get("confidence", 0.8)
            )
            
            logger.info(f"Analysis result parsed", overall_score=result.overall_score)
            return result
            
        except Exception as e:
            logger.error(f"Failed to parse analysis result: {e}")
            return None
    
    async def get_key_points(self, transcription: str) -> List[str]:
        """Extract key points from transcription"""
        
        if not transcription:
            return []
        
        prompt = f"""
        Извлеки ключевые моменты из этой расшифровки телефонного разговора.
        Верни список из 5-7 самых важных моментов в формате JSON.
        
        Формат ответа:
        {{
            "key_points": ["момент 1", "момент 2", ...]
        }}
        
        Расшифровка:
        {transcription[:2000]}  # Ограничиваем длину
        """
        
        messages = [
            {"role": "system", "content": "Ты эксперт по анализу разговоров."},
            {"role": "user", "content": prompt}
        ]
        
        try:
            result = await self._make_openai_request(messages)
            if result and "key_points" in result:
                return result["key_points"][:7]  # Максимум 7 пунктов
        except Exception as e:
            logger.error(f"Failed to extract key points: {e}")
        
        return []
    
    async def identify_objections(self, transcription: str) -> List[Dict[str, Any]]:
        """Identify and analyze objections in the call"""
        
        if not transcription:
            return []
        
        prompt = SPECIAL_PROMPTS["extract_objections"] + f"\n\nРАСШИФРОВКА:\n{transcription}"
        
        messages = [
            {"role": "system", "content": SYSTEM_INSTRUCTIONS["general"]},
            {"role": "user", "content": prompt}
        ]
        
        try:
            result = await self._make_openai_request(messages)
            if result and "objections" in result:
                return result["objections"]
        except Exception as e:
            logger.error(f"Failed to identify objections: {e}")
        
        return []
    
    async def evaluate_manager_performance(
        self,
        transcription: str,
        focus_areas: Optional[List[str]] = None
    ) -> Dict[str, float]:
        """Evaluate specific aspects of manager performance"""
        
        if not transcription:
            return {}
        
        focus_areas = focus_areas or [
            "профессионализм", "коммуникативные навыки", "знание продукта",
            "работа с возражениями", "закрытие сделки"
        ]
        
        focus_list = ", ".join(focus_areas)
        
        prompt = f"""
        Оцени менеджера по следующим критериям: {focus_list}
        Дай оценку по каждому критерию от 0 до 100 баллов.
        
        Формат ответа:
        {{
            "evaluations": {{
                "критерий1": балл,
                "критерий2": балл,
                ...
            }}
        }}
        
        Расшифровка:
        {transcription[:2000]}
        """
        
        messages = [
            {"role": "system", "content": "Ты эксперт по оценке работы менеджеров по продажам."},
            {"role": "user", "content": prompt}
        ]
        
        try:
            result = await self._make_openai_request(messages)
            if result and "evaluations" in result:
                return result["evaluations"]
        except Exception as e:
            logger.error(f"Failed to evaluate performance: {e}")
        
        return {}
    
    async def suggest_improvements(self, transcription: str) -> List[str]:
        """Generate improvement suggestions"""
        
        if not transcription:
            return []
        
        prompt = f"""
        Проанализируй этот разговор и дай 3-5 конкретных рекомендаций по улучшению.
        Рекомендации должны быть практичными и применимыми.
        
        Формат ответа:
        {{
            "improvements": ["рекомендация 1", "рекомендация 2", ...]
        }}
        
        Расшифровка:
        {transcription[:2000]}
        """
        
        messages = [
            {"role": "system", "content": "Ты опытный тренер по продажам."},
            {"role": "user", "content": prompt}
        ]
        
        try:
            result = await self._make_openai_request(messages)
            if result and "improvements" in result:
                return result["improvements"][:5]
        except Exception as e:
            logger.error(f"Failed to generate improvements: {e}")
        
        return []
    
    async def batch_analyze(
        self,
        transcriptions: List[str],
        call_type: str = "general"
    ) -> List[Optional[AnalysisResult]]:
        """Analyze multiple calls in batch"""
        
        logger.info(f"Starting batch analysis", count=len(transcriptions))
        
        results = []
        for i, transcription in enumerate(transcriptions):
            logger.info(f"Analyzing call {i+1}/{len(transcriptions)}")
            
            result = await self.analyze_call(transcription, call_type)
            results.append(result)
            
            # Small delay to avoid rate limiting
            if i < len(transcriptions) - 1:
                await asyncio.sleep(0.5)
        
        successful = sum(1 for r in results if r is not None)
        logger.info(f"Batch analysis completed", successful=successful, total=len(transcriptions))
        
        return results
    
    async def health_check(self) -> bool:
        """Check if OpenAI API is accessible"""
        if not self.settings.openai_api_key:
            return False
        
        try:
            test_messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say 'OK' in JSON format: {\"status\": \"OK\"}"}
            ]
            
            result = await self._make_openai_request(test_messages)
            return result is not None and result.get("status") == "OK"
            
        except Exception as e:
            logger.error(f"OpenAI health check failed: {e}")
            return False