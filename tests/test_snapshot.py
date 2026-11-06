import sys
import unittest
import shutil
import tempfile
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import updateSnapshot as snapshot


class SnapshotScopeTests(unittest.TestCase):
    def test_generated_card_contains_metrics_and_partial_annotation(self):
        repo = {'private': True, 'languages_url': 'private-url',
                'stargazers_count': 0, 'forks_count': 0, 'name': 'private-name'}
        values = {'lines_changed': {'display': '1,234*'}, 'views': {'display': '—'}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(snapshot.ROOT / 'templates', root / 'templates')
            with patch.object(snapshot, 'ROOT', root), patch.object(snapshot, 'INCLUDE_PRIVATE', True), patch.object(snapshot, 'snapshot_repos', return_value=[repo]), patch.object(snapshot, 'github_get', return_value={f'Language {i}': i for i in range(1, 13)}), patch.object(snapshot, 'collect_metrics', return_value=values), patch.object(snapshot, 'contributions', return_value='10'), patch.object(snapshot, 'repositories_with_contributions', return_value='7'):
                snapshot.main()
            content = (root / 'img/snapshot/overview.svg').read_text()
            ET.fromstring(content)
            self.assertIn('1,234*', content)
            self.assertIn('Repositories with contributions</td><td>7</td>', content)
            self.assertIn('* Partial total', content)
            self.assertIn('— Unavailable', content)
            self.assertNotIn('private-name', content)
            self.assertNotIn('private-url', content)
            languages = (root / 'img/snapshot/languages.svg').read_text()
            overview_root = ET.fromstring(content)
            languages_root = ET.fromstring(languages)
            self.assertEqual(overview_root.attrib['height'], '250')
            self.assertEqual(languages_root.attrib['height'], '250')
            self.assertEqual(languages.count('class="lang"'), 10)
            self.assertNotIn('>Other<', languages)
            percentages = [float(value) for value in re.findall(r'class="percent">([0-9.]+)%', languages)]
            self.assertAlmostEqual(sum(percentages), 100, delta=0.06)
            self.assertIn('Equal weight per repository', languages)
            for i in range(3, 13):
                self.assertIn(f'>Language {i}<', languages)

    def test_fewer_than_ten_languages_remain_visible(self):
        sizes = Counter({f'Language {i}': i for i in range(1, 10)})
        rows = snapshot.language_rows(sizes)
        self.assertEqual(len(rows), 9)
        self.assertEqual(rows, sizes.most_common())
        self.assertNotIn('Other', dict(rows))
        self.assertEqual(sum(size for _, size in rows), sum(sizes.values()))

    def test_empty_and_zero_byte_languages(self):
        sizes = Counter({f'Language {i}': i for i in range(1, 7)})
        self.assertEqual(snapshot.language_rows(sizes), sizes.most_common())
        self.assertEqual(snapshot.language_rows(Counter()), [])
        self.assertEqual(snapshot.language_rows(Counter({'Python': 10, 'Empty': 0})), [('Python', 10)])

    def test_large_repository_does_not_dominate(self):
        scores = snapshot.balanced_language_scores(
            [{'Java': 1000000000}] + [{'TypeScript': 1000}] * 4
        )
        self.assertEqual(scores, Counter({'Java': 1, 'TypeScript': 4}))
        self.assertEqual(scores['Java'] / sum(scores.values()), 0.2)

    def test_language_scores_preserve_mix_within_each_repo(self):
        scores = snapshot.balanced_language_scores([
            {'TypeScript': 750, 'CSS': 250}, {'Python': 1000000}, {}, {'Empty': 0}
        ])
        self.assertEqual(scores, Counter({'Python': 1, 'TypeScript': 0.75, 'CSS': 0.25}))
        self.assertEqual(sum(scores.values()), 2)

    def test_only_top_ten_with_deterministic_ties_and_no_other(self):
        scores = Counter({f'Language {i:02}': 1 for i in reversed(range(12))})
        rows = snapshot.language_rows(scores)
        self.assertEqual(len(rows), 10)
        self.assertEqual([name for name, _ in rows], [f'Language {i:02}' for i in range(10)])
        self.assertNotIn('Other', dict(rows))

    def test_invalid_language_data_is_not_silently_used(self):
        for value in [{'Java': -1}, {'Java': '10'}, []]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                snapshot.balanced_language_scores([value])

    def test_public_mode_excludes_private_and_forks(self):
        repos = [{'id': 1}, {'id': 2, 'private': True}, {'id': 3, 'fork': True}]
        with patch.object(snapshot, 'INCLUDE_PRIVATE', False), patch.object(snapshot, 'fetch_repos', return_value=repos), patch.object(snapshot, 'github_get') as request:
            self.assertEqual([r['id'] for r in snapshot.snapshot_repos()], [1])
            request.assert_not_called()

    def test_private_mode_paginates_deduplicates_and_excludes_forks(self):
        first = [{'id': i, 'private': True} for i in range(100, 200)]
        second = [{'id': 100, 'private': True}, {'id': 200, 'private': True},
                  {'id': 201, 'private': True, 'fork': True}, {'id': 202, 'private': False}]
        with patch.object(snapshot, 'INCLUDE_PRIVATE', True), patch.object(snapshot, 'ACCESS_TOKEN', 'test-token'), patch.object(snapshot, 'fetch_repos', return_value=[{'id': 1}]), patch.object(snapshot, 'github_get', side_effect=[first, second]) as request:
            repos = snapshot.snapshot_repos()
            self.assertEqual(len(repos), 102)
            self.assertNotIn(201, [r['id'] for r in repos])
            self.assertNotIn(202, [r['id'] for r in repos])
            self.assertIn('page=2', request.call_args.args[0])
            self.assertIn('/user/repos?', request.call_args.args[0])

    def test_private_api_failure_does_not_silently_fall_back(self):
        with patch.object(snapshot, 'INCLUDE_PRIVATE', True), patch.object(snapshot, 'ACCESS_TOKEN', 'test-token'), patch.object(snapshot, 'fetch_repos', return_value=[]), patch.object(snapshot, 'github_get', side_effect=RuntimeError('denied')):
            with self.assertRaises(RuntimeError):
                snapshot.snapshot_repos()

    def test_private_mode_requires_token(self):
        with patch.object(snapshot, 'INCLUDE_PRIVATE', True), patch.object(snapshot, 'ACCESS_TOKEN', ''), patch.object(snapshot, 'fetch_repos', return_value=[]):
            with self.assertRaises(ValueError):
                snapshot.snapshot_repos()


if __name__ == '__main__':
    unittest.main()
