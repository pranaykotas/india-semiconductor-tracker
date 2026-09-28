#!/usr/bin/env python3
"""
Quarterly (+ post-SEMICON India) sweep for semiconductor equipment,
gases/chemicals, and materials/substrate investments in India.

Architecture (mirrors design_sweep.py / weekly_digest.py):
  1. Python fetches search snippets via Google News RSS
  2. Claude compares against current equipment_materials.yml and proposes
     additions/updates
  3. Output written as HTML email for manual review

This tracker only includes firms with their OWN disclosed India facility
or investment — not every company that has signed a supply MoU with a
fab already tracked in facilities.yml (those stay as milestones on the
buyer's own facility page). The synthesis prompt enforces that bar.

Run from the repo root:
    ANTHROPIC_API_KEY=... python scripts/equipment_sweep.py
"""

import os
import re
import sys
import time
import base64
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone, timedelta
from urllib.parse import quote_plus

import anthropic
import markdown
import requests
import yaml

# ---------------------------------------------------------------------------
# Search queries — equipment makers, gases/chemicals, materials/substrates
# ---------------------------------------------------------------------------
QUERIES = [
    # Equipment majors
    '"Applied Materials" India investment OR facility OR expansion',
    '"Lam Research" India investment OR facility OR manufacturing',
    '"Tokyo Electron" India investment OR facility OR centre',
    '"ASML" India office OR facility OR investment',
    '"KLA Corporation" India investment OR facility OR campus',
    '"Teradyne" India office OR facility OR investment',
    '"Entegris" India investment OR facility',
    # Gases & chemicals
    '"Linde India" semiconductor gas OR facility',
    '"INOX Air Products" semiconductor OR Dholera OR Sanand',
    '"Air Liquide" India semiconductor',
    '"Merck Electronics" India semiconductor chemicals',
    '"SK Materials" India semiconductor',
    '"Versum Materials" India',
    'semiconductor specialty gas OR UHP gas India facility',
    # Materials & substrates
    'silicon wafer manufacturing India investment',
    'photoresist OR "CMP slurry" India semiconductor',
    'quartz OR ceramic components India semiconductor facility',
    'semiconductor substrate India investment OR facility',
    # Scheme / policy
    '"Semicon 2.0" equipment OR materials',
    'India Semiconductor Mission equipment materials scheme',
    # PIB press releases
    'site:pib.gov.in semiconductor equipment OR materials OR gases',
    # General
    'SEMICON India semiconductor equipment materials investment announcement',
]

