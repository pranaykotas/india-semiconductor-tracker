#!/usr/bin/env python3
"""
Quarterly sweep for Indian fabless firms and GCC design centre updates.

Architecture (mirrors weekly_digest.py):
  1. Python fetches search snippets via Google News RSS
  2. Claude compares against current design.yml and proposes additions/updates
  3. Output written as HTML email for manual review

Run from the repo root:
    ANTHROPIC_API_KEY=... python scripts/design_sweep.py
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
# Search queries — broader than weekly digest, covers design ecosystem
# ---------------------------------------------------------------------------
QUERIES = [
    # DLI scheme
    '"Design Linked Incentive" semiconductor India',
    '"DLI scheme" semiconductor approved OR beneficiary',
    'MeitY "chip design" India approved OR scheme',
    # Indian fabless firms
    '"Indian fabless" semiconductor',
    '"RISC-V" India chip design startup',
    '"Signalchip" semiconductor',
    '"Mindgrove" semiconductor',
    '"VVDN" semiconductor chip',
    '"Saankhya Labs" semiconductor',
    '"Incore Semiconductors" RISC-V',
    '"Steradian" semiconductor',
    '"Terminus Circuits" semiconductor',
    # GCC expansions
    '"Qualcomm India" semiconductor design OR R&D OR expansion',
    '"Intel India" semiconductor design OR R&D OR headcount',
    '"AMD India" semiconductor design OR expansion',
    '"Texas Instruments" India semiconductor',
    '"Samsung" India semiconductor design',
    '"Broadcom" India semiconductor design',
    '"NXP" India semiconductor design',
    '"Infineon" India semiconductor design',
    '"STMicroelectronics" India semiconductor',
    '"MediaTek" India semiconductor design',
    '"Synopsys" India semiconductor',
    '"Cadence" India semiconductor',
    '"ARM" India semiconductor design OR R&D',
    '"Renesas" India semiconductor',
    '"Analog Devices" India semiconductor',
    # General design ecosystem
    'India semiconductor design centre expansion OR new',
    'India chip design GCC headcount OR hiring',
]

SYNTHESIS_PROMPT = """\
You are the editor of the India Semiconductor Tracker's design firms section
(live at https://fabs.pranaykotas.com/design.html, maintained by Pranay Kotasthane,
Takshashila Institution).

## Currently tracked design firms

```yaml
{design_summary}
```

## Search results from the past 90 days

{search_results}

## Your task

Compare the search results against the currently tracked firms and produce a sweep report.

Use exactly this format:

---

### New firms to add

For each firm found in results that is NOT in the current YAML:

**[Firm name]**
- Category: Indian Fabless / DLI Beneficiary / GCC Design Centre
- Why add: 1-2 sentences
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

### No news found

List every tracked firm not mentioned in any section above.

---

Rules:
- Every claim must cite a URL from the search results. No invented sources.
- Do not infer updates not supported by results.
- Prioritise: new DLI approvals > new GCC centres > headcount changes > product announcements.
- For Indian fabless, note if they are DLI beneficiaries.
- For GCCs, note India headcount and locations if mentioned.
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


def fetch_snippets(queries: list[str], max_results: int = 5, lookback_days: int = 90) -> str:
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


def build_design_summary(design_yaml: str) -> str:
    data = yaml.safe_load(design_yaml)
    summary = []
    for f in data.get("design_firms", []):
        locs = f.get("locations", [])
        cities = ", ".join(l.get("city", "") for l in locs)
        summary.append({
            "id": f.get("id"),
            "name": f.get("name"),
            "category": f.get("category"),
            "parent_company": f.get("parent_company"),
            "product_focus": f.get("product_focus"),
            "india_headcount": f.get("india_headcount"),
            "cities": cities,
        })
    return yaml.dump(summary, allow_unicode=True, sort_keys=False)


def to_html(subject: str, digest_md: str) -> str:
    content = markdown.markdown(digest_md, extensions=["fenced_code"])
    return HTML_TEMPLATE.format(subject=subject, content=content)


def generate_sweep(design_yaml: str, today: str) -> str:
    print("  Fetching search snippets (90-day lookback)...")
    search_results = fetch_snippets(QUERIES)

    design_summary = build_design_summary(design_yaml)

    prompt = SYNTHESIS_PROMPT.format(
        design_summary=design_summary,
        search_results=search_results,
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
        with open("data/design.yml") as f:
            design_yaml = f.read()
    except FileNotFoundError:
        print("ERROR: data/design.yml not found. Run from repo root.", file=sys.stderr)
        sys.exit(1)

    today = date.today().isoformat()
    subject = f"[Semicon Tracker] Design firm sweep — {today}"

    print(f"Running design firm sweep for {today}...")
    sweep = generate_sweep(design_yaml, today)

    os.makedirs("data", exist_ok=True)

    with open("data/design-sweep.txt", "w") as f:
        f.write(subject + "\n")

    with open("data/design-sweep.html", "w") as f:
        f.write(to_html(subject, sweep))

    print(f"Done. Written to data/design-sweep.html ({len(sweep):,} chars)")


if __name__ == "__main__":
    main()
