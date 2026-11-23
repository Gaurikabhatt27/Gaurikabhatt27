#!/usr/bin/env python3

import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape


USERNAME = "Gaurikabhatt27"
API = "https://api.github.com"
GRAPHQL_URL = f"{API}/graphql"
ROOT = Path(__file__).resolve().parents[1]
COMMIT_OUTPUT = ROOT / "assets" / "commit-log.svg"
STATS_OUTPUT = ROOT / "assets" / "github-at-a-glance.svg"
COLORS = ("#2A1420", "#591C36", "#9E2B58", "#E0467F", "#FFE6F0")

CONTRIBUTIONS_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    login
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks {
          contributionDays {
            contributionCount
            date
            weekday
          }
        }
      }
    }
  }
}
"""


def api_request(url, token, method="GET", payload=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Gaurikabhatt27-profile-sync",
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            body = response.read()
            return (json.loads(body.decode("utf-8")) if body else {}), response.headers
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"GitHub API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub API connection failed: {exc.reason}") from exc


def parse_next_link(headers):
    for item in headers.get("Link", "").split(","):
        if 'rel="next"' in item:
            match = re.search(r"<([^>]+)>", item)
            if match:
                return match.group(1)
    return None


def list_public_repositories(token):
    repositories = []
    seen_urls = set()
    url = f"{API}/users/{USERNAME}/repos?type=owner&visibility=public&per_page=100&page=1"

    while url:
        if url in seen_urls:
            raise RuntimeError("Repository pagination repeated a URL")
        seen_urls.add(url)

        page, headers = api_request(url, token)
        if not isinstance(page, list):
            raise RuntimeError("Repository inventory did not return a JSON array")

        for repo in page:
            if (
                repo.get("owner", {}).get("login") == USERNAME
                and repo.get("visibility") == "public"
            ):
                repositories.append(repo)

        next_url = parse_next_link(headers)
        if next_url:
            url = next_url
        elif len(page) == 100:
            parsed = urllib.parse.urlparse(url)
            query = urllib.parse.parse_qs(parsed.query)
            current_page = int(query.get("page", ["1"])[0])
            query["page"] = [str(current_page + 1)]
            url = urllib.parse.urlunparse(
                parsed._replace(query=urllib.parse.urlencode(query, doseq=True))
            )
        else:
            break

    ids = [repo["id"] for repo in repositories]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Repository inventory contains duplicate repository IDs")
    return repositories


def request_contributions(token, start_date, end_date):
    payload = {
        "query": CONTRIBUTIONS_QUERY,
        "variables": {
            "login": USERNAME,
            "from": f"{start_date.isoformat()}T00:00:00Z",
            "to": f"{end_date.isoformat()}T23:59:59Z",
        },
    }
    data, _ = api_request(GRAPHQL_URL, token, "POST", payload)
    if data.get("errors"):
        messages = "; ".join(str(error.get("message", error)) for error in data["errors"])
        raise RuntimeError(f"GitHub GraphQL returned errors: {messages}")

    user = data.get("data", {}).get("user")
    if not user or user.get("login") != USERNAME:
        raise RuntimeError("GitHub GraphQL did not return Gaurikabhatt27")
    collection = user.get("contributionsCollection")
    calendar = collection.get("contributionCalendar") if collection else None
    if not calendar:
        raise RuntimeError("Contribution calendar data is missing")
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
        raise RuntimeError(
            f"Incomplete contribution calendar: received {len(counts)} of {expected} days"
        )
    return counts


def calculate_contribution_metrics(counts, start_date, end_date):
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
        return positive[lower] + (
            positive[upper] - positive[lower]
        ) * (position - lower)

    thresholds = [
        percentile(0.25),
        percentile(0.50),
        percentile(0.75),
        percentile(0.90),
    ]

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
    if include_year:
        return date.strftime("%b %d, %Y")
    return date.strftime("%b %d")


def load_snake_markup():
    path = ROOT / "dist" / "github-snake.svg"
    if path.exists():
        svg = path.read_text(encoding="utf-8")
        match = re.search(r"<svg\b[^>]*>(.*)</svg>", svg, re.S)
        if match:
            return (
                '  <g aria-label="Animated GitHub contribution snake">\n'
                '    <svg x="76" y="174" width="742" height="98" '
                'viewBox="0 0 848 112" preserveAspectRatio="xMidYMid meet" '
                'xmlns="http://www.w3.org/2000/svg">\n'
                f"{match.group(1)}\n"
                "    </svg>\n"
                "  </g>"
            )

    existing = COMMIT_OUTPUT.read_text(encoding="utf-8") if COMMIT_OUTPUT.exists() else ""
    match = re.search(
        r'  <g aria-label="Animated GitHub contribution snake">.*?  </g>',
        existing,
        re.S,
    )
    return match.group(0) if match else ""


def generate_commit_svg(counts, metrics, start_date, end_date, level, snake_markup):
    month_names = (
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    )
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
                count = counts[date]
                fill = COLORS[level(count)]
                glow = ' filter="url(#bright-glow)"' if level(count) == 4 else ""
                heatmap.append(
                    f'<rect x="{x}" y="{y}" width="10" height="10" rx="2" '
                    f'fill="{fill}"{glow}/>'
                )
        visible_dates = [date for date in week if start_date <= date <= end_date]
        if visible_dates:
            marker = visible_dates[0]
            if marker.month != previous_month:
                label_x = 804 if column == len(weeks) - 1 else x
                month_labels.append(
                    f'<text x="{label_x}" y="158" fill="#A8959E" '
                    f'font-family="Arial, Helvetica, sans-serif" font-size="9">'
                    f'{month_names[marker.month - 1]}</text>'
                )
                previous_month = marker.month

    axis = [
        '<text x="54" y="191" text-anchor="end" fill="#A8959E" '
        'font-family="Arial, Helvetica, sans-serif" font-size="8.5">Mon</text>',
        '<text x="54" y="219" text-anchor="end" fill="#A8959E" '
        'font-family="Arial, Helvetica, sans-serif" font-size="8.5">Wed</text>',
        '<text x="54" y="247" text-anchor="end" fill="#A8959E" '
        'font-family="Arial, Helvetica, sans-serif" font-size="8.5">Fri</text>',
    ]
    longest_start = fmt_date(metrics["longest_start"], True)
    longest_end = fmt_date(metrics["longest_end"], True)
    streak_text = (
        f"LONGEST STREAK · {metrics['longest']} DAYS · "
        f"{longest_start} – {longest_end}"
    )
    busiest_date = fmt_date(metrics["busiest_date"], True)
    annotation_x = 76
    if metrics["longest_start"]:
        offset = (metrics["longest_start"] - sunday).days // 7
        annotation_x = max(76, min(810, 76 + offset * 14))

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="390" viewBox="0 0 900 390" role="img" aria-labelledby="commit-log-title commit-log-desc">
  <title id="commit-log-title">GitHub commit log</title>
  <desc id="commit-log-desc">Real GitHub contribution activity for Gaurikabhatt27.</desc>
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
</svg>
'''


def generate_stats_svg(repository_count, stars, forks, language_distribution, synced_at):
    language_text = ", ".join(
        f"{language} {count}"
        for language, count in list(language_distribution.items())[:4]
    ) or "No public language data"

    rows = [
        ("◆", "Public repositories", str(repository_count), "CURRENT OWNED PUBLIC REPOSITORIES"),
        ("★", "Total Stars Earned", str(stars), "CURRENT OWNED PUBLIC REPOSITORIES"),
        ("⑂", "Total Forks", str(forks), "CURRENT OWNED PUBLIC REPOSITORIES"),
        ("⌘", "Programming languages", str(len(language_distribution)), escape(language_text)),
        ("◷", "Last synchronized", escape(synced_at), "GITHUB API"),
    ]

    row_svg = []
    y = 68
    for icon, label, value, period in rows:
        row_svg.append(
            f'''<g>
    <circle cx="34" cy="{y}" r="14" fill="#351925" stroke="#71304C" stroke-width="1"/>
    <text x="34" y="{y + 5}" text-anchor="middle" fill="#E06C88"
          font-family="Georgia, 'Times New Roman', serif" font-size="15">{icon}</text>
    <text x="58" y="{y - 2}" fill="#F5EDF0" font-family="Arial, Helvetica, sans-serif"
          font-size="12" font-weight="700">{escape(label)}</text>
    <text x="58" y="{y + 12}" fill="#A8959E" font-family="Consolas, monospace"
          font-size="7.5" letter-spacing="0.8">{period}</text>
    <text x="418" y="{y + 5}" text-anchor="end" fill="#F5EDF0"
          font-family="Georgia, 'Times New Roman', serif" font-size="18" font-weight="700">{escape(value)}</text>
  </g>'''
        )
        if y < 220:
            row_svg.append(
                f'<line x1="58" y1="{y + 23}" x2="418" y2="{y + 23}" '
                f'stroke="#71304C" stroke-opacity="0.52" stroke-width="1"/>'
            )
        y += 43

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="440" height="286" viewBox="0 0 440 286" role="img" aria-labelledby="github-glance-title github-glance-desc">
  <title id="github-glance-title">GitHub at a glance</title>
  <desc id="github-glance-desc">Public repository statistics for Gaurikabhatt27.</desc>
  <defs>
    <radialGradient id="glance-glow" cx="0.82" cy="0.12" r="0.72">
      <stop offset="0" stop-color="#6B1A3E" stop-opacity="0.28"/>
      <stop offset="0.58" stop-color="#351925" stop-opacity="0.10"/>
      <stop offset="1" stop-color="#24111C" stop-opacity="0"/>
    </radialGradient>
  </defs>

  <rect width="440" height="286" rx="16" fill="#24111C"/>
  <rect x="1" y="1" width="438" height="284" rx="15" fill="url(#glance-glow)"/>
  <text x="22" y="34" fill="#F5EDF0" font-family="Georgia, 'Times New Roman', serif"
        font-size="19" font-weight="700">GitHub at a glance</text>
  <text x="418" y="34" text-anchor="end" fill="#A8959E"
        font-family="Consolas, monospace" font-size="7.5" letter-spacing="1">GITHUB · {USERNAME}</text>

  {''.join(row_svg)}
</svg>
'''


def staged_publish(outputs):
    staged = Path(tempfile.mkdtemp(prefix="github-profile-sync-", dir=str(ROOT)))
    try:
        staged_outputs = []
        backups = {}

        for path, text in outputs:
            staged_path = staged / path.name
            staged_path.write_text(text, encoding="utf-8")
            if path.suffix == ".svg":
                ET.parse(staged_path)
            staged_outputs.append((path, staged_path))

        for path, _ in staged_outputs:
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
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is unavailable", file=sys.stderr)
        return 1

    end_date = datetime.now(timezone.utc).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=364)
    synced_at = datetime.now(timezone.utc).isoformat(
        timespec="minutes"
    ).replace("+00:00", "Z")

    try:
        repositories = list_public_repositories(token)
        stars = sum(repo.get("stargazers_count", 0) for repo in repositories)
        forks = sum(repo.get("forks_count", 0) for repo in repositories)

        language_distribution = {}
        for repo in repositories:
            language = repo.get("language")
            if language:
                language_distribution[language] = (
                    language_distribution.get(language, 0) + 1
                )
        language_distribution = dict(
            sorted(
                language_distribution.items(),
                key=lambda item: (-item[1], item[0]),
            )
        )

        calendar = request_contributions(token, start_date, end_date)
        counts = flatten_calendar(calendar, start_date, end_date)
        metrics = calculate_contribution_metrics(counts, start_date, end_date)
        level = intensity_levels(counts)

        commit_svg = generate_commit_svg(
            counts,
            metrics,
            start_date,
            end_date,
            level,
            load_snake_markup(),
        )
        stats_svg = generate_stats_svg(
            len(repositories),
            stars,
            forks,
            language_distribution,
            synced_at,
        )

        staged_publish([
            (COMMIT_OUTPUT, commit_svg),
            (STATS_OUTPUT, stats_svg),
        ])
        print(
            f"Updated public GitHub profile SVGs: "
            f"{len(repositories)} repositories, "
            f"{metrics['total']} contributions"
        )
        return 0
    except Exception as exc:
        print(
            f"GitHub profile synchronization failed; existing SVGs preserved: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
