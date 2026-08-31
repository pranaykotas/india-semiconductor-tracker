#!/usr/bin/env python3
"""
Weekly digest agent for India Semiconductor Manufacturing Tracker.

Architecture:
  1. Python fetches search snippets via Google News RSS (free, no API key needed)
  2. Claude synthesizes the snippets into a structured digest (no search tools)
  3. Output written as HTML for readable email delivery

Total token usage: ~3-5k (vs 30-75k with Claude's built-in web_search tool).

Run from the repo root:
    ANTHROPIC_API_KEY=... python scripts/weekly_digest.py
"""

import base64
import os
import sys
import time
from datetime import date

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus

import anthropic
import markdown
import requests
import yaml

# ---------------------------------------------------------------------------
# Search queries
# ---------------------------------------------------------------------------
QUERIES = [
    # Tata fab (Dholera)
    '"Tata Electronics" Dholera semiconductor',
    # Tata ATMP (Morigaon / Jagiroad / TSAT)
    '"TSAT" semiconductor OR "Tata Semiconductor Assembly" Morigaon OR Jagiroad',
    # Micron
    '"Micron" Sanand semiconductor',
    # Kaynes
    '"Kaynes Semicon" OR "Kaynes semiconductor"',
    # CG Power / CG Semi
    '"CG Semi" OR "CG Power" semiconductor Sanand',
    # HCL-Foxconn
    '"HCL Foxconn" semiconductor Jewar OR "HCL semiconductor"',
    # SicSem
    '"SicSem" OR "silicon carbide" India semiconductor fab',
    # RRP Electronics
    '"RRP Electronics" semiconductor',
    # 3D Glass Solutions
    '"3D Glass Solutions" India semiconductor OR "3DGS" Bhubaneswar',
    # CDIL
    '"CDIL" OR "Continental Device India" semiconductor Mohali',
    # ASIP (Advanced System in Package Tech, Visakhapatnam)
    '"ASIP" OR "Advanced System in Package" Visakhapatnam semiconductor',
    # SCL Mohali (Semi-Conductor Laboratory — no query existed before)
    '"SCL" OR "Semi-Conductor Laboratory" Mohali semiconductor',
    # GAETEC Hyderabad (no query existed before)
    '"GAETEC" OR "Gallium Arsenide" India semiconductor Hyderabad',
    # IISc / MNNFC Bengaluru (no query existed before)
    '"MNNFC" OR "IISc" semiconductor fab Bengaluru',
    # ISM policy / approvals
    '"India Semiconductor Mission" approval OR cabinet OR scheme',
    '"India semiconductor" delayed OR "behind schedule" OR slippage',
    '"Modified Semicon Scheme" approved OR disbursement',
    # PIB press releases (reliable via Google News indexing)
    'site:pib.gov.in semiconductor',
    'site:pib.gov.in "India Semiconductor Mission"',
    'site:pib.gov.in MeitY chip OR fab OR OSAT OR ATMP',
]

