import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import requests
import snapshot_metrics as metrics

REPO = {'url': 'https://api.github.com/repos/example/secret-project'}


def response(status, data=None, headers=None):
    return Mock(status_code=status, headers=headers or {}, json=Mock(return_value=data))


class MetricTests(unittest.TestCase):
    def test_pending_retries_then_succeeds(self):
        with patch.object(metrics.requests, 'get', side_effect=[response(202), response(200, {'count': 3})]) as get, patch.object(metrics.time, 'sleep') as sleep:
            self.assertEqual(metrics.request_metric('url', {}), ({'count': 3}, ''))
            self.assertEqual(get.call_count, 2)
            sleep.assert_called_once_with(2)

    def test_pending_exhaustion_is_not_zero(self):
        with patch.object(metrics.requests, 'get', return_value=response(202)) as get, patch.object(metrics.time, 'sleep'):
            self.assertEqual(metrics.request_metric('url', {}), (None, 'pending'))
            self.assertEqual(get.call_count, 4)

    def test_denied_empty_and_rate_limit_responses(self):
        for status, headers, reason in [(401, {}, 'access_denied'), (403, {}, 'access_denied'), (404, {}, 'access_denied'), (204, {}, 'no_data'), (403, {'X-RateLimit-Remaining': '0'}, 'rate_limited'), (429, {}, 'rate_limited')]:
            with self.subTest(status=status, headers=headers), patch.object(metrics.requests, 'get', return_value=response(status, headers=headers)):
                self.assertEqual(metrics.request_metric('url', {}), (None, reason))

    def test_network_failure(self):
        with patch.object(metrics.requests, 'get', side_effect=requests.Timeout('private URL')):
            self.assertEqual(metrics.request_metric('url', {}), (None, 'network'))

    def test_counts_only_own_additions_and_deletions(self):
        data = [{'author': {'login': 'HELLOOCC'}, 'total': 2, 'weeks': [{'a': 10, 'd': 4}, {'a': 3, 'd': 2}]}, {'author': {'login': 'other'}, 'total': 1, 'weeks': [{'a': 999, 'd': 999}]}]
        with patch.object(metrics, 'request_metric', return_value=(data, '')):
            self.assertEqual(metrics.lines_changed(REPO, 'helloocc', {}).value, 19)

    def test_large_repository_zeroes_not_reported_as_zero(self):
        data = [{'author': {'login': 'helloocc'}, 'total': 10000, 'weeks': [{'a': 0, 'd': 0}]}]
        with patch.object(metrics, 'request_metric', return_value=(data, '')):
            result = metrics.lines_changed(REPO, 'helloocc', {})
            self.assertIsNone(result.value)
            self.assertEqual(result.reason, 'large_repository')

    def test_unknown_zero_changes_not_reported_as_zero(self):
        data = [{'author': {'login': 'helloocc'}, 'total': 1, 'weeks': [{'a': 0, 'd': 0}]}]
        with patch.object(metrics, 'request_metric', return_value=(data, '')):
            self.assertIsNone(metrics.lines_changed(REPO, 'helloocc', {}).value)

    def test_views_use_count_not_uniques(self):
        with patch.object(metrics, 'request_metric', return_value=({'count': 21, 'uniques': 5}, '')):
            self.assertEqual(metrics.repository_views(REPO, {}).value, 21)

    def test_valid_zero_and_invalid_data(self):
        for data, expected in [({'count': 0}, 0), ({}, None), ({'count': -1}, None), ({'count': '3'}, None)]:
            with self.subTest(data=data), patch.object(metrics, 'request_metric', return_value=(data, '')):
                self.assertEqual(metrics.repository_views(REPO, {}).value, expected)

    def test_partial_all_missing_and_complete_totals(self):
        self.assertEqual(metrics.summarize([metrics.Metric(0)])['display'], '0')
        self.assertEqual(metrics.summarize([metrics.Metric(1234), metrics.Metric(5)])['display'], '1,239')
        self.assertEqual(metrics.summarize([metrics.Metric(1234), metrics.Metric(reason='pending')])['display'], '1,234*')
        self.assertEqual(metrics.summarize([metrics.Metric(reason='access_denied')])['display'], '—')

    def test_logs_do_not_include_private_names(self):
        output = io.StringIO()
        with patch.object(metrics, 'lines_changed', return_value=metrics.Metric(8)), patch.object(metrics, 'repository_views', return_value=metrics.Metric(reason='access_denied')), redirect_stdout(output):
            result = metrics.collect_metrics([REPO], 'helloocc', {})
        self.assertEqual(result['lines_changed']['display'], '8')
        self.assertIn('access_denied=1', output.getvalue())
        self.assertNotIn('secret-project', output.getvalue())


if __name__ == '__main__':
    unittest.main()
