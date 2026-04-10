#!/usr/bin/env python3
"""
Weekly digest agent for India Semiconductor Manufacturing Tracker.

Architecture:
  1. Python fetches search snippets via DuckDuckGo (free, no API key needed)
  2. Claude synthesizes the snippets into a structured digest (no search tools)

Total token usage: ~3-5k (vs 30-75k with Claude's built-in web_search tool).

Run from the repo root:
    ANTHROPIC_API_KEY=... python scripts/weekly_digest.py
"""

import os
import sys
import time
from datetime import date

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus

import anthropic
import requests
import yaml

# ---------------------------------------------------------------------------
# Search queries
# ---------------------------------------------------------------------------
QUERIES = [
    '"Tata Electronics" Dholera semiconductor',
    '"Tata Semiconductor" Jagiroad OR Morigaon',
    '"Micron" Sanand semiconductor',
    '"Kaynes Semicon"',
    '"CG Semi" OR "CG Power" semiconductor',
    '"HCL Foxconn" semiconductor Jewar',
    '"SicSem" silicon carbide',
    '"RRP Electronics" semiconductor',
    '"3D Glass Solutions" India semiconductor',
    '"CDIL" semiconductor Mohali',
    '"ASIP" Visakhapatnam semiconductor',
    '"India Semiconductor Mission" approval OR cabinet',
    '"India semiconductor" delayed OR "behind schedule"',
    '"Modified Semicon Scheme" approved',
]

SYNTHESIS_PROMPT = """\
You are the editor of the India Semiconductor Manufacturing Tracker weekly digest
(live at https://fabs.pranaykotas.com, maintained by Pranay Kotasthane, Takshashila Institution).

## Current state of tracked facilities

```yaml
{facilities_summary}
```

## Search results from the past week

{search_results}

## Your task

Compare the search results against the current YAML state and write the weekly digest.
Only include items that represent a CHANGE from what is already in the YAML.

Use exactly this format:

---

### Likely updates needed

For each high-confidence update (clear source URL, clear change from YAML state):

**[Facility name]**
- What changed: 1-2 sentences
- Source: [URL] (date)
- Suggested YAML edit:
  ```yaml
  <show only the changed fields>
  ```

### Possibly relevant (lower confidence)

Short bullets for items with weaker sources or unclear relevance. Include source URL.

### New ISM approvals / new facilities

Cabinet decisions or announcements for facilities NOT currently tracked.

### Confirmed: no news

Facilities with no relevant updates found. List names only.

---

Rules:
- Every claim must cite a URL from the search results above. No invented sources.
- Do not infer updates that aren't in the results.
- YAML schema: id, name, company, partners[], location, type, category,
  investment.total_inr, status, status_detail, delay_confirmed,
  milestones[].date+event, dates.{{announced,approved,construction_start,
  original_expected_completion,date_completion}}, sources[].{{url,title,date}}
- Today's date: {today}
"""


def build_facilities_summary(facilities_yaml: str) -> str:
    """Extract only the comparison-relevant fields from the full YAML."""
    data = yaml.safe_load(facilities_yaml)
    summary = []
    for f in data.get("facilities", []):
        milestones = f.get("milestones") or []
        last_milestone = ""
        if milestones:
            m = milestones[-1]
            last_milestone = f"{m.get('date', '')} — {m.get('event', '')}"
        dates = f.get("dates") or {}
        summary.append({
            "id": f.get("id"),
            "name": f.get("name"),
            "company": f.get("company"),
            "type": f.get("type"),
            "status": f.get("status"),
            "status_detail": f.get("status_detail", ""),
            "delay_confirmed": f.get("delay_confirmed", False),
            "original_expected_completion": dates.get("original_expected_completion", ""),
            "date_completion": dates.get("date_completion", ""),
            "last_milestone": last_milestone,
        })
    return yaml.dump(summary, allow_unicode=True, sort_keys=False)


