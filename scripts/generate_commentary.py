"""
generate_commentary.py
Calls Claude API to generate fresh sweepstake commentary and writes it to data/data.json.
Runs daily at 2pm AEST (04:00 UTC) via GitHub Actions.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW TO CUSTOMISE COMMENTARY GUIDANCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Edit the PARTICIPANT_NOTES dictionary below.
Each entry is a plain-English instruction to Claude about how to
write that participant's commentary — portfolio situation,
any personality angles, things to emphasise or avoid.

Changes take effect at the next 2pm AEST run, or trigger
Generate Commentary manually via GitHub Actions > Run workflow.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import json
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
CLAUDE_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
DATA_FILE       = Path(__file__).parent.parent / "data" / "data.json"
AEST            = timezone(timedelta(hours=10))

ALL_PARTICIPANTS = [
    "Kenna", "Cronan", "Silk", "Same", "Galbraith",
    "Morris", "P Rankin", "T Rankin", "Hankin", "Varcoe", "Crowle"
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PARTICIPANT NOTES — edit these to guide commentary tone/angle
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PARTICIPANT_NOTES = {
    "Kenna":    "Kenna has 8 teams — the largest portfolio. Spain is the only meaningful asset. The other 7 are passengers at varying stages of elimination.",
    "Cronan":   "Cronan leads on Win% with France as the primary asset. Acknowledge the lead but note it is essentially a one-team portfolio.",
    "Silk":     "Silk has England and USA as the two live assets. Algeria and Qatar are dead weight. Genuinely competitive if both main teams progress deep.",
    "Same":     "Same has Portugal and Colombia as the two serious assets. Portugal has been disappointing. Colombia quietly performing well.",
    "Galbraith":"Galbraith has Argentina as the standout asset plus Morocco who won their group. Turkey and South Africa are eliminated. Focus on Argentina and Morocco's knockout prospects.",
    "Morris":   "Morris is unbeaten across multiple games but has too many draws. Brazil is the primary asset. Uruguay has been frustrating. Scotland and Iran are fringe contributors.",
    "P Rankin": "P Rankin's Germany is the flagship and performing well. Sweden, Czech Republic and Iraq are supporting cast at varying degrees of relevance.",
    "T Rankin": "T Rankin's Netherlands are one of the more dangerous sides in the bracket. Croatia are out. Ghana the wildcard. Focus on Netherlands' knockout potential.",
    "Hankin":   "Hankin leads the field on raw on-pitch points despite low Win%. Norway, Mexico and Ivory Coast all performing above their title odds. Saudi Arabia eliminated.",
    "Varcoe":   "Varcoe has gone unbeaten across all games — Japan, Switzerland, Canada and DR Congo all contributing. The quiet overachiever of the sweepstake.",
    "Crowle":   "Crowle has zero wins across all games played. Belgium drawing everything. Ecuador, Bosnia and Uzbekistan struggling. The portfolio needs a result urgently.",
}


def pick_participants(data):
    """Pick 3 participants, avoiding repeating the last edition's batch."""
    last_covered = data.get("meta", {}).get("last_commentary_participants", [])
    edition = data.get("meta", {}).get("edition", 1)
    available = [p for p in ALL_PARTICIPANTS if p not in last_covered]
    if len(available) < 3:
        available = ALL_PARTICIPANTS.copy()
    start = (edition * 3) % len(available)
    return [available[(start + i) % len(available)] for i in range(3)]


def build_exec_summary_prompt(data):
    """Prompt for the executive summary — overview of the whole window."""
    standings = data.get("standings", [])
    results   = data.get("recent_results", [])
    upcoming  = data.get("upcoming_fixtures", [])

    standings_text = "CURRENT STANDINGS (top 5 by Win%):\n"
    for s in standings[:5]:
        standings_text += (
            f"  {s['rank']}. {s['name']}: {s['win_pct']:.2f}% | "
            f"Pts {s['pts']} | W{s['w']}-D{s['d']}-L{s['l']}\n"
        )

    results_text = "RECENT RESULTS:\n"
    for r in results[:6]:
        results_text += (
            f"  {r['date']} Grp {r.get('group','?')}: "
            f"{r['home']} ({r['home_owner']}) {r['home_score']}–{r['away_score']} "
            f"{r['away']} ({r['away_owner']})\n"
        )

    upcoming_text = "UPCOMING KEY FIXTURES:\n"
    for f in upcoming[:4]:
        upcoming_text += (
            f"  {f['aest_time']} Grp {f.get('group','?')}: "
            f"{f['home']} ({f['home_owner']}) vs {f['away']} ({f['away_owner']})\n"
        )

    now_aest = datetime.now(AEST).strftime("%-d %B %Y")

    return f"""You are the senior analyst for the WC2026 Sweepstake Intelligence Report — a private sweepstake among 11 friends. Tone: dry, sharp, The Economist covering a pub sweepstake. No exclamation marks.

TODAY: {now_aest}

{standings_text}
{results_text}
{upcoming_text}

TASK: Write an executive summary for this edition.

- pull_quote: A single sharp one-liner capturing the defining moment or irony of this window. Max 20 words.
- paragraph_1: (~70 words) The most significant results and storylines — specific scorelines, who gained, who lost ground.
- paragraph_2: (~70 words) Forward look — key fixtures in the next 48 hours, what's at stake for specific participants.

Dry tone. Reference participant names directly. No cheerleading.

Return ONLY a JSON object, no preamble, no markdown:
{{
  "pull_quote": "...",
  "paragraph_1": "...",
  "paragraph_2": "..."
}}"""