SYNTHESIS_PROMPT = """\
You are the editor of the India Semiconductor Tracker's equipment &
materials section (live at https://fabs.pranaykotas.com/equipment.html,
maintained by Pranay Kotasthane, Takshashila Institution).

## Currently tracked equipment/materials firms

```yaml
{equipment_summary}
```

## Search results from the past {lookback} days

{search_results}

## Your task

Compare the search results against the currently tracked firms and
produce a sweep report.

CRITICAL INCLUSION BAR: only flag a firm if it has its OWN disclosed
India facility, investment, or standalone operation (an R&D centre, a
manufacturing plant, a dedicated office with real headcount, etc.). Do
NOT flag a firm whose only India news is signing a supply MoU with a
fab or OSAT already tracked elsewhere on this site (e.g. "X signs deal
to supply Tata's Dholera fab") — those belong as a milestone on that
fab's own page, not here. If you are unsure whether a firm clears this
bar, say so explicitly rather than guessing.

Use exactly this format:

---

### New firms to add

For each firm found in results that clears the inclusion bar and is
NOT in the current YAML:

**[Firm name]**
- Category: Equipment Manufacturer / Gases & Chemicals / Materials & Substrates / Infrastructure & Services
- Why add: 1-2 sentences, and why it clears the "own facility" bar specifically
- Source: [URL] (date)
- Suggested YAML entry:
  ```yaml
  - id: suggested-id
    name: "..."
    category: "..."
    # ... fill what's known, use null for unknown fields
  ```

### Updates to existing firms

For each tracked firm with new information:

**[Firm name]**
- What changed: 1-2 sentences
- Source: [URL] (date)
- Suggested field changes:
  ```yaml
  field_name: new_value
  ```

### Supply relationships only (NOT added, for awareness)

Firms whose only India news is an MoU/supply relationship with an
already-tracked fab or OSAT — these do not get their own entry, but
flag them so Pranay can check whether the buyer's facility page has
this milestone recorded yet.

### No news found

List every tracked firm not mentioned in any section above.

---

Rules:
- Every claim must cite a URL from the search results. No invented sources.
- Do not infer updates not supported by results.
- Prioritise: new standalone facility announcements > investment figure changes > status changes (Announced → Under Construction → Operational) > headcount/hiring news.
- If a reported investment figure conflicts with what's currently tracked, flag the discrepancy explicitly rather than silently preferring one number.
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
          font-size: 0.85em; border-left: 3px solid #E65100; }}
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

LOOKBACK_DAYS = 90


def resolve_google_news_url(url: str) -> str:
    if "news.google.com" not in url:
        return url

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

    web_url = re.sub(r"/rss/articles/", "/articles/", url).split("?")[0]
    try:
        resp = requests.get(
            web_url, timeout=10, allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
        )
        if "news.google.com" not in resp.url:
            return resp.url
    except Exception:
        pass

    return url


def fetch_snippets(queries: list[str], max_results: int = 5, lookback_days: int = LOOKBACK_DAYS) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
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

                try:
                    pub_date = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %Z")
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                    if pub_date < cutoff:
                        continue
                    date_label = pub_date.strftime("%Y-%m-%d")
                except ValueError:
                    date_label = pub_date_str

                resolved_url = resolve_google_news_url(link)
                lines.append(f"  - {title} ({date_label})")
                lines.append(f"    URL: {resolved_url}")
                found += 1

            if found == 0:
                lines.append(f"  (no results in past {lookback_days} days)")

        except Exception as e:
            lines.append(f"  (search failed: {e})")

        time.sleep(0.5)

    return "\n".join(lines)


def build_equipment_summary(equipment_yaml: str) -> str:
    data = yaml.safe_load(equipment_yaml)
    summary = []
    for f in data.get("equipment_materials", []):
        inv = f.get("investment") or {}
        summary.append({
            "id": f.get("id"),
            "name": f.get("name"),
            "category": f.get("category"),
            "parent_company": f.get("parent_company"),
            "city": (f.get("location") or {}).get("city"),
            "status": f.get("status"),
            "investment_inr_cr": inv.get("total_inr"),
            "investment_usd_m": inv.get("total_usd_million"),
            "supplies_to": f.get("supplies_to") or [],
        })
    return yaml.dump(summary, allow_unicode=True, sort_keys=False)


def to_html(subject: str, digest_md: str) -> str:
    content = markdown.markdown(digest_md, extensions=["fenced_code"])
    return HTML_TEMPLATE.format(subject=subject, content=content)


def generate_sweep(equipment_yaml: str, today: str) -> str:
    print(f"  Fetching search snippets ({LOOKBACK_DAYS}-day lookback)...")
    search_results = fetch_snippets(QUERIES)

    equipment_summary = build_equipment_summary(equipment_yaml)

    prompt = SYNTHESIS_PROMPT.format(
        equipment_summary=equipment_summary,
        search_results=search_results,
        lookback=LOOKBACK_DAYS,
        today=today,
    )

    print(f"  Sending to Claude for synthesis (~{len(prompt.split()):,} words)...")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    text_blocks = [b.text for b in response.content if hasattr(b, "text") and b.text]
    return text_blocks[-1] if text_blocks else "No sweep results generated."


def main():
    try:
        with open("data/equipment_materials.yml") as f:
            equipment_yaml = f.read()
    except FileNotFoundError:
        print("ERROR: data/equipment_materials.yml not found. Run from repo root.", file=sys.stderr)
        sys.exit(1)

    today = date.today().isoformat()
    subject = f"[Semicon Tracker] Equipment & materials sweep — {today}"

    print(f"Running equipment & materials sweep for {today}...")
    sweep = generate_sweep(equipment_yaml, today)

    os.makedirs("data", exist_ok=True)

    with open("data/equipment-sweep.txt", "w") as f:
        f.write(subject + "\n")

    with open("data/equipment-sweep.html", "w") as f:
        f.write(to_html(subject, sweep))

    print(f"Done. Written to data/equipment-sweep.html ({len(sweep):,} chars)")


if __name__ == "__main__":
    main()