def get_article_published_date(url: str) -> datetime | None:
    """
    Fetch the first 5KB of an article and extract its original publication date
    from meta tags. Returns None if date cannot be determined.
    This catches cases where aggregators (MSN, Yahoo) re-surface old articles
    with a fresh RSS date.
    """
    patterns = [
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'<meta[^>]+name=["\']pubdate["\'][^>]+content=["\']([^"\']+)["\']',
    ]
    try:
        resp = requests.get(url, timeout=8, stream=True, headers={"User-Agent": "Mozilla/5.0"})
        # Read only the first 5KB — enough for <head> meta tags
        chunk = b""
        for data in resp.iter_content(chunk_size=1024):
            chunk += data
            if len(chunk) >= 5120:
                break
        text = chunk.decode("utf-8", errors="ignore")
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                raw = match.group(1).strip()
                # Handle ISO 8601 with various timezone formats
                raw = re.sub(r"(\d{2}:\d{2}:\d{2})(\+\d{2}:\d{2}|Z)?$",
                             lambda m: m.group(0) if m.group(2) else m.group(1) + "+00:00",
                             raw)
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        pass
    return None


def fetch_snippets(queries: list[str], max_results: int = 3) -> str:
    """
    Fetch news via Google News RSS (free, no API key, India-focused).
    Returns a plain-text block with title, URL, and date per result.
    Only returns articles from the past 7 days.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    lines = []

    for query in queries:
        lines.append(f"\n### Query: {query}")
        try:
            url = (
                f"https://news.google.com/rss/search"
                f"?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"
            )
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()

            root = ET.fromstring(resp.content)
            items = root.findall(".//item")
            found = 0
            for item in items:
                if found >= max_results:
                    break
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub_date_str = (item.findtext("pubDate") or "").strip()

                # Parse and filter by date
                try:
                    pub_date = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %Z")
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                    if pub_date < cutoff:
                        continue
                    date_label = pub_date.strftime("%Y-%m-%d")
                except ValueError:
                    date_label = pub_date_str

                # Verify original article date — catches aggregators re-surfacing old content
                actual_date = get_article_published_date(link)
                if actual_date and actual_date < cutoff:
                    continue  # article is older than 7 days despite fresh RSS date

                lines.append(f"  - {title} ({date_label})")
                lines.append(f"    URL: {link}")
                found += 1

            if found == 0:
                lines.append("  (no results in past 7 days)")

        except Exception as e:
            lines.append(f"  (search failed: {e})")

        time.sleep(0.5)

    return "\n".join(lines)


def generate_digest(facilities_yaml: str, today: str) -> str:
    print("  Fetching search snippets via DuckDuckGo...")
    search_results = fetch_snippets(QUERIES)

    facilities_summary = build_facilities_summary(facilities_yaml)

    prompt = SYNTHESIS_PROMPT.format(
        facilities_summary=facilities_summary,
        search_results=search_results,
        today=today,
    )

    print(f"  Sending to Claude for synthesis (~{len(prompt.split()):,} words)...")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    text_blocks = [b.text for b in response.content if hasattr(b, "text") and b.text]
    return text_blocks[-1] if text_blocks else "No digest generated."


def main():
    try:
        with open("data/facilities.yml") as f:
            facilities_yaml = f.read()
    except FileNotFoundError:
        print("ERROR: data/facilities.yml not found. Run from repo root.", file=sys.stderr)
        sys.exit(1)

    today = date.today().isoformat()
    subject = f"[Semicon Tracker] Weekly digest — {today}"

    print(f"Generating weekly digest for {today}...")
    digest = generate_digest(facilities_yaml, today)

    # Subject on first line so the workflow can extract it for the email header
    output = f"{subject}\n\n{digest}"
    os.makedirs("data", exist_ok=True)
    with open("data/digest.txt", "w") as f:
        f.write(output)

    print(f"Done. Written to data/digest.txt ({len(digest):,} chars)")


if __name__ == "__main__":
    main()
