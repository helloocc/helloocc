"""Generate the transparent overview/languages cards used by itgoyo/itgoyo.

Uses public owned repositories plus accessible private repositories when enabled.
Templates: itgoyo/github-stats-transparent (MIT, see templates/snapshot/LICENSE).
"""
from collections import Counter
from html import escape
from pathlib import Path
import os
import sys

from updateGithubStats import USER_NAME, ACCESS_TOKEN, fetch_repos, github_get, github_headers, graphql
from snapshot_metrics import collect_metrics

ROOT = Path(__file__).resolve().parents[1]
INCLUDE_PRIVATE = os.getenv('INCLUDE_PRIVATE', '').lower() == 'true'
COLORS = {'Python': '#3572A5', 'JavaScript': '#f1e05a', 'TypeScript': '#3178c6',
          'Java': '#b07219', 'Shell': '#89e051', 'HTML': '#e34c26', 'CSS': '#563d7c',
          'Vue': '#41b883', 'SCSS': '#c6538c', 'Dockerfile': '#384d54'}


def render(template, values):
    output = (ROOT / 'templates/snapshot' / template).read_text()
    for key, value in values.items():
        output = output.replace('{{ ' + key + ' }}', str(value))
    if '{{ ' in output:
        raise ValueError('Unfilled template')
    return output


def snapshot_repos():
    repos = {repo['id']: repo for repo in fetch_repos()
             if not repo.get('fork') and not repo.get('private')}
    if INCLUDE_PRIVATE:
        if not ACCESS_TOKEN:
            raise ValueError('Private statistics require STATS_TOKEN.')
        page = 1
        while True:
            batch = github_get(
                'https://api.github.com/user/repos?visibility=private'
                '&affiliation=owner,collaborator,organization_member'
                f'&per_page=100&page={page}'
            )
            for repo in batch:
                if repo.get('private') and not repo.get('fork'):
                    repos[repo['id']] = repo
            if len(batch) < 100:
                break
            page += 1
    return list(repos.values())


def contributions():
    if not ACCESS_TOKEN:
        return '—'
    # The calendar count depends on the token's access and GitHub visibility rules.
    try:
        data = graphql('''query($login: String!) {
          user(login: $login) {
            contributionsCollection { contributionYears }
          }
        }''', {'login': USER_NAME})
        years = data['user']['contributionsCollection']['contributionYears']
        total = 0
        for year in years:
            result = graphql('''query($login: String!, $from: DateTime!, $to: DateTime!) {
              user(login: $login) {
                contributionsCollection(from: $from, to: $to) {
                  contributionCalendar { totalContributions }
                }
              }
            }''', {'login': USER_NAME, 'from': f'{year}-01-01T00:00:00Z',
                  'to': f'{year}-12-31T23:59:59Z'})
            total += result['user']['contributionsCollection']['contributionCalendar']['totalContributions']
        return f'{total:,}'
    except Exception:
        print('Contribution count unavailable; displaying a dash.')
        return '—'


def repositories_with_contributions():
    """Match upstream all_repos: non-fork repositories union contributed repos."""
    if not ACCESS_TOKEN:
        print('Contributed repository count unavailable: authentication required.')
        return '—'
    selections = [
        'repositories(first: 100, isFork: false, after: $cursor)',
        '''repositoriesContributedTo(
            first: 100, includeUserRepositories: false, after: $cursor,
            contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY, PULL_REQUEST_REVIEW]
        )''',
    ]
    ids = set()
    try:
        for selection in selections:
            cursor = None
            seen_cursors = set()
            while True:
                query = '''query($login: String!, $cursor: String) {
                  user(login: $login) {
                    selected: ''' + selection + ''' {
                      nodes { id isPrivate }
                      pageInfo { hasNextPage endCursor }
                    }
                  }
                }'''
                result = graphql(query, {'login': USER_NAME, 'cursor': cursor})
                connection = result['user']['selected']
                for repo in connection['nodes']:
                    if not repo or not repo.get('id') or type(repo.get('isPrivate')) is not bool:
                        raise ValueError('Incomplete repository data')
                    if INCLUDE_PRIVATE or not repo['isPrivate']:
                        ids.add(repo['id'])
                page = connection['pageInfo']
                if type(page['hasNextPage']) is not bool:
                    raise ValueError('Invalid pagination')
                if not page['hasNextPage']:
                    break
                cursor = page['endCursor']
                if not cursor or cursor in seen_cursors:
                    raise ValueError('Invalid pagination cursor')
                seen_cursors.add(cursor)
        print(f'Repositories with contributions: {len(ids)} (GitHub-visible union).')
        return f'{len(ids):,}'
    except Exception:
        # Never substitute a partial count or log private names from API errors.
        print('Contributed repository count unavailable; check token access and API limits.')
        return '—'


