"""
Call Quality Scoring System
Автоматическая оценка качества звонков по чек-листу критериев
"""

from typing import Dict, Any, List
from datetime import datetime
import structlog
import json

from ..config import get_settings
from ..utils.helpers import retry_async
from ..utils.api_budget import api_budget, BudgetExceededError
import httpx

logger = structlog.get_logger("salesbot.analysis.call_quality_scorer")


class CallQualityScorer:
    """Оценивает качество звонка по набору критериев"""

    # Чек-лист критериев оценки
    QUALITY_CHECKLIST = {
        'greeting': {
            'weight': 5,
            'criteria': 'Поздоровался, представился, назвал компанию',
            'description': 'Правильное начало разговора'
        },
        'need_identification': {
            'weight': 15,
            'criteria': 'Задал 3+ открытых вопроса о потребностях клиента',
            'description': 'Выявление потребностей'
        },
        'active_listening': {
            'weight': 10,
            'criteria': 'Перефразировал слова клиента, подтвердил понимание',
            'description': 'Активное слушание'
        },
        'value_proposition': {
            'weight': 15,
            'criteria': 'Представил решение через выгоды для клиента, а не через характеристики',
            'description': 'Презентация ценности'
        },
        'objection_handling': {
            'weight': 15,
            'criteria': 'Правильно отработал возражения (не спорил, признал, предложил альтернативу)',
            'description': 'Работа с возражениями'
        },
        'next_step': {
            'weight': 20,
            'criteria': 'Договорился о конкретном следующем шаге с четкой датой и временем',
            'description': 'Следующий шаг'
        },
        'tone_professionalism': {
            'weight': 10,
            'criteria': 'Дружелюбный профессиональный тон, без слов-паразитов',
            'description': 'Тон и профессионализм'
        },
        'call_control': {
            'weight': 10,
            'criteria': 'Управлял беседой, не дал увести разговор в сторону',
            'description': 'Контроль разговора'
        }
    }

    def __init__(self):
        self.settings = get_settings()

    async def score_call(
        self,
        transcription: str,
        call_type: str = "general",
        call_duration: int = 0
    ) -> Dict[str, Any]:
        """
        Оценить качество звонка по всем критериям ОДНИМ запросом (экономия 8x)

        Args:
            transcription: Текст разговора
            call_type: Тип звонка (cold_call, follow_up, etc)
            call_duration: Длительность в секундах

        Returns:
            Dict с оценками по каждому критерию и общей оценкой
        """
        logger.info("Scoring call quality", call_type=call_type, duration=call_duration)

        if not transcription or len(transcription.strip()) < 50:
            logger.warning("Transcription too short for quality scoring")
            return self._get_default_score("Транскрипция слишком короткая")

        # Check budget before expensive operation
        allowed, reason = api_budget.can_make_request(0.10)  # gpt-4 is expensive
        if not allowed:
            logger.error(f"Budget exceeded: {reason}")
            return self._get_default_score(f"Бюджет исчерпан: {reason}")

        try:
            # ОПТИМИЗАЦИЯ: Один запрос вместо 8!
            all_scores = await self._evaluate_all_criteria_single_request(
                transcription, call_type
            )

            if not all_scores:
                return self._get_default_score("Ошибка анализа")

            # Построить результаты из единого ответа
            results = {}
            for criterion_code, criterion_config in self.QUALITY_CHECKLIST.items():
                score = all_scores.get(criterion_code, 50)  # Default 50 if missing
                results[criterion_code] = {
                    'score': score,
                    'weight': criterion_config['weight'],
                    'weighted_score': score * criterion_config['weight'] / 100,
                    'description': criterion_config['description']
                }

            # Вычислить общую оценку
            total_score = sum(r['weighted_score'] for r in results.values())
            grade = self._get_grade(total_score)

            # Определить сильные и слабые стороны
            strengths = self._identify_strong_points(results)
            weaknesses = self._identify_weak_points(results)
            critical_issues = self._identify_critical_issues(results)

            # Рекомендации из того же ответа (если есть)
            recommendations = all_scores.get('recommendations', [])
            if not recommendations:
                recommendations = ["Изучите лучшие практики для данного типа звонков"]

            return {
                'total_score': round(total_score, 1),
                'grade': grade,
                'breakdown': results,
                'strengths': strengths,
                'weaknesses': weaknesses,
                'critical_issues': critical_issues,
                'recommendations': recommendations,
                'call_duration': call_duration,
                'call_type': call_type,
                'evaluated_at': datetime.utcnow().isoformat()
            }

        except BudgetExceededError as e:
            logger.error(f"Budget exceeded: {e}")
            return self._get_default_score(f"Бюджет исчерпан")
        except Exception as e:
            logger.error(f"Failed to score call: {e}")
            return self._get_default_score(f"Ошибка: {str(e)}")

    async def _evaluate_all_criteria_single_request(
        self,
        transcription: str,
        call_type: str
    ) -> Optional[Dict[str, Any]]:
        """Оценить ВСЕ критерии ОДНИМ запросом - экономия 8x!"""

        criteria_list = "\n".join([
            f"- {code}: {config['criteria']} (вес: {config['weight']}%)"
            for code, config in self.QUALITY_CHECKLIST.items()
        ])

        prompt = f"""
Оцени разговор продажника по ВСЕМ критериям сразу.

Тип звонка: {call_type}

КРИТЕРИИ ОЦЕНКИ:
{criteria_list}

РАЗГОВОР:
{transcription[:4000]}

Верни JSON с оценками по каждому критерию (0-100) и рекомендациями:
{{
    "greeting": число 0-100,
    "need_identification": число 0-100,
    "active_listening": число 0-100,
    "value_proposition": число 0-100,
    "objection_handling": число 0-100,
    "next_step": число 0-100,
    "tone_professionalism": число 0-100,
    "call_control": число 0-100,
    "recommendations": ["рекомендация 1", "рекомендация 2", "рекомендация 3"]
}}

Шкала оценок:
0-40 = Плохо / Не выполнено
41-60 = Удовлетворительно
61-80 = Хорошо
81-100 = Отлично
"""

        try:
            response = await self._call_gpt(prompt, max_tokens=500, temperature=0.3)

            # Parse JSON response
            try:
                # Remove markdown code blocks if present
                response = response.strip()
                if response.startswith("```json"):
                    response = response[7:]
                if response.startswith("```"):
                    response = response[3:]
                if response.endswith("```"):
                    response = response[:-3]

                result = json.loads(response.strip())

                # Validate scores are in range
                for key in self.QUALITY_CHECKLIST.keys():
                    if key in result:
                        result[key] = max(0, min(100, int(result[key])))

                return result

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse GPT response as JSON: {e}")
                return None

        except Exception as e:
            logger.error(f"Failed to evaluate all criteria: {e}")
            return None

    async def _evaluate_criterion(
        self,
        transcription: str,
        criterion: str,
        criteria_description: str,
        call_type: str
    ) -> float:
        """Оценить один критерий используя AI"""

        prompt = f"""
Оцени разговор продажника по критерию: "{criteria_description}"

Тип звонка: {call_type}

Разговор:
{transcription[:3000]}

Оцени от 0 до 100, где:
0-40 = Не выполнено / Плохо
41-60 = Частично выполнено / Удовлетворительно
61-80 = Хорошо выполнено
81-100 = Отлично выполнено

Критерий: {criteria_description}

Верни ТОЛЬКО число от 0 до 100, без объяснений.
"""

        try:
            response = await self._call_gpt(prompt, max_tokens=10, temperature=0.3)
            score_text = response.strip()

            # Извлечь число
            import re
            numbers = re.findall(r'\d+', score_text)
            if numbers:
                score = int(numbers[0])
                return min(100, max(0, score))  # Ограничить 0-100
            else:
                logger.warning(f"Could not extract score from: {score_text}")
                return 50  # Default

        except Exception as e:
            logger.error(f"Failed to evaluate criterion {criterion}: {e}")
            return 50  # Default на случай ошибки

    def _get_grade(self, score: float) -> str:
        """Преобразовать числовую оценку в буквенную"""
        if score >= 90:
            return 'A'
        elif score >= 80:
            return 'B'
        elif score >= 70:
            return 'C'
        elif score >= 60:
            return 'D'
        else:
            return 'F'

    def _identify_strong_points(self, results: Dict) -> List[Dict[str, Any]]:
        """Определить сильные стороны (оценка >= 80)"""
        strengths = []
        for criterion, data in results.items():
            if data['score'] >= 80:
                strengths.append({
                    'criterion': criterion,
                    'description': data['description'],
                    'score': data['score']
                })

        # Сортировать по оценке
        strengths.sort(key=lambda x: x['score'], reverse=True)
        return strengths[:3]  # Топ-3

    def _identify_weak_points(self, results: Dict) -> List[Dict[str, Any]]:
        """Определить слабые стороны (60 < оценка < 80)"""
        weaknesses = []
        for criterion, data in results.items():
            if 60 < data['score'] < 80:
                weaknesses.append({
                    'criterion': criterion,
                    'description': data['description'],
                    'score': data['score']
                })

        weaknesses.sort(key=lambda x: x['score'])
        return weaknesses[:3]  # Топ-3

    def _identify_critical_issues(self, results: Dict) -> List[Dict[str, Any]]:
        """Определить критические проблемы (оценка <= 60)"""
        critical = []
        for criterion, data in results.items():
            if data['score'] <= 60:
                critical.append({
                    'criterion': criterion,
                    'description': data['description'],
                    'score': data['score']
                })

        critical.sort(key=lambda x: x['score'])
        return critical

    async def _generate_recommendations(
        self,
        results: Dict,
        weaknesses: List,
        critical_issues: List,
        call_type: str
    ) -> List[str]:
        """Генерировать рекомендации по улучшению"""

        if not weaknesses and not critical_issues:
            return ["Отличная работа! Продолжайте в том же духе."]

        # Собрать проблемные области
        issues = []
        for issue in critical_issues + weaknesses:
            issues.append(f"- {issue['description']}: {issue['score']}/100")

        prompt = f"""
Менеджер провел {call_type} звонок.

Проблемные области:
{chr(10).join(issues)}

Дай 3-4 КОНКРЕТНЫХ рекомендации как улучшить эти аспекты.
Каждая рекомендация должна быть практичной и применимой сразу.

Формат: список из 3-4 пунктов, каждый на новой строке, начинается с "•"
"""

        try:
            response = await self._call_gpt(prompt, max_tokens=300, temperature=0.7)

            # Парсить рекомендации
            recommendations = []
            for line in response.split('\n'):
                line = line.strip()
                if line and (line.startswith('•') or line.startswith('-') or line[0].isdigit()):
                    # Очистить от маркеров
                    clean_line = line.lstrip('•-0123456789. ')
                    if clean_line:
                        recommendations.append(clean_line)

            return recommendations[:4] if recommendations else ["Изучите лучшие практики для данного типа звонков"]

        except Exception as e:
            logger.error(f"Failed to generate recommendations: {e}")
            return ["Требуется дополнительное обучение"]

    async def _call_gpt(self, prompt: str, max_tokens: int = 500, temperature: float = 0.3) -> str:
        """Вызвать GPT API с бюджетной защитой"""

        if not self.settings.openai_api_key:
            raise ValueError("OpenAI API key not configured")

        # Budget check
        allowed, reason = api_budget.can_make_request(0.10)
        if not allowed:
            raise BudgetExceededError(reason)

        # Get model from runtime settings (can be changed via admin panel)
        from ..utils.runtime_settings import runtime_settings
        model = await runtime_settings.get_model()

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.settings.openai_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Ты эксперт по оценке качества продаж. Даешь объективные оценки. Отвечай кратко."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "max_tokens": max_tokens,
                    "temperature": temperature
                }
            )

            response.raise_for_status()
            result = response.json()

            # Track cost
            usage = result.get("usage", {})
            if usage:
                await api_budget.record_request(
                    model=model,
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    request_type="quality_scoring"
                )

            return result['choices'][0]['message']['content'].strip()

    def _get_default_score(self, error_message: str = None) -> Dict[str, Any]:
        """Получить дефолтную оценку при ошибке"""
        return {
            'total_score': 0,
            'grade': 'N/A',
            'breakdown': {},
            'strengths': [],
            'weaknesses': [],
            'critical_issues': [],
            'recommendations': [],
            'error': error_message,
            'evaluated_at': datetime.utcnow().isoformat()
        }


# Global instance
call_quality_scorer = CallQualityScorer()
