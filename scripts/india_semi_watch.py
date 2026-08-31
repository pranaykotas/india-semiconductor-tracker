#!/usr/bin/env python3
"""
Monthly "India Semi Watch" draft generator for the India Semiconductor
Tracker (fabs.pranaykotas.com).

Purpose: email Pranay a ready-to-edit draft for the recurring "India Semi
Watch" section in Siliconpolitik (hightechir.substack.com), covering both
fab/OSAT facilities and fabless/design firms.

Two ingredients, deliberately kept separate:
  1. A TIMELINE CHECK computed by pure date logic from data/facilities.yml
     (no LLM involved — always accurate, never stale).
  2. A "what's new" draft, written by Claude from recent milestones/sources
     across both facilities.yml and design.yml (~35-day lookback).

This is a DRAFT, not an auto-post — output is emailed for editing, same as
weekly_digest.py. No Substack/Twitter API calls.

Run from the repo root:
    ANTHROPIC_API_KEY=... python scripts/india_semi_watch.py
"""

import os
import sys
from datetime import date, datetime, timedelta

import anthropic
import yaml

# Reuse the HTML wrapper and helpers already built for the weekly digest.
from weekly_digest import to_html

LOOKBACK_DAYS = 35

SYNTHESIS_PROMPT = """\
You are drafting the "India Semi Watch" section for Siliconpolitik, the
semiconductor-geopolitics newsletter within Technopolitik
(hightechir.substack.com), written by Pranay Kotasthane at the Takshashila
Institution. This section covers India's semiconductor manufacturing AND
chip-design ecosystem, drawing on the live tracker at
https://fabs.pranaykotas.com.

Siliconpolitik's house style: short titled sub-sections, each a recent
development followed by a few sentences of concrete analysis — not a news
summary, not hype. Direct, domain-expert register. No jargon like
"ecosystem synergies" or "leveraging."

## Recent facility milestones (last {lookback} days)

{facility_recent}

## Recent design-firm developments (last {lookback} days)

{design_recent}

## Timeline check (already computed — DO NOT recompute or restate the dates
## yourself, just weave a short intro sentence around this block verbatim)

{timeline_check}

## Your task

Write the "India Semi Watch — {month_year}" section, up to ~500 words total:

1. A short intro line.
2. One or two "what's new" items drawn ONLY from the recent facility/design
   data above — real product ships, milestones, DLI progress, new
   approvals. If nothing genuinely new happened this window, say so
   plainly in one sentence rather than inventing content — do not pad.
3. Include the **Timeline check** block near-verbatim (you may adjust
   surrounding prose, but do not alter the facility names, figures, or
   delayed/on-track classification given to you).
4. Close with a one-line pointer to https://fabs.pranaykotas.com (and
   https://fabs.pranaykotas.com/design.html for design-firm detail).

Format in Markdown: a level-3 heading, then prose/bullets. Do not invent
sources or figures beyond what's given above.
"""


def load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except ValueError:
        return None


def compute_timeline_check(facilities: list[dict], today: date) -> str:
    """Pure date logic — no LLM. Delayed vs on-track, per the plan's rule:
    Delayed  = delay_confirmed True, OR original_expected_completion is in
               the past with status not Operational/Cancelled and no
               date_completion set.
    On track = active status with original_expected_completion in the
               future, not delayed.
    """
    delayed = []
    on_track = []

    for f in facilities:
        status = f.get("status")
        if status in ("Operational", "Cancelled"):
            continue

        dates = f.get("dates") or {}
        orig = parse_date(dates.get("original_expected_completion"))
        completion = parse_date(dates.get("date_completion"))
        flagged = bool(f.get("delay_confirmed"))

        if not orig:
            continue  # no baseline to judge against

        is_delayed = flagged or (orig < today and not completion)

        entry = {
            "name": f.get("name"),
            "investment_cr": (f.get("investment") or {}).get("total_inr"),
            "original_expected_completion": dates.get("original_expected_completion"),
            "revised_completion": dates.get("date_completion"),
            "status": status,
            "flagged": flagged,
        }
        (delayed if is_delayed else on_track).append(entry)

    lines = ["Delayed:"]
    if delayed:
        for e in delayed:
            note = "formally flagged delayed" if e["flagged"] else "past original target, not formally flagged"
            revised = f", revised target {e['revised_completion']}" if e["revised_completion"] else ""
            lines.append(
                f"  - {e['name']} (₹{e['investment_cr']}cr, status: {e['status']}) — "
                f"original target {e['original_expected_completion']}{revised} — {note}"
            )
    else:
        lines.append("  (none)")

    lines.append("On track:")
    if on_track:
        for e in on_track:
            lines.append(
                f"  - {e['name']} (₹{e['investment_cr']}cr, status: {e['status']}) — "
                f"targeting {e['original_expected_completion']}"
            )
    else:
        lines.append("  (none)")

    return "\n".join(lines)