def balanced_language_scores(language_maps):
    scores = Counter()
    for languages in language_maps:
        if not isinstance(languages, dict) or any(
            type(size) is not int or size < 0 for size in languages.values()
        ):
            raise ValueError('Invalid repository language data')
        total = sum(languages.values())
        if total:
            for name, size in languages.items():
                if size:
                    scores[name] += size / total
    return scores


def language_rows(scores):
    ranked = sorted(((name, score) for name, score in scores.items() if score > 0),
                    key=lambda row: (-row[1], row[0]))
    return ranked[:10]


def main():
    repos = snapshot_repos()
    private_count = sum(bool(repo.get('private')) for repo in repos)
    print(f'Snapshot scope: {len(repos) - private_count} public, {private_count} private repositories (excluding forks).')
    scores = balanced_language_scores(
        github_get(repo['languages_url']) for repo in repos
    )
    metrics = collect_metrics(repos, USER_NAME, github_headers())
    contributed_repos = repositories_with_contributions()
    overview = render('overview.svg', {
        'name': 'HelloC',
        'stars': f"{sum(r['stargazers_count'] for r in repos):,}",
        'forks': f"{sum(r['forks_count'] for r in repos):,}",
        'contributions': contributions(),
        'lines_changed': metrics['lines_changed']['display'],
        'views': metrics['views']['display'],
        'repos': contributed_repos,
    })
    notes = []
    if any('*' in metric['display'] for metric in metrics.values()):
        notes.append('* Partial total')
    if contributed_repos == '—' or any(metric['display'] == '—' for metric in metrics.values()):
        notes.append('— Unavailable')
    if notes:
        end = overview.rfind('</svg>')
        footnote = ('<text x="21" y="235" font-size="9" fill="#919191">'
                    + escape(' · '.join(notes)) + '</text>\n')
        overview = overview[:end] + footnote + overview[end:]
    rows = language_rows(scores)
    total = sum(score for _, score in rows)
    progress, items = [], []
    for language, score in rows:
        percent = score / total * 100
        color = COLORS.get(language, '#8b949e')
        progress.append(f'<span style="background-color:{color};width:{percent:.5f}%;" class="progress-item"></span>')
        items.append(f'<li><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" class="octicon"><circle cx="8" cy="8" r="4" fill="{color}"/></svg><span class="lang" title="{escape(language)}">{escape(language)}</span><span class="percent">{percent:.2f}%</span></li>')
    languages = render('languages.svg', {'progress': ''.join(progress),
        'lang_list': ''.join(items) or '<li><span class="lang">No language data</span></li>'})
    height = max(250, 110 + 24 * ((len(items) + 1) // 2))
    overview = overview.replace('height="250" viewBox="0 0 360 250"',
                                f'height="{height}" viewBox="0 0 360 {height}"')
    languages = languages.replace('height="250" viewBox="0 0 360 250"',
                                  f'height="{height}" viewBox="0 0 360 {height}"')
    languages = languages.replace('height="216"', f'height="{height - 34}"')
    output = ROOT / 'img/snapshot'
    output.mkdir(parents=True, exist_ok=True)
    for name, svg in [('overview.svg', overview), ('languages.svg', languages)]:
        (output / name).write_text(svg)
        print(f'Generated img/snapshot/{name}')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # API exceptions can contain private repository URLs. Do not publish them.
        print('Snapshot generation failed. Check STATS_TOKEN repository access, API limits and connectivity.', file=sys.stderr)
        sys.exit(1)
