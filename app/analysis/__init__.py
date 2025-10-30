"""
Call analysis module
GPT-based analysis, prompts, and caching

Чтобы избежать циклических импортов, импортируйте напрямую:
    from app.analysis.analyzer import CallAnalyzer, AnalysisResult
    from app.analysis.call_quality_scorer import call_quality_scorer
    from app.analysis.commitment_tracker import commitment_tracker
"""

# Не импортируем автоматически, чтобы избежать циклических зависимостей
# from .analyzer import CallAnalyzer, AnalysisResult
# from .prompts import ANALYSIS_PROMPTS
# from .cache import AnalysisCache