def recent_facility_items(facilities: list[dict], cutoff: date) -> str:
    lines = []
    for f in facilities:
        for m in f.get("milestones") or []:
            d = parse_date(m.get("date"))
            if d and d >= cutoff:
                lines.append(f"- [{f.get('name')}] {m.get('date')}: {m.get('event')}")
    return "\n".join(lines) if lines else "(no facility milestones in this window)"


def recent_design_items(design_firms: list[dict], cutoff: date) -> str:
    lines = []
    for firm in design_firms:
        for s in firm.get("sources") or []:
            d = parse_date(s.get("date"))
            if d and d >= cutoff:
                product = (firm.get("dli") or {}).get("product")
                extra = f" — product: {product}" if product else ""
                lines.append(f"- [{firm.get('name')}] {s.get('date')}: {s.get('title')}{extra}")
    return "\n".join(lines) if lines else "(no design-firm source updates in this window)"


def generate_draft(facilities_yaml: dict, design_yaml: dict, today: date) -> tuple[str, str]:
    facilities = facilities_yaml.get("facilities", [])
    design_firms = design_yaml.get("design_firms", [])
    cutoff = today - timedelta(days=LOOKBACK_DAYS)

    timeline_check = compute_timeline_check(facilities, today)
    facility_recent = recent_facility_items(facilities, cutoff)
    design_recent = recent_design_items(design_firms, cutoff)

    month_year = today.strftime("%B %Y")
    prompt = SYNTHESIS_PROMPT.format(
        lookback=LOOKBACK_DAYS,
        facility_recent=facility_recent,
        design_recent=design_recent,
        timeline_check=timeline_check,
        month_year=month_year,
    )

    print(f"  Sending to Claude for synthesis (~{len(prompt.split()):,} words)...")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    text_blocks = [b.text for b in response.content if hasattr(b, "text") and b.text]
    draft = text_blocks[-1] if text_blocks else "No draft generated."

    subject = f"[India Semi Watch] Draft for {month_year} — edit and post"
    return subject, draft


def main():
    try:
        facilities_yaml = load_yaml("data/facilities.yml")
        design_yaml = load_yaml("data/design.yml")
    except FileNotFoundError as e:
        print(f"ERROR: {e}. Run from repo root.", file=sys.stderr)
        sys.exit(1)

    today = date.today()
    print(f"Generating India Semi Watch draft for {today.strftime('%B %Y')}...")
    subject, draft = generate_draft(facilities_yaml, design_yaml, today)

    os.makedirs("data", exist_ok=True)

    # Plain text file: subject on line 1 (workflow extracts it for email header)
    with open("data/india-semi-watch.txt", "w") as f:
        f.write(subject + "\n")

    # HTML file: full styled email body (reuses weekly_digest's template)
    with open("data/india-semi-watch.html", "w") as f:
        f.write(to_html(subject, draft))

    print(f"Done. Written to data/india-semi-watch.html ({len(draft):,} chars)")


if __name__ == "__main__":
    main()
