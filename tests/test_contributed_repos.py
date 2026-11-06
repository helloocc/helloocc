import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import updateSnapshot as snapshot


def page(ids, private=(), next_cursor=None):
    return {'user': {'selected': {
        'nodes': [{'id': id, 'isPrivate': id in private} for id in ids],
        'pageInfo': {'hasNextPage': next_cursor is not None, 'endCursor': next_cursor},
    }}}


class ContributedRepositoryTests(unittest.TestCase):
    def test_union_deduplicates_and_paginates_connections_independently(self):
        responses = [page(['own', 'shared'], next_cursor='owned-2'), page(['private-own'], private=['private-own']),
                     page(['shared', 'external-fork'], next_cursor='contrib-2'), page(['private-contrib'], private=['private-contrib'])]
        with patch.object(snapshot, 'ACCESS_TOKEN', 'test'), patch.object(snapshot, 'INCLUDE_PRIVATE', True), patch.object(snapshot, 'graphql', side_effect=responses) as query:
            self.assertEqual(snapshot.repositories_with_contributions(), '5')
        self.assertEqual([call.args[1]['cursor'] for call in query.call_args_list], [None, 'owned-2', None, 'contrib-2'])
        self.assertIn('isFork: false', query.call_args_list[0].args[0])
        external_query = query.call_args_list[2].args[0]
        self.assertIn('includeUserRepositories: false', external_query)
        self.assertIn('[COMMIT, PULL_REQUEST, REPOSITORY, PULL_REQUEST_REVIEW]', external_query)
        self.assertNotIn('isFork: false', external_query)
        self.assertEqual(query.call_args.args[1]['login'], snapshot.USER_NAME)

    def test_public_mode_excludes_private_from_both_connections(self):
        responses = [page(['a', 'private-a'], private=['private-a']), page(['b', 'private-b'], private=['private-b'])]
        with patch.object(snapshot, 'ACCESS_TOKEN', 'test'), patch.object(snapshot, 'INCLUDE_PRIVATE', False), patch.object(snapshot, 'graphql', side_effect=responses):
            self.assertEqual(snapshot.repositories_with_contributions(), '2')

    def test_no_token_does_not_report_zero(self):
        with patch.object(snapshot, 'ACCESS_TOKEN', ''), patch.object(snapshot, 'graphql') as query:
            self.assertEqual(snapshot.repositories_with_contributions(), '—')
            query.assert_not_called()

    def test_legitimate_empty_union_is_zero(self):
        with patch.object(snapshot, 'ACCESS_TOKEN', 'test'), patch.object(snapshot, 'graphql', side_effect=[page([]), page([])]):
            self.assertEqual(snapshot.repositories_with_contributions(), '0')

    def test_failure_after_first_page_does_not_publish_partial_count_or_names(self):
        output = io.StringIO()
        with patch.object(snapshot, 'ACCESS_TOKEN', 'test'), patch.object(snapshot, 'graphql', side_effect=[page(['a'], next_cursor='next'), RuntimeError('private-repo-name')]), redirect_stdout(output):
            self.assertEqual(snapshot.repositories_with_contributions(), '—')
        self.assertNotIn('private-repo-name', output.getvalue())

    def test_repeated_cursor_or_null_node_is_not_a_complete_result(self):
        invalid = page([])
        invalid['user']['selected']['nodes'] = [None]
        for responses in [[page(['a'], next_cursor='repeat'), page(['b'], next_cursor='repeat')], [invalid]]:
            with self.subTest(responses=responses), patch.object(snapshot, 'ACCESS_TOKEN', 'test'), patch.object(snapshot, 'graphql', side_effect=responses):
                self.assertEqual(snapshot.repositories_with_contributions(), '—')


if __name__ == '__main__':
    unittest.main()
