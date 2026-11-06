"""Fetch optional Snapshot metrics without exposing repository names in logs."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import time

import requests


@dataclass(frozen=True)
class Metric:
    value: object = None
    reason: str = ''


def request_metric(url, headers, attempts=4):
    for attempt in range(attempts):
        try:
            response = requests.get(url, headers=headers, timeout=20)
        except requests.RequestException:
            return None, 'network'
        status = response.status_code
        if status == 202:
            if attempt + 1 < attempts:
                time.sleep(2 ** (attempt + 1))
                continue
            return None, 'pending'
        if status == 204:
            return None, 'no_data'
        if status == 429 or (status == 403 and (
                response.headers.get('X-RateLimit-Remaining') == '0'
                or response.headers.get('Retry-After'))):
            return None, 'rate_limited'
        if status in (401, 403, 404):
            return None, 'access_denied'
        if status != 200:
            return None, 'api_error'
        try:
            return response.json(), ''
        except ValueError:
            return None, 'invalid_response'
    return None, 'pending'


def count(value):
    if type(value) is not int or value < 0:
        raise ValueError('Invalid count')
    return value


def lines_changed(repo, username, headers):
    data, reason = request_metric(repo['url'] + '/stats/contributors', headers)
    if reason:
        return Metric(reason=reason)
    try:
        if not isinstance(data, list) or not data:
            return Metric(reason='no_data')
        # GitHub returns zero additions/deletions for repositories >=10,000 commits.
        if sum(count(row['total']) for row in data) >= 10000:
            return Metric(reason='large_repository')
        total = 0
        commits = 0
        for row in data:
            author = row.get('author') or {}
            if author.get('login', '').casefold() != username.casefold():
                continue
            commits += count(row['total'])
            for week in row['weeks']:
                total += count(week['a']) + count(week['d'])
        if commits and total == 0:
            # Could also be binary-only commits; do not misreport suppressed data as zero.
            return Metric(reason='zero_changes_unverified')
        return Metric(total)
    except (KeyError, TypeError, ValueError, AttributeError):
        return Metric(reason='invalid_response')


def repository_views(repo, headers):
    data, reason = request_metric(repo['url'] + '/traffic/views', headers)
    if reason:
        return Metric(reason=reason)
    try:
        return Metric(count(data['count']))
    except (KeyError, TypeError, ValueError):
        return Metric(reason='invalid_response')


def summarize(results):
    values = [result.value for result in results if result.value is not None]
    missing = Counter(result.reason or 'unavailable' for result in results if result.value is None)
    if not results:
        display = '0'
    elif not values:
        display = '—'
    else:
        display = f'{sum(values):,}' + ('*' if missing else '')
    return {'display': display, 'available': len(values), 'total': len(results),
            'missing': dict(missing)}


def collect_metrics(repos, username, headers):
    def collect(repo):
        return lines_changed(repo, username, headers), repository_views(repo, headers)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(collect, repos))
    output = {
        'lines_changed': summarize([row[0] for row in rows]),
        'views': summarize([row[1] for row in rows]),
    }
    for name, result in output.items():
        reasons = ', '.join(f'{reason}={count}' for reason, count in sorted(result['missing'].items()))
        print(f'{name}: {result["available"]}/{result["total"]} repositories available'
              + (f'; {reasons}' if reasons else ''))
    return output
