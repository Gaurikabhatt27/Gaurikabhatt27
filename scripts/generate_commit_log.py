#!/usr/bin/env python3

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from xml.sax.saxutils import escape


USERNAME = "Gaurikabhatt27"
GRAPHQL_URL = "https://api.github.com/graphql"
OUTPUT = Path(__file__).resolve().parents[1] / "assets" / "commit-log.svg"

COLORS = ("#2A1420", "#591C36", "#9E2B58", "#E0467F", "#FFE6F0")


def get_token():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    return token


def request_contributions(token, start_date, end_date):
    if not token:
        raise RuntimeError("No GitHub API token is available")
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        login
        contributionsCollection(from: $from, to: $to) {
          totalContributions
          contributionCalendar {
            totalContributions
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
    payload = {
        "query": query,
        "variables": {
            "login": USERNAME,
            "from": f"{start_date.isoformat()}T00:00:00Z",
            "to": f"{end_date.isoformat()}T23:59:59Z",
        },
    }
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Gaurikabhatt27-profile-commit-log",
            "Accept": "application/vnd.github+json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub GraphQL HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub GraphQL connection failed: {exc.reason}") from exc

    if result.get("errors"):
        messages = "; ".join(str(error.get("message", error)) for error in result["errors"])
        raise RuntimeError(f"GitHub GraphQL returned errors: {messages}")
    user = result.get("data", {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub user '{USERNAME}' was not found")
    if user.get("login") != USERNAME:
        raise RuntimeError(
            f"GraphQL returned unexpected user '{user.get('login')}' instead of '{USERNAME}'"
        )
    collection = user.get("contributionsCollection")
    calendar = collection.get("contributionCalendar") if collection else None
    if not calendar:
        raise RuntimeError("Contribution calendar data was missing from the GitHub API response")
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

    if len(counts) != (end_date - start_date).days + 1:
        raise RuntimeError(
            f"Contribution calendar returned {len(counts)} in-range days; "
            f"expected {(end_date - start_date).days + 1}"
        )
    return counts


def request_public_contributions(start_date, end_date):
    url = f"https://github.com/users/{USERNAME}/contributions"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Gaurikabhatt27-profile-commit-log",
            "Accept": "text/html",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            html = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Public GitHub calendar HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Public GitHub calendar connection failed: {exc.reason}") from exc

    class ContributionParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.days = {}
            self.tooltips = {}
            self.tooltip_id = None
            self.tooltip_text = []

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if tag == "td" and attributes.get("class") == "ContributionCalendar-day":
                day_id = attributes.get("id")
                date_text = attributes.get("data-date")
                if day_id and date_text:
                    self.days[day_id] = date_text
            elif tag == "tool-tip":
                self.tooltip_id = attributes.get("for")
                self.tooltip_text = []

        def handle_data(self, data):
            if self.tooltip_id:
                self.tooltip_text.append(data)

        def handle_endtag(self, tag):
            if tag == "tool-tip" and self.tooltip_id:
                clean_text = re.sub(r"\s+", " ", "".join(self.tooltip_text)).strip()
                if clean_text.lower().startswith("no contribution"):
                    count = 0
                else:
                    match = re.search(
                        r"(\d[\d,]*)\s+contributions?",
                        clean_text,
                        re.IGNORECASE,
                    )
                    count = int(match.group(1).replace(",", "")) if match else None
                self.tooltips[self.tooltip_id] = count
                self.tooltip_id = None
                self.tooltip_text = []

    parser = ContributionParser()
    parser.feed(html)

    counts = {}
    for day_id, date_text in parser.days.items():
        date = datetime.strptime(date_text, "%Y-%m-%d").date()
        if not (start_date <= date <= end_date):
            continue
        count = parser.tooltips.get(day_id)
        if count is None:
            raise RuntimeError(
                f"Public GitHub calendar omitted the contribution count for {date_text}"
            )
        counts[date] = count

    if len(counts) < 360:
        raise RuntimeError(
            f"Public GitHub calendar returned only {len(counts)} days"
        )
    return counts


def calculate_metrics(counts, start_date, end_date):
    total = sum(counts.values())
    active = sum(1 for date in counts if counts[date] > 0)

    longest_start = None
    longest_end = None
    longest = 0
    run_start = None
    run = 0
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
    busiest_date = min(busiest_dates) if busiest_dates else None
    return {
        "total": total,
        "active": active,
        "longest": longest,
        "longest_start": longest_start,
        "longest_end": longest_end,
        "busiest_count": busiest_count,
        "busiest_date": busiest_date,
    }


def intensity_levels(counts):
    """Map positive counts to five levels using 25th, 50th, 75th, and 90th percentiles."""
    positive = sorted(count for count in counts.values() if count > 0)
    if not positive:
        return lambda count: 0

    def percentile(values, fraction):
        if len(values) == 1:
            return values[0]
        position = fraction * (len(values) - 1)
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        return values[lower] + (values[upper] - values[lower]) * (position - lower)

    thresholds = [
        percentile(positive, 0.25),
        percentile(positive, 0.50),
        percentile(positive, 0.75),
        percentile(positive, 0.90),
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

    level.thresholds = thresholds
    return level


def fmt_date(date, include_year=False):
    if date is None:
        return "Unavailable"
    if include_year:
        return f"{date.strftime('%b')} {date.day}, {date.year}"
    return f"{date.strftime('%b')} {date.day}"


def generate_svg(counts, metrics, start_date, end_date, level):
    month_names = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    sunday = start_date - timedelta(days=(start_date.weekday() + 1) % 7)
    weeks = []
    current = sunday
    while current <= end_date:
        week = []
        for row in range(7):
            date = current + timedelta(days=row)
            week.append(date)
        weeks.append(week)
        current += timedelta(days=7)

    heatmap = []
    month_labels = []
    for column, week in enumerate(weeks):
        x = 76 + column * 14
        for row, date in enumerate(week):
            if not (start_date <= date <= end_date):
                continue
            y = 174 + row * 14
            count = counts.get(date, 0)
            fill = COLORS[level(count)]
            glow = ' filter="url(#bright-glow)"' if level(count) == 4 else ""
            heatmap.append(
                f'<rect x="{x}" y="{y}" width="10" height="10" rx="2" '
                f'fill="{fill}"{glow}/>'
            )

    for column, week in enumerate(weeks):
        first = week[0]
        month_marker = next((date for date in week if start_date <= date <= end_date), None)
        if month_marker is None:
            continue
        prior_weeks = weeks[:column]
        if column == 0:
            show = True
        else:
            previous_marker = next(
                (date for date in prior_weeks[-1] if start_date <= date <= end_date),
                None,
            )
            show = previous_marker is None or month_marker.month != previous_marker.month
        if show:
            x = 76 + column * 14
            month_labels.append(
                f'<text x="{x}" y="158" fill="#A8959E" '
                f'font-family="Arial, Helvetica, sans-serif" font-size="9">'
                f'{month_names[month_marker.month - 1]}</text>'
            )

    axis = [
        '<text x="42" y="186" text-anchor="end" fill="#A8959E" font-family="Arial, Helvetica, sans-serif" font-size="8.5">Mon</text>',
        '<text x="42" y="214" text-anchor="end" fill="#A8959E" font-family="Arial, Helvetica, sans-serif" font-size="8.5">Wed</text>',
        '<text x="42" y="242" text-anchor="end" fill="#A8959E" font-family="Arial, Helvetica, sans-serif" font-size="8.5">Fri</text>',
    ]

    longest_start = fmt_date(metrics["longest_start"], True)
    longest_end = fmt_date(metrics["longest_end"], True)
    streak_text = (
        f"LONGEST STREAK · {metrics['longest']} DAYS · "
        f"{longest_start} – {longest_end}"
    )
    if metrics["busiest_date"]:
        busiest_date = fmt_date(metrics["busiest_date"], True)
    else:
        busiest_date = "Unavailable"

    annotation_x = 76
    if metrics["longest_start"]:
        offset = (metrics["longest_start"] - sunday).days // 7
        annotation_x = max(76, min(810, 76 + offset * 14))

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="390" viewBox="0 0 900 390" role="img" aria-labelledby="commit-log-title commit-log-desc">
  <title id="commit-log-title">GitHub commit log</title>
  <desc id="commit-log-desc">Real GitHub contribution activity for Gaurikabhatt27.</desc>
  <defs>
    <linearGradient id="commitlog-panel" x1="0" y1="1" x2="1" y2="0">
      <stop offset="0" stop-color="#1A0C13"/>
      <stop offset="0.54" stop-color="#381224"/>
      <stop offset="1" stop-color="#591835"/>
    </linearGradient>
    <radialGradient id="commitlog-glow" cx="0.88" cy="0.12" r="0.66">
      <stop offset="0" stop-color="#A82463" stop-opacity="0.32"/>
      <stop offset="0.55" stop-color="#701A3D" stop-opacity="0.12"/>
      <stop offset="1" stop-color="#1A0C13" stop-opacity="0"/>
    </radialGradient>
    <filter id="bright-glow" x="-100%" y="-100%" width="300%" height="300%">
      <feGaussianBlur stdDeviation="1.25" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
  </defs>

  <rect width="900" height="390" rx="16" fill="url(#commitlog-panel)" stroke="#5A2740" stroke-width="1"/>
  <rect x="1" y="1" width="898" height="388" rx="15" fill="url(#commitlog-glow)"/>

  <g>
    <text x="24" y="34" fill="#D96389" font-family="Consolas, monospace" font-size="9.5" font-weight="700" letter-spacing="1.4">COMMIT LOG · REAL GITHUB ACTIVITY</text>
    <text x="24" y="62" fill="#F5EDF0" font-family="Georgia, 'Times New Roman', serif" font-size="20" font-weight="700">A year of building, one square at a time.</text>
  </g>

  <g font-family="Arial, Helvetica, sans-serif">
    <line x1="480" y1="26" x2="480" y2="82" stroke="#71304C" stroke-width="1"/>
    <line x1="584" y1="26" x2="584" y2="82" stroke="#71304C" stroke-width="1"/>
    <line x1="688" y1="26" x2="688" y2="82" stroke="#71304C" stroke-width="1"/>
    <line x1="792" y1="26" x2="792" y2="82" stroke="#71304C" stroke-width="1"/>

    <text x="500" y="34" fill="#A8959E" font-family="Consolas, monospace" font-size="8" letter-spacing="1">CONTRIBUTIONS</text>
    <text x="500" y="62" fill="#F5EDF0" font-family="Georgia, 'Times New Roman', serif" font-size="21" font-weight="700">{metrics["total"]:,}</text>
    <text x="500" y="78" fill="#B8A3AD" font-size="8">{escape(fmt_date(start_date, True))} – {escape(fmt_date(end_date, True))}</text>

    <text x="604" y="34" fill="#A8959E" font-family="Consolas, monospace" font-size="8" letter-spacing="1">ACTIVE DAYS</text>
    <text x="604" y="62" fill="#F5EDF0" font-family="Georgia, 'Times New Roman', serif" font-size="21" font-weight="700">{metrics["active"]}</text>
    <text x="604" y="78" fill="#B8A3AD" font-size="8">out of { (end_date - start_date).days + 1 } days</text>

    <text x="708" y="34" fill="#A8959E" font-family="Consolas, monospace" font-size="8" letter-spacing="1">LONGEST STREAK</text>
    <text x="708" y="62" fill="#F5EDF0" font-family="Georgia, 'Times New Roman', serif" font-size="21" font-weight="700">{metrics["longest"]}</text>
    <text x="708" y="78" fill="#B8A3AD" font-size="8">consecutive days</text>

    <text x="812" y="34" fill="#A8959E" font-family="Consolas, monospace" font-size="8" letter-spacing="1">BUSIEST DAY</text>
    <text x="812" y="62" fill="#F5EDF0" font-family="Georgia, 'Times New Roman', serif" font-size="21" font-weight="700">{metrics["busiest_count"]}</text>
    <text x="812" y="78" fill="#B8A3AD" font-size="8">{escape(busiest_date)}</text>
  </g>

  <line x1="24" y1="94" x2="876" y2="94" stroke="#71304C" stroke-width="1"/>
  <g>
    {''.join(month_labels)}
    {''.join(axis)}
    {''.join(heatmap)}
  </g>

  <line x1="24" y1="342" x2="876" y2="342" stroke="#71304C" stroke-width="1"/>
  <line x1="{annotation_x}" y1="326" x2="{annotation_x}" y2="342" stroke="#D96389" stroke-width="2"/>
  <text x="24" y="366" fill="#D96389" font-family="Consolas, monospace" font-size="9" font-weight="700" letter-spacing="1">{escape(streak_text)}</text>
</svg>
'''
    return svg


def main():
    end_date = datetime.now(timezone.utc).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=364)
    try:
        token = get_token()
        counts = None
        api_error = None
        if token:
            try:
                calendar = request_contributions(token, start_date, end_date)
                counts = flatten_calendar(calendar, start_date, end_date)
            except Exception as exc:
                api_error = exc

        if counts is None:
            try:
                counts = request_public_contributions(start_date, end_date)
            except Exception as exc:
                if api_error:
                    raise RuntimeError(
                        f"GraphQL failed ({api_error}); public contribution calendar also failed ({exc})"
                    ) from exc
                raise

        returned_start = min(counts)
        returned_end = max(counts)
        if returned_start != start_date or returned_end != end_date:
            start_date = returned_start
            end_date = returned_end

        metrics = calculate_metrics(counts, start_date, end_date)
        level = intensity_levels(counts)
        svg = generate_svg(counts, metrics, start_date, end_date, level)
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        temporary = OUTPUT.with_suffix(".svg.tmp")
        temporary.write_text(svg, encoding="utf-8")
        temporary.replace(OUTPUT)
        print(
            f"Generated {OUTPUT.name}: "
            f"{metrics['total']} contributions, "
            f"{metrics['active']} active days, "
            f"{metrics['longest']} longest streak"
        )
    except Exception as exc:
        print(f"Commit log generation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
