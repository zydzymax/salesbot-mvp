"""
Тесты для Manager Dashboard
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

from app.analytics.manager_dashboard import ManagerDashboard, ManagerKPI


@pytest.fixture
def dashboard():
    """Фикстура для создания экземпляра ManagerDashboard"""
    return ManagerDashboard()


@pytest.fixture
def sample_kpi_data():
    """Пример KPI данных"""
    return {
        'manager_id': 1,
        'manager_name': 'Иван Иванов',
        'calls_made': 50,
        'calls_answered': 45,
        'avg_call_duration': 180,
        'response_time_avg_hours': 2.5,
        'avg_quality_score': 75.5,
        'calls_with_quality_score': 40,
        'total_commitments': 20,
        'fulfilled_commitments': 18,
        'overdue_commitments': 2,
        'commitment_fulfillment_rate': 90.0,
        'suspicious_activity_score': 0.1,
        'red_flags_count': 0,
        'period_start': (datetime.utcnow() - timedelta(days=7)).isoformat(),
        'period_end': datetime.utcnow().isoformat(),
        'calculated_at': datetime.utcnow().isoformat()
    }


class TestManagerDashboard:
    """Тесты для дашборда менеджеров"""

    @pytest.mark.asyncio
    @patch('app.analytics.manager_dashboard.db_manager')
    async def test_get_calls_metrics(self, mock_db, dashboard):
        """Тест: получение метрик по звонкам"""
        # Мокаем звонки
        from collections import namedtuple
        MockCall = namedtuple('Call', ['id', 'manager_id', 'duration', 'created_at'])

        mock_calls = [
            MockCall(1, 1, 120, datetime.now()),
            MockCall(2, 1, 180, datetime.now()),
            MockCall(3, 1, 150, datetime.now()),
            MockCall(4, 1, 5, datetime.now()),  # Короткий
            MockCall(5, 1, None, datetime.now()),  # Без длительности
        ]

        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = mock_calls
        mock_session.execute.return_value = mock_result
        mock_db.get_session.return_value.__aenter__.return_value = mock_session

        from_date = datetime.now() - timedelta(days=7)
        to_date = datetime.now()

        result = await dashboard._get_calls_metrics(1, from_date, to_date)

        assert result['total_calls'] == 5
        assert result['answered_calls'] == 3  # Только звонки > 5 сек
        assert result['avg_duration'] > 0

    @pytest.mark.asyncio
    @patch('app.analytics.manager_dashboard.db_manager')
    async def test_get_quality_metrics(self, mock_db, dashboard):
        """Тест: получение метрик качества"""
        from collections import namedtuple
        MockCall = namedtuple('Call', ['id', 'quality_score'])

        mock_calls = [
            MockCall(1, 80.0),
            MockCall(2, 75.0),
            MockCall(3, 85.0),
        ]

        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = mock_calls
        mock_session.execute.return_value = mock_result
        mock_db.get_session.return_value.__aenter__.return_value = mock_session

        from_date = datetime.now() - timedelta(days=7)
        to_date = datetime.now()

        result = await dashboard._get_quality_metrics(1, from_date, to_date)

        assert result['scored_calls'] == 3
        assert result['avg_score'] == 80.0

    @pytest.mark.asyncio
    @patch('app.analytics.manager_dashboard.db_manager')
    async def test_get_quality_metrics_no_scores(self, mock_db, dashboard):
        """Тест: нет оценок качества"""
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_db.get_session.return_value.__aenter__.return_value = mock_session

        from_date = datetime.now() - timedelta(days=7)
        to_date = datetime.now()

        result = await dashboard._get_quality_metrics(1, from_date, to_date)

        assert result['avg_score'] == 0
        assert result['scored_calls'] == 0

    @pytest.mark.asyncio
    @patch('app.analytics.manager_dashboard.db_manager')
    async def test_get_commitments_metrics(self, mock_db, dashboard):
        """Тест: получение метрик по обещаниям"""
        from collections import namedtuple
        MockCommitment = namedtuple('Commitment', ['id', 'is_fulfilled', 'is_overdue'])

        mock_commitments = [
            MockCommitment(1, True, False),
            MockCommitment(2, True, False),
            MockCommitment(3, True, False),
            MockCommitment(4, False, True),  # Просрочено
            MockCommitment(5, False, False),  # Не выполнено, но не просрочено
        ]

        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = mock_commitments
        mock_session.execute.return_value = mock_result
        mock_db.get_session.return_value.__aenter__.return_value = mock_session

        from_date = datetime.now() - timedelta(days=7)
        to_date = datetime.now()

        result = await dashboard._get_commitments_metrics(1, from_date, to_date)

        assert result['total'] == 5
        assert result['fulfilled'] == 3
        assert result['overdue'] == 1
        assert result['fulfillment_rate'] == 60.0

    @pytest.mark.asyncio
    @patch('app.analytics.manager_dashboard.db_manager')
    async def test_get_commitments_metrics_no_commitments(self, mock_db, dashboard):
        """Тест: нет обещаний"""
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_db.get_session.return_value.__aenter__.return_value = mock_session

        from_date = datetime.now() - timedelta(days=7)
        to_date = datetime.now()

        result = await dashboard._get_commitments_metrics(1, from_date, to_date)

        assert result['total'] == 0
        assert result['fulfilled'] == 0
        assert result['overdue'] == 0
        assert result['fulfillment_rate'] == 0

    @pytest.mark.asyncio
    @patch('app.fraud.activity_validator.activity_validator.detect_suspicious_activity')
    async def test_get_fraud_metrics(self, mock_detect, dashboard):
        """Тест: получение метрик подозрительности"""
        mock_detect.return_value = {
            'confidence': 0.3,
            'red_flags_count': 2
        }

        result = await dashboard._get_fraud_metrics(1, 7)

        assert result['suspicion_score'] == 0.3
        assert result['red_flags_count'] == 2

    @pytest.mark.asyncio
    @patch('app.fraud.activity_validator.activity_validator.detect_suspicious_activity')
    async def test_get_fraud_metrics_error(self, mock_detect, dashboard):
        """Тест: ошибка при получении метрик подозрительности"""
        mock_detect.return_value = {'error': 'Test error'}

        result = await dashboard._get_fraud_metrics(1, 7)

        assert result['suspicion_score'] == 0
        assert result['red_flags_count'] == 0

    @pytest.mark.asyncio
    async def test_get_leaderboard_quality(self, dashboard):
        """Тест: рейтинг по качеству"""
        team_kpi = [
            {'manager_id': 1, 'manager_name': 'Иван', 'avg_quality_score': 90, 'calls_made': 50, 'commitment_fulfillment_rate': 80},
            {'manager_id': 2, 'manager_name': 'Петр', 'avg_quality_score': 75, 'calls_made': 60, 'commitment_fulfillment_rate': 90},
            {'manager_id': 3, 'manager_name': 'Мария', 'avg_quality_score': 85, 'calls_made': 55, 'commitment_fulfillment_rate': 85},
        ]

        with patch.object(dashboard, 'get_team_comparison', return_value=team_kpi):
            result = await dashboard.get_leaderboard(7, 'quality')

        assert len(result) == 3
        assert result[0]['manager_name'] == 'Иван'
        assert result[0]['position'] == 1
        assert result[1]['manager_name'] == 'Мария'
        assert result[1]['position'] == 2
        assert result[2]['manager_name'] == 'Петр'
        assert result[2]['position'] == 3

    @pytest.mark.asyncio
    async def test_get_leaderboard_activity(self, dashboard):
        """Тест: рейтинг по активности"""
        team_kpi = [
            {'manager_id': 1, 'manager_name': 'Иван', 'avg_quality_score': 90, 'calls_made': 50, 'commitment_fulfillment_rate': 80},
            {'manager_id': 2, 'manager_name': 'Петр', 'avg_quality_score': 75, 'calls_made': 70, 'commitment_fulfillment_rate': 90},
            {'manager_id': 3, 'manager_name': 'Мария', 'avg_quality_score': 85, 'calls_made': 60, 'commitment_fulfillment_rate': 85},
        ]

        with patch.object(dashboard, 'get_team_comparison', return_value=team_kpi):
            result = await dashboard.get_leaderboard(7, 'activity')

        assert result[0]['manager_name'] == 'Петр'
        assert result[0]['position'] == 1

    @pytest.mark.asyncio
    async def test_get_leaderboard_commitments(self, dashboard):
        """Тест: рейтинг по выполнению обещаний"""
        team_kpi = [
            {'manager_id': 1, 'manager_name': 'Иван', 'avg_quality_score': 90, 'calls_made': 50, 'commitment_fulfillment_rate': 80},
            {'manager_id': 2, 'manager_name': 'Петр', 'avg_quality_score': 75, 'calls_made': 70, 'commitment_fulfillment_rate': 95},
            {'manager_id': 3, 'manager_name': 'Мария', 'avg_quality_score': 85, 'calls_made': 60, 'commitment_fulfillment_rate': 85},
        ]

        with patch.object(dashboard, 'get_team_comparison', return_value=team_kpi):
            result = await dashboard.get_leaderboard(7, 'commitments')

        assert result[0]['manager_name'] == 'Петр'
        assert result[0]['position'] == 1

    @pytest.mark.asyncio
    async def test_get_alerts_low_quality(self, dashboard):
        """Тест: алерт о низком качестве"""
        kpi_low_quality = {
            'manager_id': 1,
            'manager_name': 'Иван',
            'avg_quality_score': 55.0,
            'calls_with_quality_score': 10,
            'overdue_commitments': 1,
            'suspicious_activity_score': 0.2,
            'red_flags_count': 0,
            'calls_made': 20
        }

        with patch('app.analytics.manager_dashboard.db_manager') as mock_db:
            # Мокаем получение менеджеров
            from collections import namedtuple
            MockManager = namedtuple('Manager', ['id', 'name'])
            mock_managers = [MockManager(1, 'Иван')]

            mock_session = AsyncMock()
            mock_db.get_session.return_value.__aenter__.return_value = mock_session

            with patch('app.database.crud.ManagerCRUD.get_active_managers', return_value=mock_managers):
                with patch.object(dashboard, 'get_manager_kpi', return_value=kpi_low_quality):
                    alerts = await dashboard.get_alerts()

        # Должен быть алерт о низком качестве
        low_quality_alerts = [a for a in alerts if a['type'] == 'low_quality']
        assert len(low_quality_alerts) > 0
        assert low_quality_alerts[0]['severity'] == 'high'

    @pytest.mark.asyncio
    async def test_get_alerts_overdue_commitments(self, dashboard):
        """Тест: алерт о просроченных обещаниях"""
        kpi_overdue = {
            'manager_id': 1,
            'manager_name': 'Иван',
            'avg_quality_score': 75.0,
            'calls_with_quality_score': 10,
            'overdue_commitments': 5,
            'suspicious_activity_score': 0.2,
            'red_flags_count': 0,
            'calls_made': 20
        }

        with patch('app.analytics.manager_dashboard.db_manager') as mock_db:
            from collections import namedtuple
            MockManager = namedtuple('Manager', ['id', 'name'])
            mock_managers = [MockManager(1, 'Иван')]

            mock_session = AsyncMock()
            mock_db.get_session.return_value.__aenter__.return_value = mock_session

            with patch('app.database.crud.ManagerCRUD.get_active_managers', return_value=mock_managers):
                with patch.object(dashboard, 'get_manager_kpi', return_value=kpi_overdue):
                    alerts = await dashboard.get_alerts()

        overdue_alerts = [a for a in alerts if a['type'] == 'overdue_commitments']
        assert len(overdue_alerts) > 0
        assert overdue_alerts[0]['severity'] == 'medium'

    @pytest.mark.asyncio
    async def test_get_alerts_suspicious_activity(self, dashboard):
        """Тест: алерт о подозрительной активности"""
        kpi_suspicious = {
            'manager_id': 1,
            'manager_name': 'Иван',
            'avg_quality_score': 75.0,
            'calls_with_quality_score': 10,
            'overdue_commitments': 1,
            'suspicious_activity_score': 0.7,
            'red_flags_count': 3,
            'calls_made': 20
        }

        with patch('app.analytics.manager_dashboard.db_manager') as mock_db:
            from collections import namedtuple
            MockManager = namedtuple('Manager', ['id', 'name'])
            mock_managers = [MockManager(1, 'Иван')]

            mock_session = AsyncMock()
            mock_db.get_session.return_value.__aenter__.return_value = mock_session

            with patch('app.database.crud.ManagerCRUD.get_active_managers', return_value=mock_managers):
                with patch.object(dashboard, 'get_manager_kpi', return_value=kpi_suspicious):
                    alerts = await dashboard.get_alerts()

        suspicious_alerts = [a for a in alerts if a['type'] == 'suspicious_activity']
        assert len(suspicious_alerts) > 0
        assert suspicious_alerts[0]['severity'] == 'high'

    @pytest.mark.asyncio
    async def test_get_alerts_no_activity(self, dashboard):
        """Тест: алерт об отсутствии активности"""
        kpi_no_activity = {
            'manager_id': 1,
            'manager_name': 'Иван',
            'avg_quality_score': 0,
            'calls_with_quality_score': 0,
            'overdue_commitments': 0,
            'suspicious_activity_score': 0,
            'red_flags_count': 0,
            'calls_made': 0
        }

        with patch('app.analytics.manager_dashboard.db_manager') as mock_db:
            from collections import namedtuple
            MockManager = namedtuple('Manager', ['id', 'name'])
            mock_managers = [MockManager(1, 'Иван')]

            mock_session = AsyncMock()
            mock_db.get_session.return_value.__aenter__.return_value = mock_session

            with patch('app.database.crud.ManagerCRUD.get_active_managers', return_value=mock_managers):
                with patch.object(dashboard, 'get_manager_kpi', return_value=kpi_no_activity):
                    alerts = await dashboard.get_alerts()

        no_activity_alerts = [a for a in alerts if a['type'] == 'no_activity']
        assert len(no_activity_alerts) > 0
        assert no_activity_alerts[0]['severity'] == 'high'

    @pytest.mark.asyncio
    async def test_get_alerts_sorting(self, dashboard):
        """Тест: сортировка алертов по приоритету"""
        kpi_multiple_issues = {
            'manager_id': 1,
            'manager_name': 'Иван',
            'avg_quality_score': 55.0,
            'calls_with_quality_score': 10,
            'overdue_commitments': 5,
            'suspicious_activity_score': 0.7,
            'red_flags_count': 3,
            'calls_made': 20
        }

        with patch('app.analytics.manager_dashboard.db_manager') as mock_db:
            from collections import namedtuple
            MockManager = namedtuple('Manager', ['id', 'name'])
            mock_managers = [MockManager(1, 'Иван')]

            mock_session = AsyncMock()
            mock_db.get_session.return_value.__aenter__.return_value = mock_session

            with patch('app.database.crud.ManagerCRUD.get_active_managers', return_value=mock_managers):
                with patch.object(dashboard, 'get_manager_kpi', return_value=kpi_multiple_issues):
                    alerts = await dashboard.get_alerts()

        # Проверяем, что high severity идут первыми
        if len(alerts) > 1:
            for i in range(len(alerts) - 1):
                current_severity = alerts[i]['severity']
                next_severity = alerts[i + 1]['severity']

                severity_order = {'high': 0, 'medium': 1, 'low': 2}
                assert severity_order[current_severity] <= severity_order[next_severity]

    @pytest.mark.asyncio
    async def test_generate_daily_report(self, dashboard):
        """Тест: генерация ежедневного отчета"""
        team_kpi = [
            {
                'manager_id': 1,
                'manager_name': 'Иван',
                'calls_made': 50,
                'avg_quality_score': 85
            },
            {
                'manager_id': 2,
                'manager_name': 'Петр',
                'calls_made': 40,
                'avg_quality_score': 75
            },
        ]

        with patch.object(dashboard, 'get_team_comparison', return_value=team_kpi):
            with patch.object(dashboard, 'get_alerts', return_value=[]):
                report = await dashboard.generate_daily_report()

        assert 'date' in report
        assert report['team_size'] == 2
        assert report['total_calls'] == 90
        assert report['avg_quality_score'] == 80.0
        assert len(report['top_performers']) <= 3
        assert 'alerts_count' in report
