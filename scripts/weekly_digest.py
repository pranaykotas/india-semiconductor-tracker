#!/usr/bin/env python3
"""
Weekly digest agent for India Semiconductor Manufacturing Tracker.

Architecture: searches run in small independent batches (fresh context each time)
so web search results never accumulate past the 30k input-token/min rate limit.
A final synthesis call combines all batch findings into the structured digest.

Run from the repo root:
    ANTHROPIC_API_KEY=... python scripts/weekly_digest.py
"""

import os
import sys
import time
from datetime import date

import anthropic
import yaml

# ---------------------------------------------------------------------------
# Search batches — each batch runs as a separate API call with fresh context.
# Max 5 searches per batch to keep input tokens well under the 30k/min limit.
# ---------------------------------------------------------------------------
SEARCH_BATCHES = [
    {
        "label": "Batch 1 — Tata / Micron / Kaynes / CG Semi",
        "queries": [
            '"Tata Electronics" Dholera semiconductor',
            '"Tata Semiconductor" Jagiroad OR Morigaon',
            '"Micron" Sanand semiconductor',
            '"Kaynes Semicon"',
            '"CG Semi" OR "CG Power" semiconductor',
        ],
    },
    {
        "label": "Batch 2 — HCL Foxconn / SicSem / 3D Glass / CDIL / ASIP",
        "queries": [
            '"HCL Foxconn" semiconductor Jewar',
            '"SicSem" silicon carbide',
            '"3D Glass Solutions" India semiconductor',
            '"CDIL" semiconductor Mohali',
            '"ASIP" Visakhapatnam semiconductor',
        ],
    },
    {
        "label": "Batch 3 — RRP + programme-level (ISM approvals / delays)",
        "queries": [
            '"RRP Electronics" semiconductor',
            '"India Semiconductor Mission" approval OR cabinet',
            '"India semiconductor" delayed OR "behind schedule"',
            '"Modified Semicon Scheme" approved',
        ],
    },
]

BATCH_PROMPT = """\
You are a research assistant for the India Semiconductor Manufacturing Tracker.

Run each of the following web searches (past 7 days only) and report what you find.
For each result, include: facility/topic, what happened, source URL, and publication date.
Omit anything without a verifiable source URL.

Searches to run:
{queries}

Return a concise bullet-point summary of findings. Be factual. No hallucination.
Today's date: {today}
"""

SYNTHESIS_PROMPT = """\
You are the editor of the India Semiconductor Manufacturing Tracker weekly digest
(live at https://fabs.pranaykotas.com, maintained by Pranay Kotasthane, Takshashila Institution).

## Current state of tracked facilities

```yaml
{facilities_summary}
```

## Research findings from this week's news searches

{batch_findings}

## Your task

Compare the research findings against the current facility state above and write
the weekly digest. Only include items that represent a CHANGE from the current YAML state.

Use exactly this format:

---

### Likely updates needed

For each high-confidence update (clear source, clear change from YAML state):

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

Any cabinet decisions or company announcements for facilities NOT currently tracked.

### Confirmed: no news

Facilities checked with no relevant updates. List names only.

---

Rules:
- Every claim must have a source URL from the research findings above.
- Do not invent or infer updates not present in the findings.
- YAML schema: id, name, company, partners[], location, type, category,
  investment.total_inr, status, status_detail, delay_confirmed,
  milestones[].date+event, dates.{{announced,approved,construction_start,
  original_expected_completion,date_completion}}, sources[].{{url,title,date}}
- Today's date: {today}
"""


def build_facilities_summary(facilities_yaml: str) -> str:
    """Extract only the fields needed for comparison."""
    data = yaml.safe_load(facilities_yaml)
    summary = []
    for f in data.get("facilities", []):
        milestones = f.get("milestones") or []
        last_milestone = ""
        if milestones:
            last = milestones[-1]
            last_milestone = f"{last.get('date', '')} — {last.get('event', '')}"
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


def run_with_retry(client, **kwargs) -> anthropic.types.Message:
    """Call client.messages.create with one retry on rate limit (90s wait)."""
    for attempt in range(3):
        try:
            return client.messages.create(**kwargs)
        except anthropic.RateLimitError:
            if attempt < 2:
                wait = 90 * (attempt + 1)
                print(f"Rate limit hit — waiting {wait}s before retry {attempt + 2}/3...")
                time.sleep(wait)
            else:
                raise


def run_search_batch(client, batch: dict, today: str) -> str:
    """Run one search batch with a fresh context. Returns a findings summary."""
    print(f"  Running {batch['label']}...")
    queries_text = "\n".join(f"- {q}" for q in batch["queries"])
    prompt = BATCH_PROMPT.format(queries=queries_text, today=today)
    messages = [{"role": "user", "content": prompt}]

    for _ in range(10):
        response = run_with_retry(
            client,
            model="claude-sonnet-4-6",
            max_tokens=4096,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
            messages=messages,
        )

        text_blocks = [b.text for b in response.content if hasattr(b, "text") and b.text]

        if response.stop_reason == "end_turn":
            return text_blocks[-1] if text_blocks else "(no findings)"

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = [
                {"type": "tool_result", "tool_use_id": b.id, "content": ""}
                for b in response.content
                if b.type == "tool_use"
            ]
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
        else:
            return text_blocks[-1] if text_blocks else f"(stopped: {response.stop_reason})"

    return "(batch reached max turns)"


def synthesize_digest(client, batch_findings: list[str], facilities_summary: str, today: str) -> str:
    """Single synthesis call — no tools, just text. Combines batch findings into digest."""
    print("  Synthesizing final digest...")
    combined = "\n\n---\n\n".join(
        f"**{SEARCH_BATCHES[i]['label']}**\n\n{findings}"
        for i, findings in enumerate(batch_findings)
    )
    prompt = SYNTHESIS_PROMPT.format(
        facilities_summary=facilities_summary,
        batch_findings=combined,
        today=today,
    )
    response = run_with_retry(
        client,
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

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    facilities_summary = build_facilities_summary(facilities_yaml)

    # Step 1: Run all search batches independently
    batch_findings = []
    for batch in SEARCH_BATCHES:
        findings = run_search_batch(client, batch, today)
        batch_findings.append(findings)

    # Step 2: Synthesize into final digest (no tools — just text)
    digest = synthesize_digest(client, batch_findings, facilities_summary, today)

    # Write output — subject on first line for workflow to extract
    output = f"{subject}\n\n{digest}"
    os.makedirs("data", exist_ok=True)
    with open("data/digest.txt", "w") as f:
        f.write(output)

    print(f"Done. Written to data/digest.txt ({len(digest):,} chars)")


if __name__ == "__main__":
    main()
