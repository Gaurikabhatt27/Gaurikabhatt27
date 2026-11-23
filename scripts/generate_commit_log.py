#!/usr/bin/env python3

import json
import hashlib
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape


USERNAME = "Gaurikabhatt27"
API = "https://api.github.com"
GRAPHQL_URL = f"{API}/graphql"
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "commit-log.svg"
STATS_OUTPUT = ROOT / "assets" / "github-at-a-glance.svg"
INVENTORY = ROOT / "assets" / "github-repository-inventory.json"
COLORS = ("#2A1420", "#591C36", "#9E2B58", "#E0467F", "#FFE6F0")


def get_token():
    return os.environ.get("GITHUB_TOKEN")


def api_request(url, token=None, method="GET", payload=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Gaurikabhatt27-profile-sync",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            body = response.read()
            return json.loads(body.decode("utf-8")) if body else {}, response.headers
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        remaining = exc.headers.get("X-RateLimit-Remaining")
        reset = exc.headers.get("X-RateLimit-Reset")
        retry = exc.headers.get("Retry-After")
        suffix = ""
        if exc.code == 403 and remaining == "0":
            suffix = f"; rate limit resets at epoch {reset}" if reset else ""
        elif retry:
            suffix = f"; retry after {retry} seconds"
        raise RuntimeError(f"GitHub REST HTTP {exc.code}: {detail}{suffix}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub API connection failed: {exc.reason}") from exc


def graphql_request(token, query, variables):
    if not token:
        raise RuntimeError("A GitHub token is required for GraphQL contribution data")
    payload = {"query": query, "variables": variables}
    data, _ = api_request(GRAPHQL_URL, token, "POST", payload)
    if data.get("errors"):
        messages = "; ".join(str(error.get("message", error)) for error in data["errors"])
        raise RuntimeError(f"GitHub GraphQL returned errors: {messages}")
    return data


def parse_next_link(headers):
    link = headers.get("Link", "")
    for item in link.split(","):
        if 'rel="next"' in item:
            match = re.search(r"<([^>]+)>", item)
            if match:
                return match.group(1)
    return None


def list_owned_repositories(token):
    repositories = []
    seen_urls = set()
    page_numbers = set()
    url = f"{API}/users/{USERNAME}/repos?type=owner&visibility=public&per_page=100&page=1"

    while url:
        if url in seen_urls:
            raise RuntimeError("Pagination loop detected while listing repositories")
        seen_urls.add(url)
        current_url = url
        page, headers = api_request(current_url, token)
        if not isinstance(page, list):
            raise RuntimeError("Repository listing did not return a JSON array")
        if not page:
            next_url = parse_next_link(headers)
            if next_url:
                raise RuntimeError("Repository pagination returned an empty page before the Link chain ended")
            break
        repositories.extend(
            repo for repo in page
            if repo.get("owner", {}).get("login") == USERNAME
            and repo.get("visibility") == "public"
        )
        url = parse_next_link(headers)
        if url is None and len(page) == 100:
            parsed = urllib.parse.urlparse(current_url)
            query = urllib.parse.parse_qs(parsed.query)
            current_page = int(query.get("page", ["1"])[0])
            if current_page in page_numbers:
                raise RuntimeError("Repository pagination repeated an inventory page")
            page_numbers.add(current_page)
            query["page"] = [str(current_page + 1)]
            url = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))
        elif url is None:
            break
        else:
            parsed = urllib.parse.urlparse(url)
            next_page = int(urllib.parse.parse_qs(parsed.query).get("page", ["1"])[0])
            if next_page in page_numbers:
                raise RuntimeError("Repository pagination repeated an inventory page")
            page_numbers.add(next_page)

    ids = {repo["id"] for repo in repositories}
    if len(ids) != len(repositories):
        raise RuntimeError("Repository listing contains duplicate repository IDs")
    return repositories


