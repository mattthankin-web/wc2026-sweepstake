"""
generate_commentary.py
Calls Claude API to generate fresh sweepstake commentary and writes it to data/data.json.
Runs daily at 2pm AEST (04:00 UTC) via GitHub Actions.
"""

import os
import json
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
CLAUDE_API_KEY  = os.environ["ANTHROPIC_API_KEY"]   # set in GitHub secrets
DATA_FILE       = Path(__file__).parent.parent / "data" / "data.json"
AEST            = timezone(timedelta(hours=10))

# Rotation: we cover 3 different participants each edition, cycling through all 11
# Never repeat the same 3 two editions in a row
ALL_PARTICIPANTS = [
    "Kenna", "Cronan", "Silk", "Same", "Galbraith",
    "Morris", "P Rankin", "T Rankin", "Hankin", "Varcoe", "Crowle"
]

# Standing instructions per participant (personality/angle notes for Claude)
PARTICIPANT_NOTES = {
    "Galbraith": (
        "Galbraith supports Melbourne Football Club (AFL) who lost to Adelaide Crows recently, "
        "collapsing despite leading at every quarter break. Riley Thilthorpe (key forward, NOT ruckman) "
        "took a mark in the forward pocket and kicked the go-ahead goal, undoing Max Gawn's dominant "
        "hitout count. Weave in subtle AFL comparisons where they fit — compare underperforming "
        "World Cup teams to Melbourne's inability to close out games, or dominant stats that count "
        "for nothing. Keep it dry and subtle, not heavy-handed."
    ),
    "Cronan":   "Cronan is the overall Win% leader. Commentary should acknowledge the lead but note the pressure.",
    "Kenna":    "Kenna has 8 teams — the largest portfolio. Spain is the only real asset; the other 7 are passengers.",
    "Silk":     "Silk has England and USA. Both strong. Algeria and Qatar are dead weight.",
    "Same":     "Same has Portugal (Ronaldo) and Colombia. Strong pair but Portugal disappointing so far.",
    "Morris":   "Morris is unbeaten across 8 games but has 5 draws. Statistically solid, momentum lacking.",
    "P Rankin": "P Rankin's Germany is strong. Sweden, Czech Republic and Iraq are varying degrees of hopeless.",
    "T Rankin": "T Rankin's Netherlands just demolished Sweden 5-1. Croatia are out. Ghana alive.",
    "Hankin":   "Hankin has the most on-pitch points (13) despite low win probability (4.54%). Saudi Arabia eliminated.",
    "Varcoe":   "Varcoe is unbeaten across all 7 games (Japan, Switzerland, DR Congo, Canada). Quiet overachiever.",
    "Crowle":   "Crowle has 0 wins from 7 games. Belgium are 2 draws. Ecuador, Bosnia, Uzbekistan all struggling.",
}

def pick_participants(data):
    """
    Pick 3 participants to cover this edition.
    Avoids repeating participants from the last edition.
    Cycles through all 11 over time.
    """
    last_covered = data.get("meta", {}).get("last_commentary_participants", [])
    edition = data.get("meta", {}).get("edition", 1)

    # Rotate through groups of 3-4, never repeating last batch
    available = [p for p in ALL_PARTICIPANTS if p not in last_covered]
    if len(available) < 3:
        available = ALL_PARTICIPANTS.copy()

    # Pick based on edition number for consistent rotation
    start = (edition * 3) % len(available)
    picks = []
    for i in range(3):
        picks.append(available[(start + i) % len(available)])

    return picks