SYNTHESIS_PROMPT = """\
You are the editor of the India Semiconductor Manufacturing Tracker weekly digest
(live at https://fabs.pranaykotas.com, maintained by Pranay Kotasthane, Takshashila Institution).

## Current state of tracked facilities

```yaml
{facilities_summary}
```

## All tracked facility names (every facility must appear in the digest)

{facility_names}

## Search results from the past week

{search_results}

## Your task

Compare the search results against the current YAML state and write the weekly digest.
Only include updates that represent a CHANGE from what is already in the YAML.
Before flagging anything, check the facility's FULL milestones[] list above (not
just the most recent entry) — news outlets frequently re-report an old
groundbreaking, foundation-stone, or inauguration event days or weeks later with a
fresh publish date. If the event, investment figure, or partner in a search result
already appears anywhere in that facility's milestones/investment/partners, it is
NOT an update — put it under "Confirmed: no news" (or omit), not "Likely updates
needed".
Every facility listed above must appear in exactly one section of the digest.

Use exactly this format:

---

### Likely updates needed

For each high-confidence update (clear source URL, clear change from YAML state):

**[Facility name]**
- What changed: 1-2 sentences
- Source: [URL] (date)
- Suggested YAML edit:
  ```yaml
  <show only the changed fields, and ALWAYS include sources[] and milestones[] entries>
  ```

### Possibly relevant (lower confidence)

Short bullets for items with weaker sources or unclear relevance. Include source URL.

### New ISM approvals / new facilities

Cabinet decisions or announcements for facilities NOT currently tracked.

### Confirmed: no news

List every facility from "All tracked facility names" that does not appear in any
section above. Every facility must be accounted for — do not leave any out.

---

Rules:
- Every claim must cite a URL from the search results above. No invented sources.
- Do not infer updates that aren't in the results.
- YAML schema: id, name, company, partners[], location, type, category,
  investment.total_inr, status, status_detail, delay_confirmed,
  milestones[].date+event, dates.{{announced,approved,construction_start,
  original_expected_completion,date_completion}}, sources[].{{url,title,date}}
- Every "Suggested YAML edit" MUST include both:
  1. A milestones[] entry for the new event (if applicable)
  2. A sources[] entry with the article URL, title, and date — like this:
     milestones:
       - date: "YYYY-MM-DD"
         event: "Description of what happened"
     sources:
       - url: <use the real article URL from the search results, not a proxy URL>
         title: <article headline>
         date: "YYYY-MM-DD"
- Today's date: {today}
"""

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: Arial, Helvetica, sans-serif; max-width: 680px; margin: 0 auto;
          padding: 20px; color: #222; line-height: 1.5; }}
  h2   {{ color: #0D1F3C; border-bottom: 2px solid #0D1F3C; padding-bottom: 6px; }}
  h3   {{ color: #0D1F3C; border-bottom: 1px solid #ddd; padding-bottom: 4px; margin-top: 28px; }}
  code {{ background: #f4f4f4; padding: 2px 5px; border-radius: 3px; font-size: 0.88em; }}
  pre  {{ background: #f4f4f4; padding: 12px; border-radius: 6px; overflow-x: auto;
          font-size: 0.85em; border-left: 3px solid #B85C00; }}
  pre code {{ background: none; padding: 0; }}
  a    {{ color: #1565C0; }}
  hr   {{ border: none; border-top: 1px solid #eee; margin: 24px 0; }}
  ul   {{ padding-left: 20px; }}
  li   {{ margin-bottom: 6px; }}
  strong {{ color: #111; }}
  p    {{ margin: 8px 0; }}
</style>
</head>
<body>
<h2>{subject}</h2>
{content}
</body>
</html>"""


def build_facilities_summary(facilities_yaml: str) -> str:
    """Extract only the comparison-relevant fields from the full YAML."""
    data = yaml.safe_load(facilities_yaml)
    summary = []
    for f in data.get("facilities", []):
        milestones = f.get("milestones") or []
        # Send the full milestone history, not just the last one — otherwise
        # the synthesis step can't tell an already-logged event (e.g. an
        # earlier inauguration or foundation-stone) apart from genuine news,
        # and re-flags recycled articles as "new" updates.
        milestone_log = [
            f"{m.get('date', '')} — {m.get('event', '')}" for m in milestones
        ]
        dates = f.get("dates") or {}
        investment = f.get("investment") or {}
        summary.append({
            "id": f.get("id"),
            "name": f.get("name"),
            "company": f.get("company"),
            "type": f.get("type"),
            "status": f.get("status"),
            "status_detail": f.get("status_detail", ""),
            "delay_confirmed": f.get("delay_confirmed", False),
            "investment_total_inr_cr": investment.get("total_inr", ""),
            "partners": f.get("partners") or [],
            "original_expected_completion": dates.get("original_expected_completion", ""),
            "date_completion": dates.get("date_completion", ""),
            "milestones": milestone_log,
        })
    return yaml.dump(summary, allow_unicode=True, sort_keys=False)


def resolve_google_news_url(url: str) -> str:
    """
    Resolve a Google News RSS proxy URL to the real article URL.

    Strategy 1: base64 decode the URL blob (fast, no network request).
    Strategy 2: HTTP GET to the non-RSS Google News URL (follows HTTP redirect).
    """
    if "news.google.com" not in url:
        return url

    # Strategy 1: decode base64 blob — older Google News format embeds URL directly
    match = re.search(r"news\.google\.com/(?:rss/)?articles/([^?&/]+)", url)
    if match:
        encoded = match.group(1)
        encoded += "=" * (-len(encoded) % 4)
        try:
            data = base64.urlsafe_b64decode(encoded)
            for prefix in (b"https://", b"http://"):
                idx = data.find(prefix)
                if idx != -1:
                    end = idx
                    while end < len(data) and 0x20 <= data[end] < 0x80:
                        end += 1
                    candidate = data[idx:end].decode("ascii", errors="ignore").rstrip(".,)")
                    if "." in candidate and "news.google.com" not in candidate and len(candidate) > 15:
                        return candidate
        except Exception:
            pass

    # Strategy 2: HTTP GET — non-RSS Google News URLs do HTTP redirect
    web_url = re.sub(r"/rss/articles/", "/articles/", url).split("?")[0]
    try:
        resp = requests.get(
            web_url,
            timeout=10,
            allow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        if "news.google.com" not in resp.url:
            return resp.url
    except Exception:
        pass

    return url


def fetch_article_info(url: str) -> tuple[str, datetime | None]:
    """
    Return (resolved_url, published_date).
    Resolves Google News proxy URLs and extracts article:published_time meta tag.
    """
    resolved = resolve_google_news_url(url)

    patterns = [
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'<meta[^>]+name=["\']pubdate["\'][^>]+content=["\']([^"\']+)["\']',
    ]
    try:
        resp = requests.get(
            resolved, timeout=8, stream=True,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        resolved = resp.url  # pick up any further redirects
        chunk = b""
        for data in resp.iter_content(chunk_size=1024):
            chunk += data
            if len(chunk) >= 5120:
                break
        text = chunk.decode("utf-8", errors="ignore")
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                raw = m.group(1).strip()
                raw = re.sub(
                    r"(\d{2}:\d{2}:\d{2})(\+\d{2}:\d{2}|Z)?$",
                    lambda x: x.group(0) if x.group(2) else x.group(1) + "+00:00",
                    raw,
                )
                return resolved, datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return resolved, None
    except Exception:
        pass
    return resolved, None


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

                # Parse and filter by RSS date
                try:
                    pub_date = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %Z")
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                    if pub_date < cutoff:
                        continue
                    date_label = pub_date.strftime("%Y-%m-%d")
                except ValueError:
                    date_label = pub_date_str

                # Resolve proxy URL + verify original article publish date
                resolved_url, actual_date = fetch_article_info(link)
                if actual_date and actual_date < cutoff:
                    continue  # old article re-surfaced by aggregator

                lines.append(f"  - {title} ({date_label})")
                lines.append(f"    URL: {resolved_url}")
                found += 1

            if found == 0:
                lines.append("  (no results in past 7 days)")

        except Exception as e:
            lines.append(f"  (search failed: {e})")

        time.sleep(0.5)

    return "\n".join(lines)


def to_html(subject: str, digest_md: str) -> str:
    """Convert markdown digest to a styled HTML email body."""
    content = markdown.markdown(
        digest_md,
        extensions=["fenced_code"],
    )
    return HTML_TEMPLATE.format(subject=subject, content=content)


def generate_digest(facilities_yaml: str, today: str) -> str:
    print("  Fetching search snippets via Google News RSS...")
    search_results = fetch_snippets(QUERIES)

    facilities_summary = build_facilities_summary(facilities_yaml)

    data = yaml.safe_load(facilities_yaml)
    facility_names = [f.get("name", "") for f in data.get("facilities", [])]
    names_list = "\n".join(f"- {name}" for name in facility_names)

    prompt = SYNTHESIS_PROMPT.format(
        facilities_summary=facilities_summary,
        facility_names=names_list,
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

    os.makedirs("data", exist_ok=True)

    # Plain text file: subject on line 1 (workflow extracts it for email header)
    with open("data/digest.txt", "w") as f:
        f.write(subject + "\n")

    # HTML file: full styled email body
    with open("data/digest.html", "w") as f:
        f.write(to_html(subject, digest))

    print(f"Done. Written to data/digest.html ({len(digest):,} chars)")


if __name__ == "__main__":
    main()