def commit_count(repo, token):
    owner = repo["owner"]["login"]
    name = repo["name"]
    url = f"{API}/repos/{owner}/{name}/commits?per_page=1"
    try:
        commits, headers = api_request(url, token)
        if isinstance(commits, list) and not commits:
            return 0
        link = headers.get("Link", "")
        match = re.search(r"[?&]page=(\d+)>; rel=\"last\"", link)
        if match:
            return int(match.group(1))
        return 1
    except RuntimeError as exc:
        if "GitHub REST HTTP 409" in str(exc):
            return 0
        if "GitHub REST HTTP 404" in str(exc):
            raise RuntimeError(f"Cannot access repository {name}; verify token access") from exc
        raise


def repository_fingerprint(repo):
    fields = (
        repo["id"],
        repo["name"],
        repo.get("description"),
        repo.get("visibility"),
        repo.get("language"),
        repo.get("stargazers_count"),
        repo.get("forks_count"),
        repo.get("created_at"),
        repo.get("updated_at"),
        repo.get("pushed_at"),
        repo.get("default_branch"),
    )
    return hashlib.sha256(json.dumps(fields, ensure_ascii=True).encode("utf-8")).hexdigest()


def request_contributions(token, start_date, end_date):
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        login
        contributionsCollection(from: $from, to: $to) {
          totalContributions
          contributionCalendar {
            weeks {
              contributionDays { contributionCount date weekday }
            }
          }
        }
      }
    }
    """
    data = graphql_request(token, query, {
        "login": USERNAME,
        "from": f"{start_date.isoformat()}T00:00:00Z",
        "to": f"{end_date.isoformat()}T23:59:59Z",
    })
    user = data.get("data", {}).get("user")
    if not user or user.get("login") != USERNAME:
        raise RuntimeError("GraphQL did not return the expected GitHub user")
    collection = user.get("contributionsCollection")
    calendar = collection.get("contributionCalendar") if collection else None
    if not calendar:
        raise RuntimeError("Contribution calendar data was missing")
    return calendar


def flatten_calendar(calendar, start_date, end_date):
    counts = {}
    for week in calendar.get("weeks", []):
        for day in week.get("contributionDays", []):
            date_text = day.get("date")
            count = day.get("contributionCount")
            if date_text is None or count is None:
                continue
            date = datetime.strptime(date_text, "%Y-%m-%d").date()
            if start_date <= date <= end_date:
                counts[date] = max(0, int(count))
    expected = (end_date - start_date).days + 1
    if len(counts) != expected:
        raise RuntimeError(f"Incomplete contribution calendar: got {len(counts)} of {expected} days")
    return counts


def calculate_metrics(counts, start_date, end_date):
    longest = run = 0
    longest_start = longest_end = run_start = None
    date = start_date
    while date <= end_date:
        if counts.get(date, 0) > 0:
            if run == 0:
                run_start = date
            run += 1
            if run > longest:
                longest = run
                longest_start = run_start
                longest_end = date
        else:
            run = 0
            run_start = None
        date += timedelta(days=1)
    busiest_count = max(counts.values(), default=0)
    busiest_dates = [date for date in counts if counts[date] == busiest_count]
    return {
        "total": sum(counts.values()),
        "active": sum(count > 0 for count in counts.values()),
        "longest": longest,
        "longest_start": longest_start,
        "longest_end": longest_end,
        "busiest_count": busiest_count,
        "busiest_date": min(busiest_dates) if busiest_dates else None,
    }


def intensity_levels(counts):
    positive = sorted(count for count in counts.values() if count > 0)
    if not positive:
        return lambda count: 0

    def percentile(fraction):
        position = fraction * (len(positive) - 1)
        lower = int(position)
        upper = min(lower + 1, len(positive) - 1)
        return positive[lower] + (positive[upper] - positive[lower]) * (position - lower)

    thresholds = [percentile(0.25), percentile(0.50), percentile(0.75), percentile(0.90)]

    def level(count):
        if count <= 0:
            return 0
        if count <= thresholds[0]:
            return 1
        if count <= thresholds[1]:
            return 2
        if count <= thresholds[2]:
            return 3
        return 4
    return level


def fmt_date(date, include_year=False):
    if date is None:
        return "Unavailable"
    return date.strftime("%b %d, %Y") if include_year else date.strftime("%b %d")


def load_existing_snake_markup():
    existing = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
    match = re.search(r'  <g aria-label="Animated GitHub contribution snake">.*?  </g>', existing, re.S)
    return match.group(0) if match else ""


def load_generated_snake_markup():
    path = ROOT / "dist" / "github-snake.svg"
    if not path.exists():
        return load_existing_snake_markup()
    svg = path.read_text(encoding="utf-8")
    match = re.search(r"<svg\b[^>]*>(.*)</svg>", svg, re.S)
    if not match:
        return load_existing_snake_markup()
    return (
        '  <g aria-label="Animated GitHub contribution snake">\n'
        '    <svg x="76" y="174" width="742" height="98" viewBox="0 0 848 112" '
        'preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">\n'
        f"{match.group(1)}\n"
        "    </svg>\n"
        "  </g>"
    )


def generate_commit_svg(counts, metrics, start_date, end_date, level, repository_count, commit_count, synced_at, snake_markup):
    month_names = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    sunday = start_date - timedelta(days=(start_date.weekday() + 1) % 7)
    weeks = []
    current = sunday
    while current <= end_date:
        weeks.append([current + timedelta(days=row) for row in range(7)])
        current += timedelta(days=7)

    month_labels = []
    heatmap = []
    previous_month = None
    for column, week in enumerate(weeks):
        x = 76 + column * 14
        for row, date in enumerate(week):
            if start_date <= date <= end_date:
                y = 174 + row * 14
                count = counts.get(date, 0)
                fill = COLORS[level(count)]
                glow = ' filter="url(#bright-glow)"' if level(count) == 4 else ""
                heatmap.append(f'<rect x="{x}" y="{y}" width="10" height="10" rx="2" fill="{fill}"{glow}/>')
        visible_dates = [date for date in week if start_date <= date <= end_date]
        if visible_dates:
            marker = visible_dates[0]
            if marker.month != previous_month:
                month_labels.append(
                    f'<text x="{804 if marker.month == end_date.month and column == len(weeks)-1 else x}" y="158" '
                    f'fill="#A8959E" font-family="Arial, Helvetica, sans-serif" font-size="9">'
                    f'{month_names[marker.month - 1]}</text>'
                )
                previous_month = marker.month

    axis = [
        '<text x="54" y="191" text-anchor="end" fill="#A8959E" font-family="Arial, Helvetica, sans-serif" font-size="8.5">Mon</text>',
        '<text x="54" y="219" text-anchor="end" fill="#A8959E" font-family="Arial, Helvetica, sans-serif" font-size="8.5">Wed</text>',
        '<text x="54" y="247" text-anchor="end" fill="#A8959E" font-family="Arial, Helvetica, sans-serif" font-size="8.5">Fri</text>',
    ]
    longest_start = fmt_date(metrics["longest_start"], True)
    longest_end = fmt_date(metrics["longest_end"], True)
    streak_text = f"LONGEST STREAK · {metrics['longest']} DAYS · {longest_start} – {longest_end}"
    busiest_date = fmt_date(metrics["busiest_date"], True)
    annotation_x = 76
    if metrics["longest_start"]:
        annotation_x = max(76, min(810, 76 + ((metrics["longest_start"] - sunday).days // 7) * 14))

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="390" viewBox="0 0 900 390" role="img" aria-labelledby="commit-log-title commit-log-desc">
  <title id="commit-log-title">GitHub commit log</title>
  <desc id="commit-log-desc">Actual GitHub contribution activity and commits reachable from owned-repository default branches for Gaurikabhatt27.</desc>
  <defs>
    <linearGradient id="commitlog-panel" x1="0" y1="1" x2="1" y2="0">
      <stop offset="0" stop-color="#1A0C13"/><stop offset="0.54" stop-color="#381224"/><stop offset="1" stop-color="#591835"/>
    </linearGradient>
    <radialGradient id="commitlog-glow" cx="0.88" cy="0.12" r="0.66">
      <stop offset="0" stop-color="#A82463" stop-opacity="0.32"/><stop offset="0.55" stop-color="#701A3D" stop-opacity="0.12"/><stop offset="1" stop-color="#1A0C13" stop-opacity="0"/>
    </radialGradient>
    <filter id="bright-glow" x="-100%" y="-100%" width="300%" height="300%">
      <feGaussianBlur stdDeviation="1.25" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <rect width="900" height="390" rx="16" fill="url(#commitlog-panel)" stroke="#5A2740" stroke-width="1"/>
  <rect x="1" y="1" width="898" height="388" rx="15" fill="url(#commitlog-glow)"/>
  <g>
    <text x="24" y="34" fill="#D96389" font-family="Consolas, monospace" font-size="9.5" font-weight="700" letter-spacing="1.4">COMMIT LOG · REAL GITHUB ACTIVITY</text>
    <text x="24" y="62" fill="#F5EDF0" font-family="Georgia, 'Times New Roman', serif" font-size="20" font-weight="700">A year of building, one square at a time.</text>
  </g>
  <g font-family="Arial, Helvetica, sans-serif">
    <line x1="480" y1="26" x2="480" y2="82" stroke="#71304C" stroke-width="1"/><line x1="584" y1="26" x2="584" y2="82" stroke="#71304C" stroke-width="1"/><line x1="688" y1="26" x2="688" y2="82" stroke="#71304C" stroke-width="1"/><line x1="792" y1="26" x2="792" y2="82" stroke="#71304C" stroke-width="1"/>
    <text x="500" y="34" fill="#A8959E" font-family="Consolas, monospace" font-size="8" letter-spacing="1">CONTRIBUTIONS</text>
    <text x="500" y="62" fill="#F5EDF0" font-family="Georgia, 'Times New Roman', serif" font-size="21" font-weight="700">{metrics["total"]:,}</text>
    <text x="500" y="78" fill="#B8A3AD" font-size="7.2">{escape(fmt_date(start_date, True))} –</text><text x="500" y="88" fill="#B8A3AD" font-size="7.2">{escape(fmt_date(end_date, True))}</text>
    <text x="604" y="34" fill="#A8959E" font-family="Consolas, monospace" font-size="8" letter-spacing="1">ACTIVE DAYS</text><text x="604" y="62" fill="#F5EDF0" font-family="Georgia, 'Times New Roman', serif" font-size="21" font-weight="700">{metrics["active"]}</text><text x="604" y="78" fill="#B8A3AD" font-size="8">out of {(end_date-start_date).days+1} days</text>
    <text x="708" y="34" fill="#A8959E" font-family="Consolas, monospace" font-size="8" letter-spacing="1">LONGEST STREAK</text><text x="708" y="62" fill="#F5EDF0" font-family="Georgia, 'Times New Roman', serif" font-size="21" font-weight="700">{metrics["longest"]}</text><text x="708" y="78" fill="#B8A3AD" font-size="8">consecutive days</text>
    <text x="812" y="34" fill="#A8959E" font-family="Consolas, monospace" font-size="8" letter-spacing="1">BUSIEST DAY</text><text x="812" y="62" fill="#F5EDF0" font-family="Georgia, 'Times New Roman', serif" font-size="21" font-weight="700">{metrics["busiest_count"]}</text><text x="812" y="78" fill="#B8A3AD" font-size="8">{escape(busiest_date)}</text>
  </g>
  <line x1="24" y1="94" x2="876" y2="94" stroke="#71304C" stroke-width="1"/>
  <g>{''.join(month_labels)}{''.join(axis)}{snake_markup if snake_markup else ''.join(heatmap)}</g>
  <line x1="24" y1="342" x2="876" y2="342" stroke="#71304C" stroke-width="1"/>
  <line x1="{annotation_x}" y1="326" x2="{annotation_x}" y2="342" stroke="#D96389" stroke-width="2"/>
  <text x="24" y="366" fill="#D96389" font-family="Consolas, monospace" font-size="9" font-weight="700" letter-spacing="1">{escape(streak_text)}</text>
  <text x="876" y="366" text-anchor="end" fill="#A8959E" font-family="Consolas, monospace" font-size="7.5">{repository_count} OWNED REPOS · {commit_count:,} COMMITS REACHABLE FROM DEFAULT BRANCHES · SYNCED {escape(synced_at)}</text>
</svg>
'''


def generate_stats_svg(stats):
    rows = [
        ("◆", "Owned repositories", str(stats["repository_count"]), "CURRENT INVENTORY"),
        ("↗", "Default-branch reachable commits", str(stats["commit_count"]), "ACROSS OWNED REPOSITORIES"),
        ("★", "Total Stars Earned", str(stats["stars"]), "CURRENT OWNED REPOSITORIES"),
        ("⑂", "Total Forks", str(stats["forks"]), "CURRENT OWNED REPOSITORIES"),
        ("◎", "Total Issues", "UNAVAILABLE" if stats["issues"] is None else str(stats["issues"]), "LAST YEAR"),
    ]
    y = 68
    row_svg = []
    for icon, label, value, period in rows:
        row_svg.append(f'''<g><circle cx="34" cy="{y}" r="14" fill="#351925" stroke="#71304C" stroke-width="1"/><text x="34" y="{y+5}" text-anchor="middle" fill="#E06C88" font-family="Georgia, 'Times New Roman', serif" font-size="15">{icon}</text><text x="58" y="{y-2}" fill="#F5EDF0" font-family="Arial, Helvetica, sans-serif" font-size="12" font-weight="700">{escape(label)}</text><text x="58" y="{y+12}" fill="#A8959E" font-family="Consolas, monospace" font-size="7.5" letter-spacing="0.8">{escape(period)}</text><text x="418" y="{y+5}" text-anchor="end" fill="#F5EDF0" font-family="Georgia, 'Times New Roman', serif" font-size="18" font-weight="700">{escape(value)}</text></g>''')
        if y < 220:
            row_svg.append(f'<line x1="58" y1="{y+23}" x2="418" y2="{y+23}" stroke="#71304C" stroke-opacity="0.52" stroke-width="1"/>')
        y += 43
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="440" height="286" viewBox="0 0 440 286" role="img" aria-labelledby="github-glance-title github-glance-desc"><title id="github-glance-title">GitHub at a glance</title><desc id="github-glance-desc">Current owned-repository statistics and commits reachable from owned-repository default branches for Gaurikabhatt27.</desc><defs><radialGradient id="glance-glow" cx="0.82" cy="0.12" r="0.72"><stop offset="0" stop-color="#6B1A3E" stop-opacity="0.28"/><stop offset="0.58" stop-color="#351925" stop-opacity="0.10"/><stop offset="1" stop-color="#24111C" stop-opacity="0"/></radialGradient></defs><rect width="440" height="286" rx="16" fill="#24111C"/><rect x="1" y="1" width="438" height="284" rx="15" fill="url(#glance-glow)"/><text x="22" y="34" fill="#F5EDF0" font-family="Georgia, 'Times New Roman', serif" font-size="19" font-weight="700">GitHub at a glance</text><text x="418" y="34" text-anchor="end" fill="#A8959E" font-family="Consolas, monospace" font-size="7.5" letter-spacing="1">GITHUB · {USERNAME}</text>{''.join(row_svg)}</svg>'''


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def staged_publish(outputs):
    staged = Path(tempfile.mkdtemp(prefix="github-profile-sync-", dir=str(ROOT)))
    backups = {}
    try:
        staged_outputs = []
        for path, text in outputs:
            staged_path = staged / path.name
            staged_path.write_text(text, encoding="utf-8")
            if staged_path.suffix == ".svg":
                import xml.etree.ElementTree as ET
                ET.parse(staged_path)
            elif staged_path.suffix == ".json":
                json.loads(staged_path.read_text(encoding="utf-8"))
            staged_outputs.append((path, staged_path))

        for path, staged_path in staged_outputs:
            if path.exists():
                backup = staged / f"{path.name}.backup"
                shutil.copy2(path, backup)
                backups[path] = backup

        try:
            for path, staged_path in staged_outputs:
                os.replace(staged_path, path)
        except Exception:
            for path, backup in backups.items():
                if backup.exists():
                    os.replace(backup, path)
            raise
    finally:
        shutil.rmtree(staged, ignore_errors=True)


def main():
    token = get_token()
    if not token:
        print("Profile sync requires GITHUB_TOKEN in GitHub Actions for public API access.", file=sys.stderr)
        return 1

    end_date = datetime.now(timezone.utc).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=364)
    synced_at = datetime.now(timezone.utc).isoformat(timespec="minutes").replace("+00:00", "Z")

    try:
        repos = list_owned_repositories(token)
        public_repos = repos

        repository_records = []
        total_commit_count = 0
        language_distribution = {}
        for repo in repos:
            count = commit_count(repo, token)
            total_commit_count += count
            language = repo.get("language")
            if language:
                language_distribution[language] = language_distribution.get(language, 0) + 1
            if repo.get("visibility") == "public":
                repository_records.append({
                    "name": repo["name"],
                    "description": repo.get("description"),
                    "visibility": "public",
                    "primary_language": language,
                    "stars": repo.get("stargazers_count", 0),
                    "forks": repo.get("forks_count", 0),
                    "created_at": repo.get("created_at"),
                    "updated_at": repo.get("updated_at"),
                    "pushed_at": repo.get("pushed_at"),
                    "default_branch": repo.get("default_branch"),
                    "commit_count": count,
                    "fingerprint": repository_fingerprint(repo),
                })

        calendar = request_contributions(token, start_date, end_date)
        counts = flatten_calendar(calendar, start_date, end_date)
        metrics = calculate_metrics(counts, start_date, end_date)
        level = intensity_levels(counts)

        previous = {}
        if INVENTORY.exists():
            try:
                previous = json.loads(INVENTORY.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                previous = {}
        previous_public = {repo["name"]: repo.get("fingerprint") for repo in previous.get("owned_repositories", [])}
        current_public = {repo["name"]: repo["fingerprint"] for repo in repository_records}
        deleted_public = sorted(set(previous_public) - set(current_public))
        added_public = sorted(set(current_public) - set(previous_public))
        changed_public = sorted(
            name for name in set(previous_public) & set(current_public)
            if previous_public[name] != current_public[name]
        )

        inventory = {
            "schema_version": 1,
            "username": USERNAME,
            "synced_at": synced_at,
            "owned_public_repository_count": len(public_repos),
            "owned_public_repository_commit_count": total_commit_count,
            "stars": sum(repo.get("stargazers_count", 0) for repo in repos),
            "forks": sum(repo.get("forks_count", 0) for repo in repos),
            "language_distribution": dict(sorted(language_distribution.items(), key=lambda item: (-item[1], item[0]))),
            "owned_repositories": repository_records,
            "changes": {
                "added_public_repositories": added_public,
                "deleted_public_repositories": deleted_public,
                "changed_public_repositories": changed_public,
            },
        }

        inventory["last_successfully_synchronized"] = synced_at

        end_year = end_date
        range_query = f"{start_date.isoformat()}..{end_year.isoformat()}"
        issues_count = previous.get("issues")
        try:
            issues_payload, _ = api_request(
                f"{API}/search/issues?q={urllib.parse.quote(f'author:{USERNAME} is:issue created:{range_query}')}&per_page=1",
                token,
            )
            issues_count = int(issues_payload.get("total_count", 0))
        except RuntimeError as exc:
            print(f"Non-critical issue search failed: {exc}", file=sys.stderr)
        inventory["issues"] = issues_count

        snake_markup = load_generated_snake_markup()
        commit_svg = generate_commit_svg(
            counts, metrics, start_date, end_date, level, len(repos),
            total_commit_count, synced_at, snake_markup,
        )
        stats = {
            "repository_count": len(repos),
            "commit_count": total_commit_count,
            "stars": inventory["stars"],
            "forks": inventory["forks"],
            "issues": issues_count,
        }

        staged_publish([
            (OUTPUT, commit_svg),
            (STATS_OUTPUT, generate_stats_svg(stats)),
            (INVENTORY, json.dumps(inventory, indent=2, ensure_ascii=False) + "\n"),
        ])
        print(
            f"Synced {len(repos)} owned repositories, {total_commit_count} commits, "
            f"{metrics['total']} contributions"
        )
        if deleted_public:
            print(f"Detected deleted public repositories: {', '.join(deleted_public)}")
    except Exception as exc:
        print(f"Profile synchronization failed safely; existing generated assets preserved: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