def build_commentary_prompt(data, participants):
    """Prompt for participant-specific commentary boxes."""
    standings = data.get("standings", [])
    results   = data.get("recent_results", [])
    p_map     = data.get("participants", {})

    standings_text = "CURRENT STANDINGS (ranked by Win%):\n"
    for s in standings:
        teams = p_map.get(s["name"], {}).get("teams", [])
        standings_text += (
            f"  {s['rank']}. {s['name']}: {s['win_pct']:.2f}% | "
            f"Pts {s['pts']} | W{s['w']}-D{s['d']}-L{s['l']} | GD {s['gd']:+d} | "
            f"Teams: {', '.join(teams)}\n"
        )

    results_text = "RESULTS SINCE LAST EDITION:\n"
    for r in results[:8]:
        results_text += (
            f"  {r['date']} Grp {r.get('group','?')}: "
            f"{r['home']} ({r['home_owner']}) {r['home_score']}–{r['away_score']} "
            f"{r['away']} ({r['away_owner']})\n"
        )

    participant_sections = ""
    for p in participants:
        notes   = PARTICIPANT_NOTES.get(p, "")
        teams   = p_map.get(p, {}).get("teams", [])
        standing = next((s for s in standings if s["name"] == p), {})
        participant_sections += (
            f"\n{p.upper()}:\n"
            f"  Teams: {', '.join(teams)}\n"
            f"  Standing: Rank {standing.get('rank','?')} | {standing.get('win_pct',0):.2f}% | "
            f"Pts {standing.get('pts','?')} | W{standing.get('w',0)}-D{standing.get('d',0)}-L{standing.get('l',0)}\n"
            f"  Guidance: {notes}\n"
        )

    now_aest = datetime.now(AEST).strftime("%-d %B %Y")

    return f"""You are the senior analyst for the WC2026 Sweepstake Intelligence Report — a private sweepstake among 11 friends. Tone: dry, sharp, wry humour. Think The Economist covering a pub sweepstake. No exclamation marks.

TODAY: {now_aest}
COVERING: {', '.join(participants)}

{standings_text}
{results_text}

PARTICIPANT DETAILS:
{participant_sections}

RULES: Winner takes all. Win% = Kalshi-implied combined win probability across surviving teams.

TASK: Write commentary for each of the 3 participants:
- Sharp specific headline
- 1-2 paragraphs (~80-120 words each, similar length)
- Specific results and sweepstake implications
- Follow the Guidance note for each participant
- No generic observations

Return ONLY valid JSON, no preamble, no markdown:
[
  {{
    "participant": "Name",
    "color": "#hexcolor",
    "title": "Name: Sharp Headline Here",
    "body": "Paragraph one.\\n\\nParagraph two (if needed)."
  }}
]

Colors: Kenna=#EA580C, Cronan=#1D4ED8, Silk=#BE185D, Same=#15803D, Galbraith=#7C3AED, Morris=#0891B2, P Rankin=#C2410C, T Rankin=#4338CA, Hankin=#166534, Varcoe=#92400E, Crowle=#0369A1"""


def call_claude(prompt, max_tokens=2000):
    """Call the Anthropic Claude API."""
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]
        },
        timeout=60
    )
    response.raise_for_status()
    data = response.json()
    text = data["content"][0]["text"].strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def main():
    print("Generating commentary...")

    with open(DATA_FILE) as f:
        data = json.load(f)

    # 1. Executive summary
    print("  Generating executive summary...")
    exec_summary = call_claude(build_exec_summary_prompt(data), max_tokens=600)
    print(f"  Quote: {exec_summary.get('pull_quote','')[:60]}...")

    # 2. Participant commentary
    participants = pick_participants(data)
    print(f"  Covering: {', '.join(participants)}")
    commentary = call_claude(build_commentary_prompt(data, participants), max_tokens=2000)
    print(f"  Generated {len(commentary)} blocks")

    # 3. Write back to data.json
    data["exec_summary"] = exec_summary
    data["commentary"]   = commentary
    data["meta"]["last_commentary_participants"] = participants
    data["meta"]["last_commentary_generated"]    = datetime.now(timezone.utc).isoformat()
    data["meta"]["edition"] = data["meta"].get("edition", 1) + 1

    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"  Done. Written to {DATA_FILE}")
    for c in commentary:
        print(f"    → {c['title']}")


if __name__ == "__main__":
    main()
