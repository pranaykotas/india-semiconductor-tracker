#!/usr/bin/env python3
"""
Weekly digest agent for India Semiconductor Manufacturing Tracker.

Calls Claude (claude-sonnet-4-6) with web_search to research the past week's
news about each tracked facility, then writes the digest to data/digest.txt.

Run from the repo root:
    ANTHROPIC_API_KEY=... python scripts/weekly_digest.py
"""

import os
import sys
from datetime import date

import anthropic

PROMPT_TEMPLATE = """\
You are the weekly digest agent for the India Semiconductor Manufacturing Tracker
(maintained by Pranay Kotasthane at the Takshashila Institution, live at https://fabs.pranaykotas.com).

## Current facility data

```yaml
{facilities_yaml}
```

## Your task

Scan the past 7 days of news for updates relevant to the 14 facilities above, plus
any new India Semiconductor Mission (ISM) approvals. Produce a concise digest.

## Step 1 — Note the current state
For each facility, note: current `status`, latest milestone date, `delay_confirmed`
flag, and `dates.original_expected_completion`.

## Step 2 — Search for news (past 7 days)

Use web_search for each query below. Prioritise sources: PIB (pib.gov.in),
Economic Times, Business Standard, Mint, Moneycontrol, Reuters, company press releases.

Facility-specific:
- "Tata Electronics" Dholera semiconductor
- "Tata Semiconductor" Jagiroad OR Morigaon
- "Micron" Sanand semiconductor
- "Kaynes Semicon"
- "CG Semi" OR "CG Power" semiconductor
- "HCL Foxconn" semiconductor Jewar
- "SicSem" silicon carbide
- "RRP Electronics" semiconductor
- "3D Glass Solutions" India semiconductor
- "CDIL" semiconductor Mohali
- "ASIP" Visakhapatnam semiconductor

Programme-level (catches new ISM approvals and slippage stories):
- "India Semiconductor Mission" approval OR cabinet
- "India semiconductor" delayed OR "behind schedule"
- "Modified Semicon Scheme" approved

## Step 3 — Compare findings to YAML state

For each news item found:
- Already reflected in the YAML? Skip.
- Is it a new milestone, status change, slippage signal, or new facility?
- Does it have a verifiable source URL? If not, omit it entirely. No URL = no suggestion.

## Step 4 — Write the digest

Use exactly this structure:

### Likely updates needed
[Facility name]
- What changed: 1-2 sentences
- Source: [URL] (date)
- Suggested YAML edit:
  ```yaml
  <diff showing only the changed fields>
  ```

### Possibly relevant (lower confidence)
Items with weaker sources or unclear relevance. Short bullets with source URLs.

### New ISM approvals / new facilities
Any cabinet decisions or company announcements for facilities not currently tracked.

### Confirmed: no news
Facilities checked with no relevant updates this week. List facility names only.

---

## Strict rules
- Do NOT suggest committing, pushing, or modifying files. This is a read-only digest.
- Every claim must have a source URL. Hallucinated sources are worse than omissions.
- Flag uncertainty clearly — put low-confidence items in "Possibly relevant".
- Keep the digest short enough to triage in 10 minutes.
- YAML schema for suggested edits: id, name, company, partners[], location, type,
  category, investment.total_inr, status, status_detail, delay_confirmed, narrative,
  milestones[].date+event, complexity, dates.{{announced, approved, construction_start,
  original_expected_completion, date_completion}}, sources[].{{url, title, date}}
- Today's date: {today}
"""


def generate_digest(facilities_yaml: str, today: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    prompt = PROMPT_TEMPLATE.format(facilities_yaml=facilities_yaml, today=today)
    messages = [{"role": "user", "content": prompt}]

    # Agentic loop — Claude may call web_search multiple times before finishing
    for turn in range(20):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8096,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 20,
            }],
            messages=messages,
        )

        # Collect text blocks from this response
        text_blocks = [b.text for b in response.content if hasattr(b, "text") and b.text]

        if response.stop_reason == "end_turn":
            return text_blocks[-1] if text_blocks else "No digest generated."

        if response.stop_reason == "tool_use":
            # Append assistant turn and continue the loop
            messages.append({"role": "assistant", "content": response.content})
            # For server-side tools the API may not need explicit tool_result,
            # but include empty ones for safety
            tool_results = [
                {"type": "tool_result", "tool_use_id": b.id, "content": ""}
                for b in response.content
                if b.type == "tool_use"
            ]
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
        else:
            return text_blocks[-1] if text_blocks else f"Stopped unexpectedly: {response.stop_reason}"

    return "Digest generation reached the maximum number of turns without completing."


def main():
    try:
        with open("data/facilities.yml") as f:
            facilities_yaml = f.read()
    except FileNotFoundError:
        print("ERROR: data/facilities.yml not found. Run from the repo root.", file=sys.stderr)
        sys.exit(1)

    today = date.today().isoformat()
    subject = f"[Semicon Tracker] Weekly digest — {today}"

    print(f"Generating weekly digest for {today}...")
    digest = generate_digest(facilities_yaml, today)

    # Write subject on first line (extracted by workflow for email subject header),
    # then a blank line, then the body.
    output = f"{subject}\n\n{digest}"
    os.makedirs("data", exist_ok=True)
    with open("data/digest.txt", "w") as f:
        f.write(output)

    print(f"Done. Written to data/digest.txt ({len(digest):,} chars)")


if __name__ == "__main__":
    main()
