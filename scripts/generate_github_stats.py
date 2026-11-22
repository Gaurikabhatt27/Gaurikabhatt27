#!/usr/bin/env python3

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape


USERNAME = "Gaurikabhatt27"
API = "https://api.github.com"
OUTPUT = Path(__file__).resolve().parents[1] / "assets" / "github-at-a-glance.svg"


def api_get(path, token=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Gaurikabhatt27-profile-stats",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"{API}{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def search_total(query, token=None):
    data = api_get(
        "/search/" + query,
        token,
    )
    return int(data["total_count"])


def generate_svg(stars, commits, prs, issues, contributed):
    contributed_text = contributed if contributed is not None else "UNAVAILABLE"
    end_date = datetime.now(timezone.utc).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=364)

    rows = [
        ("★", "Total Stars Earned", str(stars), "ALL-TIME"),
        ("↗", "Total Commits", str(commits), f"LAST YEAR · {start_date.strftime('%b %d, %Y')}–{end_date.strftime('%b %d, %Y')}"),
        ("⑂", "Total PRs", str(prs), f"LAST YEAR · {start_date.strftime('%b %d, %Y')}–{end_date.strftime('%b %d, %Y')}"),
        ("◎", "Total Issues", str(issues), f"LAST YEAR · {start_date.strftime('%b %d, %Y')}–{end_date.strftime('%b %d, %Y')}"),
        ("◇", "Contributed To", escape(str(contributed_text)), "LAST YEAR"),
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
          font-size="12" font-weight="700">{label}</text>
    <text x="58" y="{y + 12}" fill="#A8959E" font-family="Consolas, monospace"
          font-size="7.5" letter-spacing="0.8">{period}</text>
    <text x="418" y="{y + 5}" text-anchor="end" fill="#F5EDF0"
          font-family="Georgia, 'Times New Roman', serif" font-size="{18 if str(value) != 'UNAVAILABLE' else 10}" font-weight="700">{value}</text>
  </g>'''
        )
        if y < 220:
            row_svg.append(
                f'<line x1="58" y1="{y + 23}" x2="418" y2="{y + 23}" stroke="#71304C" stroke-opacity="0.52" stroke-width="1"/>'
            )
        y += 43

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="440" height="286" viewBox="0 0 440 286" role="img" aria-labelledby="github-glance-title github-glance-desc">
  <title id="github-glance-title">GitHub at a glance</title>
  <desc id="github-glance-desc">Public GitHub account statistics for Gaurikabhatt27.</desc>
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


def main():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    end_date = datetime.now(timezone.utc).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=364)
    range_query = f"{start_date.isoformat()}..{end_date.isoformat()}"

    try:
        repos = []
        page = 1
        while True:
            page_repos = api_get(
                f"/users/{USERNAME}/repos?per_page=100&page={page}&sort=updated",
                token,
            )
            if not page_repos:
                break
            repos.extend(page_repos)
            if len(page_repos) < 100:
                break
            page += 1

        stars = sum(repo.get("stargazers_count", 0) for repo in repos)
        commit_query = (
            f"commits?q={urllib.parse.quote(f'author:{USERNAME} committer-date:{range_query}')}"
        )
        commits = search_total(commit_query, token)
        prs = search_total(
            f"issues?q={urllib.parse.quote(f'author:{USERNAME} is:pr created:{range_query}')}",
            token,
        )
        issues = search_total(
            f"issues?q={urllib.parse.quote(f'author:{USERNAME} is:issue created:{range_query}')}",
            token,
        )

        svg = generate_svg(stars, commits, prs, issues, None)
        temporary = OUTPUT.with_suffix(".svg.tmp")
        temporary.write_text(svg, encoding="utf-8")
        temporary.replace(OUTPUT)
        print(
            f"Generated GitHub stats: {stars} stars, {commits} commits, "
            f"{prs} PRs, {issues} issues"
        )
    except Exception as exc:
        print(f"GitHub statistics generation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
