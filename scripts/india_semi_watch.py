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
You are drafting the "What's New" half of "India Semi Watch," a section in
Siliconpolitik — the semiconductor-geopolitics newsletter within
Technopolitik (hightechir.substack.com), written by Pranay Kotasthane at
the Takshashila Institution. This covers India's semiconductor
manufacturing AND chip-design ecosystem, drawing on the live tracker at
https://fabs.pranaykotas.com.

The timeline check (delayed vs on-track facilities) is handled separately
by code, not you — don't write it, don't mention it, just cover what's new.

## Recent facility milestones (last {lookback} days)

{facility_recent}

## Recent design-firm developments (last {lookback} days)

{design_recent}

## Your task

Write one or two items on what's new, drawn ONLY from the data above — real
product ships, construction milestones, DLI progress, new approvals. If
nothing genuinely new happened this window, say so plainly in one sentence
rather than inventing content. Up to ~300 words total.

## Style — this must read like Pranay wrote it himself, not like an AI summary

- Open with the fact itself, not a scene-setting sentence. No "Two items
  moved the needle this month" or "Against a backdrop of X" or any variant
  — start with what happened.
- No stock phrases: "moved the needle," "doubles down," "signals that,"
  "represents a," "stands as," "serves as a testament," "not just X, it's
  Y," "plays a crucial role." If a sentence would work as a pull-quote,
  rewrite it plainer.
- Have an actual opinion or reaction where warranted, stated directly, not
  hedged ("this matters because," not "this could potentially suggest").
- Vary sentence length. Don't write three same-length sentences in a row.
- Use plain markdown: a paragraph per item, no heading (the section heading
  is added separately), no bullet points unless genuinely listing more
  than two things.
- Do not invent sources, figures, or dates beyond what's given above.
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


def compute_timeline_check(facilities: list[dict], today: date) -> tuple[list[dict], list[dict]]:
    """Pure date logic — no LLM. Delayed vs on-track, per the plan's rule:
    Delayed  = delay_confirmed True, OR original_expected_completion is in
               the past with status not Operational/Cancelled and no
               date_completion set.
    On track = active status with original_expected_completion in the
               future, not delayed.

    Returns (delayed, on_track) lists of dicts — rendering to markdown is a
    separate step, so formatting never touches the LLM.
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
            "id": f.get("id"),
            "name": f.get("name"),
            "investment_cr": (f.get("investment") or {}).get("total_inr"),
            "original_expected_completion": dates.get("original_expected_completion"),
            "revised_completion": dates.get("date_completion"),
            "status": status,
            "flagged": flagged,
        }
        (delayed if is_delayed else on_track).append(entry)

    return delayed, on_track


def render_timeline_check_markdown(delayed: list[dict], on_track: list[dict]) -> str:
    """Renders the timeline check as plain markdown — a blank line before
    each list and one bullet per line, so it can never collapse into a
    single run-on paragraph regardless of what the LLM does elsewhere in
    the email."""
    lines = ["### Timeline check", ""]

    lines.append("**Delayed:**")
    lines.append("")
    if delayed:
        for e in delayed:
            note = "formally flagged delayed" if e["flagged"] else "past original target, not formally flagged"
            revised = f", revised target {e['revised_completion']}" if e["revised_completion"] else ""
            lines.append(
                f"- **{e['name']}** (₹{e['investment_cr']}cr, {e['status']}) — "
                f"original target {e['original_expected_completion']}{revised} — {note}"
            )
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("**On track:**")
    lines.append("")
    if on_track:
        for e in on_track:
            lines.append(
                f"- **{e['name']}** (₹{e['investment_cr']}cr, {e['status']}) — "
                f"targeting {e['original_expected_completion']}"
            )
    else:
        lines.append("- (none)")

    return "\n".join(lines)


def render_image_suggestions(facility_names: list[str], has_design_items: bool) -> str:
    """Static, deterministic image/screenshot guidance — not LLM-generated,
    so it's always present and always the same reliable advice."""
    lines = ["### Images to include", ""]
    lines.append(
        "- **Map & Overview** (fabs.pranaykotas.com) — screenshot the leaflet "
        "map zoomed to show marker clusters; strongest lead image."
    )
    for name in facility_names:
        lines.append(
            f"- **{name}** — crop just its card/status badge from its facility page "
            f"if it's the focus of a \"what's new\" item."
        )
    if has_design_items:
        lines.append(
            "- **Chip Design page** (fabs.pranaykotas.com/design.html) — map or "
            "table view, for the design-firm item(s)."
        )
    lines.append(
        "- Take screenshots at 1200px+ width, crop tight (single card/region, "
        "not a full page), and caption with \"via fabs.pranaykotas.com\"."
    )
    return "\n".join(lines)


def recent_facility_items(facilities: list[dict], cutoff: date) -> tuple[str, list[str]]:
    lines = []
    names = []
    for f in facilities:
        for m in f.get("milestones") or []:
            d = parse_date(m.get("date"))
            if d and d >= cutoff:
                lines.append(f"- [{f.get('name')}] {m.get('date')}: {m.get('event')}")
                if f.get("name") not in names:
                    names.append(f.get("name"))
    text = "\n".join(lines) if lines else "(no facility milestones in this window)"
    return text, names


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

    delayed, on_track = compute_timeline_check(facilities, today)
    facility_recent, recent_names = recent_facility_items(facilities, cutoff)
    design_recent = recent_design_items(design_firms, cutoff)
    has_design_items = "no design-firm source updates" not in design_recent

    month_year = today.strftime("%B %Y")
    prompt = SYNTHESIS_PROMPT.format(
        lookback=LOOKBACK_DAYS,
        facility_recent=facility_recent,
        design_recent=design_recent,
        month_year=month_year,
    )

    print(f"  Sending to Claude for synthesis (~{len(prompt.split()):,} words)...")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1536,
        messages=[{"role": "user", "content": prompt}],
    )
    text_blocks = [b.text for b in response.content if hasattr(b, "text") and b.text]
    whats_new = text_blocks[-1] if text_blocks else "(no draft generated)"

    # Assemble deterministically: only the "what's new" prose above came
    # from the LLM. The timeline check and image guidance are rendered in
    # code so they can never be reworded, mis-formatted, or dropped.
    draft = "\n\n".join([
        f"### India Semi Watch — {month_year}",
        "",
        "**What's new**",
        "",
        whats_new.strip(),
        "",
        render_timeline_check_markdown(delayed, on_track),
        "",
        render_image_suggestions(recent_names, has_design_items),
        "",
        (
            "Full facility detail at [fabs.pranaykotas.com](https://fabs.pranaykotas.com); "
            "design-firm tracking at "
            "[fabs.pranaykotas.com/design.html](https://fabs.pranaykotas.com/design.html)."
        ),
    ])

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