def build_prompt(data, participants):
    """Build the Claude prompt with current standings and results."""
    standings = data.get("standings", [])
    results = data.get("recent_results", [])
    p_map = data.get("participants", {})

    # Format standings summary
    standings_text = "CURRENT STANDINGS (ranked by Win%):\n"
    for s in standings:
        teams = p_map.get(s["name"], {}).get("teams", [])
        standings_text += (
            f"  {s['rank']}. {s['name']}: {s['win_pct']:.2f}% | "
            f"Pts {s['pts']} | W{s['w']}-D{s['d']}-L{s['l']} | GD {s['gd']:+d} | "
            f"Teams: {', '.join(teams)}\n"
        )

    # Format recent results
    results_text = "RESULTS SINCE LAST EDITION:\n"
    for r in results[:8]:
        results_text += (
            f"  {r['date']} Grp {r['group']}: {r['home']} ({r['home_owner']}) "
            f"{r['home_score']}–{r['away_score']} "
            f"{r['away']} ({r['away_owner']})\n"
        )

    # Format participant-specific context
    participant_sections = ""
    for p in participants:
        notes = PARTICIPANT_NOTES.get(p, "")
        p_data = p_map.get(p, {})
        teams = p_data.get("teams", [])
        standing = next((s for s in standings if s["name"] == p), {})
        participant_sections += (
            f"\n{p.upper()}:\n"
            f"  Teams: {', '.join(teams)}\n"
            f"  Standing: Rank {standing.get('rank','?')} | {standing.get('win_pct',0):.2f}% | "
            f"Pts {standing.get('pts','?')} | W{standing.get('w',0)}-D{standing.get('d',0)}-L{standing.get('l',0)}\n"
            f"  Notes: {notes}\n"
        )

    now_aest = datetime.now(AEST).strftime("%-d %B %Y")

    prompt = f"""You are the senior analyst for the WC2026 Sweepstake Intelligence Report — a private sweepstake among 11 friends following the 2026 FIFA World Cup. The tone is dry, sharp, consulting-paper seriousness with wry humour. Think The Economist covering a pub sweepstake.

TODAY'S DATE: {now_aest}
THIS EDITION COVERS: {', '.join(participants)}

{standings_text}

{results_text}

PARTICIPANT DETAILS FOR THIS EDITION:
{participant_sections}

SWEEPSTAKE RULES: Winner takes all — only the participant whose team wins the World Cup collects. Win% = Kalshi-implied combined tournament win probability across a participant's surviving teams.

TASK: Write analytical commentary for each of the 3 participants listed. For each, write:
- A sharp, specific headline (e.g. "Kenna: Spain Remembered Who They Are")
- 1-2 paragraphs of commentary (roughly the same length as each other — around 80-120 words each)
- Reference specific results, scorelines, and sweepstake implications
- Where notes mention an AFL angle (Galbraith/Melbourne Demons), weave it in subtly — don't overdo it
- Avoid generic observations. Every sentence should be specific to THIS participant's situation RIGHT NOW.
- Maintain consistent dry tone throughout — no exclamation marks, no cheerleading

Return ONLY valid JSON in this exact format, no preamble, no markdown:
[
  {{
    "participant": "Name",
    "color": "#hexcolor",
    "title": "Name: Sharp Headline Here",
    "body": "Paragraph one.\\n\\nParagraph two (if needed)."
  }},
  ...
]

Hex colors: Kenna=#EA580C, Cronan=#1D4ED8, Silk=#BE185D, Same=#15803D, Galbraith=#7C3AED, Morris=#0891B2, P Rankin=#C2410C, T Rankin=#4338CA, Hankin=#166534, Varcoe=#92400E, Crowle=#0369A1"""

    return prompt

def call_claude(prompt):
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
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}]
        },
        timeout=60
    )
    response.raise_for_status()
    data = response.json()
    text = data["content"][0]["text"].strip()
    # Strip any accidental markdown fences
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())

def main():
    print("Generating commentary...")

    with open(DATA_FILE) as f:
        data = json.load(f)

    participants = pick_participants(data)
    print(f"  Covering: {', '.join(participants)}")

    prompt = build_prompt(data, participants)
    commentary = call_claude(prompt)

    print(f"  Generated {len(commentary)} commentary blocks")

    # Update data
    data["commentary"] = commentary
    data["meta"]["last_commentary_participants"] = participants
    data["meta"]["last_commentary_generated"] = datetime.now(timezone.utc).isoformat()
    data["meta"]["edition"] = data["meta"].get("edition", 1) + 1

    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"  Commentary written to {DATA_FILE}")
    for c in commentary:
        print(f"    → {c['title']}")

if __name__ == "__main__":
    main()
