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
    "Kenna", "Cronan", "Silk", "Same", "Poncho Man",
    "Morris", "P Rankin", "T Rankin", "Hankin", "Varcoe", "Crowle"
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PARTICIPANT NOTES — edit these to guide commentary tone/angle
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PARTICIPANT_NOTES = {
    # KNOCKOUT STAGE — only discuss surviving teams
    # P Rankin and T Rankin are eliminated — brief mention only
    "Kenna":    "Write ONLY about Spain ($4.7). Semi-final vs France. Legitimate contenders. Kenna vs Cronan in the semis. Nothing else.",
    "Cronan":   "Write ONLY about France ($2.6). Semi-final vs Spain. Tournament favourites. Cronan's shot at the pot. Nothing else.",
    "Silk":     "Write ONLY about England ($4.5). Semi-final opponent TBD. Still in it. What England need to do. Nothing else.",
    "Same":     "ELIMINATED. All of Same's teams are out. One sentence only. Do not mention Portugal, Colombia, Paraguay or Cape Verde.",
    "Poncho Man":"Write ONLY about Argentina ($5.6). Quarter-final winner. Semi-final ahead. World champions. Poncho Man's path to the pot. Nothing else.",
    "Morris":   "ELIMINATED. Brazil are out. One sentence acknowledging Morris is done. Nothing more — do not discuss Brazil or any other team.",
    "P Rankin": "ELIMINATED. One sentence only. Do not mention Germany or Sweden.",
    "T Rankin": "ELIMINATED. One sentence only. Do not mention Netherlands, Ghana or any other team.",
    "Hankin":   "ELIMINATED. One sentence: Hankin is out. Nothing more.",
    "Varcoe":   "Switzerland ($90) and Canada ($470) both survived the Round of 32. Switzerland are a credible quarter-final threat. Canada are the long shot. Any path to the final wins the pot.",
    "Crowle":   "Belgium ($75) is Crowle's sole survivor after Ecuador, Bosnia and Uzbekistan all went out. One team, one last shot. Discuss Belgium's next opponent and realistic title chances.",
}


def pick_participants(data):
    """Pick participants for individual commentary — ALIVE participants only.
    Eliminated participants are covered in the exec summary only, not here."""
    last_covered = data.get("meta", {}).get("last_commentary_participants", [])
    edition = data.get("meta", {}).get("edition", 1)

    # Only consider participants with at least one alive team
    teams_in_odds = {o["team"] for o in data.get("odds", [])}
    p_map = data.get("participants", {})
    alive_participants = [
        name for name in ALL_PARTICIPANTS
        if any(t in teams_in_odds for t in p_map.get(name, {}).get("teams", []))
    ]

    if not alive_participants:
        return []

    # Rotate through alive participants, avoiding repeats from last edition
    available = [p for p in alive_participants if p not in last_covered]
    if not available:
        available = alive_participants.copy()

    # Pick up to 3, or however many alive participants there are
    count = min(3, len(alive_participants))
    start = (edition * 3) % len(available)
    return [available[(start + i) % len(available)] for i in range(min(count, len(available)))]


def build_exec_summary_prompt(data):
    """Prompt for the executive summary — overview of the whole window."""
    results   = data.get("recent_results", [])
    upcoming  = data.get("upcoming_fixtures", [])
    p_map     = data.get("participants", {})

    # Build definitive alive/eliminated list from odds table
    teams_in_odds = {o["team"] for o in data.get("odds", [])}
    alive_lines = []
    for name, info in p_map.items():
        alive = [t for t in info.get("teams", []) if t in teams_in_odds]
        if alive:
            odds_str = ", ".join(
                f"{t} @ {next((o['now'] for o in data.get('odds',[]) if o['team']==t), '?')}"
                for t in alive
            )
            alive_lines.append(f"  {name}: STILL IN — {odds_str}")
        else:
            alive_lines.append(f"  {name}: ELIMINATED")
    alive_text = "PARTICIPANT STATUS (definitive — use this to determine who is in/out):\n"
    alive_text += "\n".join(alive_lines) + "\n"

    # Also list recently eliminated teams with their owners for context
    all_teams_flat = {}
    for name, info in p_map.items():
        for t in info.get("teams", []):
            all_teams_flat[t] = name
    recently_eliminated = []
    for stage in data.get("knockout", []):
        for m in stage.get("matches", []):
            if m.get("status") == "FINISHED" and m.get("winner"):
                loser = m["away"] if m["winner"] == "home" else m["home"]
                owner = all_teams_flat.get(loser, "?")
                winner = m["home"] if m["winner"] == "home" else m["away"]
                winner_owner = all_teams_flat.get(winner, "?")
                recently_eliminated.append(
                    f"  {loser} [{owner}] eliminated by {winner} [{winner_owner}] in {stage['label']}"
                )
    if recently_eliminated:
        alive_text += "\nRECENTLY ELIMINATED TEAMS (with their owners — use this when discussing results):\n"
        alive_text += "\n".join(recently_eliminated[-12:]) + "\n"

    # Separate finished, live and upcoming matches clearly
    finished = [r for r in results if r.get('status') == 'FINISHED']
    live = [r for r in results if r.get('status') in ('IN_PLAY','LIVE','PAUSED')]

    results_text = "COMPLETED RESULTS (these matches are finished — you may discuss outcomes):\n"
    if finished:
        for r in finished[:8]:
            home_owner = r.get('home_owner','?') or '?'
            away_owner = r.get('away_owner','?') or '?'
            results_text += (
                f"  FINISHED: {r['home']} [{home_owner}] {r['home_score']}–{r['away_score']} "
                f"{r['away']} [{away_owner}]\n"
            )
    else:
        results_text += "  No completed results since last edition.\n"

    if live:
        results_text += "\nLIVE NOW (in progress — do NOT write as if these are finished):\n"
        for r in live:
            home_owner = r.get('home_owner','?') or '?'
            away_owner = r.get('away_owner','?') or '?'
            results_text += (
                f"  LIVE: {r['home']} [{home_owner}] {r['home_score']}–{r['away_score']} "
                f"{r['away']} [{away_owner}] (match in progress)\n"
            )

    upcoming_text = "UPCOMING FIXTURES (not yet played — write about these as future events only):\n"
    for f in upcoming[:5]:
        home_owner = f.get('home_owner','?') or '?'
        away_owner = f.get('away_owner','?') or '?'
        upcoming_text += (
            f"  {f['aest_time']}: "
            f"{f['home']} [owned by {home_owner}] vs {f['away']} [owned by {away_owner}]\n"
        )

    now_aest = datetime.now(AEST).strftime("%-d %B %Y")

    return f"""You are the senior analyst for the WC2026 Sweepstake Intelligence Report — a private sweepstake among 11 friends. Tone: dry, sharp, The Economist covering a pub sweepstake. No exclamation marks.

TODAY: {now_aest}

{alive_text}
{results_text}
{upcoming_text}

CONTEXT: We are in the KNOCKOUT ROUNDS. Winner takes all. Only surviving teams matter.

TASK: Write an executive summary covering the entire sweepstake picture.
This is the ONLY place where eliminated participants are mentioned.

CRITICAL TENSE RULE: Only write about COMPLETED RESULTS as finished. LIVE matches are in progress — write about them in present tense. UPCOMING matches have not happened — write about them as future events only. Never state a result that hasn't happened.

CRITICAL: Use the PARTICIPANT STATUS list below as your source of truth for who is in/out.

- pull_quote: A sharp one-liner about the state of the sweepstake right now. Max 20 words. No exclamation marks.
- paragraph_1: (~80 words) Cover all recent results and their sweepstake impact — who progressed, who was eliminated, any drama. Brief mention of eliminated participants is fine here only. No points totals.
- paragraph_2: (~80 words) Cover ALL surviving participants — their team, current odds, next opponent, and realistic path to the pot. Name every surviving participant explicitly. This paragraph should read like a concise state-of-play for the whole remaining field.

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

    # Build alive participants summary for exec prompt
    teams_in_odds_exec = {o["team"] for o in data.get("odds", [])}
    alive_summary = []
    for name, info in p_map.items():
        alive = [t for t in info.get("teams", []) if t in teams_in_odds_exec]
        if alive:
            odds_str = ", ".join(f"{t} @ {next((o['now'] for o in data.get('odds',[]) if o['team']==t), '?')}" for t in alive)
            alive_summary.append(f"{name}: {odds_str}")
        else:
            alive_summary.append(f"{name}: ELIMINATED")
    alive_participants_text = "ALIVE PARTICIPANTS (for reference — do not declare anyone eliminated unless listed as ELIMINATED here):\n"
    alive_participants_text += "\n".join(f"  {s}" for s in alive_summary) + "\n\n"

    results_text = "RESULTS SINCE LAST EDITION (format: Team [Owner] Score Team [Owner]):\n"
    for r in results[:8]:
        results_text += (
            f"  {r['date']} Grp {r.get('group','?')}: "
            f"{r['home']} [owned by {r['home_owner']}] {r['home_score']}–{r['away_score']} "
            f"{r['away']} [owned by {r['away_owner']}]\n"
        )
    results_text += "NOTE: Each team has exactly one owner shown in brackets. Do not confuse team owners.\n"

    # Use odds table as definitive source of alive teams
    # Catches BOTH group-stage AND knockout eliminations
    # If a team has no odds entry, they are out of the tournament
    teams_in_odds = {o["team"] for o in data.get("odds", [])}

    participant_sections = ""
    for p in participants:
        notes     = PARTICIPANT_NOTES.get(p, "")
        all_teams = p_map.get(p, {}).get("teams", [])
        alive     = [t for t in all_teams if t in teams_in_odds]
        is_out    = len(alive) == 0
        standing  = next((s for s in standings if s["name"] == p), {})
        # Get odds for alive teams
        alive_odds = []
        for o in data.get("odds", []):
            if o.get("owner") == p and o.get("team") in alive:
                alive_odds.append(f"{o['team']} @ {o['now']}")

        participant_sections += (
            f"\n{p.upper()}:\n"
            f"  Status: {'ELIMINATED — one sentence only, nothing more' if is_out else 'STILL IN TOURNAMENT'}\n"
            f"  Alive teams: {', '.join(alive) if alive else 'None — eliminated'}\n"
            f"  Current odds: {', '.join(alive_odds) if alive_odds else 'N/A'}\n"
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

CONTEXT: We are in the KNOCKOUT ROUNDS of the 2026 World Cup. Winner takes all.
Only the participant whose team wins the World Cup wins the sweepstake pot.

ABSOLUTE RULE: Each participant has exactly ONE alive team. Name ONLY that team. Do not name any other team for any reason — not historically, not as context, not in passing. Austria, Morocco, Egypt, Switzerland, USA, Norway and all other eliminated teams must not appear.

RULES:
- Write ONLY about the one alive team listed per participant
- Do NOT name any other team the participant owns or owned — zero tolerance
- Eliminated participants do not appear in individual commentary at all
- You may reference how the alive team got here (their knockout results) but name only alive teams and their opponents who are still in the tournament
- Forward focus: next opponent, path to the final, title odds
- No points, no Win%, no table positions
- Write with personality

TASK: For each participant listed — write about their ONE team only:
- Sharp headline
- 1-2 paragraphs (~80-120 words)
- Zero mention of any eliminated team or participant
- Follow the Guidance note exactly

Return ONLY valid JSON, no preamble, no markdown:
[
  {{
    "participant": "Name",
    "color": "#hexcolor",
    "title": "Name: Sharp Headline Here",
    "body": "Paragraph one.\\n\\nParagraph two (if needed)."
  }}
]

Colors: Kenna=#EA580C, Cronan=#1D4ED8, Silk=#BE185D, Same=#15803D, Poncho Man=#7C3AED, Morris=#0891B2, P Rankin=#C2410C, T Rankin=#4338CA, Hankin=#166534, Varcoe=#92400E, Crowle=#0369A1"""


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




# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TRIVIA SCHEDULE GENERATOR
# Runs once per day at 2pm AEST alongside commentary.
# Pre-assigns 5 questions per day for the rest of the
# tournament so everyone gets the same questions regardless
# of when they play. Questions never repeat.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WC_END_DATE = "2026-07-19"  # World Cup final date

ALL_QUESTIONS = [
  {"id":1,"question":"Which country won the first ever FIFA World Cup in 1930?","options":["Brazil","Uruguay","Argentina","Italy"],"correct":1,"explanation":"Uruguay hosted and won the inaugural World Cup in 1930, beating Argentina 4-2 in the final.","category":"history","difficulty":"easy"},
  {"id":2,"question":"Who holds the all-time record for most goals scored in World Cup history?","options":["Ronaldo (Brazil)","Miroslav Klose","Gerd Müller","Lionel Messi"],"correct":1,"explanation":"Miroslav Klose scored 16 goals across four World Cups (2002–2014). Messi equalled that record at WC2026.","category":"records","difficulty":"easy"},
  {"id":3,"question":"At the 2026 World Cup, which player scored a hat-trick to equal the all-time World Cup scoring record?","options":["Kylian Mbappé","Erling Haaland","Lionel Messi","Vinicius Jr."],"correct":2,"explanation":"Messi scored three goals against Algeria to reach 16 World Cup goals, equalling Klose's all-time record.","category":"2026","difficulty":"easy"},
  {"id":4,"question":"How many nations co-hosted the 2026 FIFA World Cup?","options":["1","2","3","4"],"correct":2,"explanation":"The 2026 World Cup was jointly hosted by the USA, Canada and Mexico — the first World Cup hosted by three nations.","category":"2026","difficulty":"easy"},
  {"id":5,"question":"How many teams competed in the expanded 2026 FIFA World Cup?","options":["32","40","48","64"],"correct":2,"explanation":"2026 expanded to 48 teams for the first time, up from the 32-team format used since 1998.","category":"2026","difficulty":"easy"},
  {"id":6,"question":"Which country beat Qatar 6-0 at the 2026 World Cup, with a Jonathan David hat-trick?","options":["USA","Mexico","Canada","France"],"correct":2,"explanation":"Co-host Canada demolished Qatar 6-0 with Jonathan David scoring a hat-trick.","category":"2026","difficulty":"medium"},
  {"id":7,"question":"Brazil has won the most World Cups. How many titles do they have?","options":["4","5","6","3"],"correct":1,"explanation":"Brazil have won five World Cups: 1958, 1962, 1970, 1994 and 2002.","category":"history","difficulty":"easy"},
  {"id":8,"question":"Which team did France beat in the 2018 World Cup final?","options":["Brazil","Germany","Croatia","England"],"correct":2,"explanation":"France beat Croatia 4-2 in the 2018 World Cup final in Moscow.","category":"history","difficulty":"easy"},
  {"id":9,"question":"In the 2022 World Cup final, what was the score after extra time?","options":["2-2","3-3","1-1","4-4"],"correct":1,"explanation":"The 2022 final finished 3-3 after extra time, with Argentina winning 4-2 on penalties.","category":"history","difficulty":"medium"},
  {"id":10,"question":"Which Spanish teenager was one of the most watched players at the 2026 World Cup?","options":["Pedri","Gavi","Lamine Yamal","Ferran Torres"],"correct":2,"explanation":"Lamine Yamal, aged 17, was one of Spain's key players at the 2026 tournament.","category":"2026","difficulty":"easy"},
  {"id":11,"question":"Which team won 2026 World Cup Group C, beating Scotland and drawing with Brazil?","options":["Brazil","Haiti","Morocco","Scotland"],"correct":2,"explanation":"Morocco won Group C with a 1-0 win over Scotland and a draw against Brazil.","category":"2026","difficulty":"medium"},
  {"id":12,"question":"The USA topped their 2026 World Cup group. Which group were they in?","options":["Group A","Group C","Group D","Group B"],"correct":2,"explanation":"The USA were in Group D alongside Paraguay, Australia and Turkey.","category":"2026","difficulty":"medium"},
  {"id":13,"question":"Which country has won back-to-back World Cup titles — the only nation to do so?","options":["Brazil","Italy","Germany","Argentina"],"correct":0,"explanation":"Brazil won back-to-back World Cups in 1958 and 1962.","category":"history","difficulty":"medium"},
  {"id":14,"question":"Who scored the famous 'Hand of God' goal at the 1986 World Cup?","options":["Pelé","Diego Maradona","Ronaldo","Zinedine Zidane"],"correct":1,"explanation":"Diego Maradona scored the 'Hand of God' goal against England in the 1986 quarter-final.","category":"history","difficulty":"easy"},
  {"id":15,"question":"What is the highest score in a single World Cup match?","options":["8-0","9-0","10-1","12-0"],"correct":2,"explanation":"Hungary beat El Salvador 10-1 in the 1982 World Cup.","category":"records","difficulty":"hard"},
  {"id":16,"question":"Which 2026 World Cup group did France and Norway both play in?","options":["Group H","Group I","Group J","Group K"],"correct":1,"explanation":"France and Norway were both in Group I, along with Senegal and Iraq.","category":"2026","difficulty":"medium"},
  {"id":17,"question":"How many goals did the Netherlands score against Sweden at the 2026 World Cup?","options":["3","4","5","6"],"correct":2,"explanation":"The Netherlands beat Sweden 5-1 in Group F.","category":"2026","difficulty":"medium"},
  {"id":18,"question":"Which World Cup saw VAR used for the first time?","options":["2014 Brazil","2018 Russia","2022 Qatar","2010 South Africa"],"correct":1,"explanation":"VAR was introduced at the 2018 World Cup in Russia.","category":"history","difficulty":"medium"},
  {"id":19,"question":"Who won the Golden Boot at the 2022 World Cup?","options":["Lionel Messi","Kylian Mbappé","Olivier Giroud","Julian Alvarez"],"correct":1,"explanation":"Kylian Mbappé won the Golden Boot at Qatar 2022 with 8 goals.","category":"history","difficulty":"medium"},
  {"id":20,"question":"Who scored the winning penalty for Argentina in the 2022 World Cup final shootout?","options":["Lionel Messi","Leandro Paredes","Gonzalo Montiel","Emiliano Martínez"],"correct":2,"explanation":"Gonzalo Montiel scored the decisive penalty to win Argentina the 2022 World Cup.","category":"history","difficulty":"hard"},
  {"id":21,"question":"Which team knocked out defending champions Germany in the 2018 World Cup group stage?","options":["Nigeria","Senegal","Mexico","South Korea"],"correct":3,"explanation":"South Korea beat Germany 2-0, eliminating the defending champions.","category":"history","difficulty":"medium"},
  {"id":22,"question":"France beat Senegal 3-1 at the 2026 World Cup. Who scored twice in that match?","options":["Antoine Griezmann","Ousmane Dembélé","Kylian Mbappé","Marcus Thuram"],"correct":2,"explanation":"Kylian Mbappé scored twice against Senegal, becoming France's all-time leading scorer.","category":"2026","difficulty":"hard"},
  {"id":23,"question":"What year did Pelé score his first World Cup goal, aged just 17?","options":["1954","1958","1962","1966"],"correct":1,"explanation":"Pelé burst onto the world stage at the 1958 World Cup in Sweden.","category":"history","difficulty":"medium"},
  {"id":24,"question":"Which nation hosted the 2010 FIFA World Cup — the first ever on African soil?","options":["Nigeria","Egypt","South Africa","Morocco"],"correct":2,"explanation":"South Africa hosted the 2010 World Cup, the first tournament on African soil.","category":"history","difficulty":"easy"},
  {"id":25,"question":"Which 2026 World Cup group had Argentina, Austria, Algeria and Jordan?","options":["Group H","Group I","Group J","Group K"],"correct":2,"explanation":"Argentina were in Group J alongside Austria, Algeria and Jordan.","category":"2026","difficulty":"hard"},
  {"id":26,"question":"Which goalkeeper made two penalty saves to help Argentina win the 2022 World Cup final shootout?","options":["Hugo Lloris","Emiliano Martínez","Sergio Romero","Franco Armani"],"correct":1,"explanation":"Emiliano 'Dibu' Martínez made two saves in the 2022 final shootout.","category":"history","difficulty":"medium"},
  {"id":27,"question":"Which iconic stadium hosted the opening match of the 2026 World Cup?","options":["Rose Bowl, Los Angeles","MetLife Stadium, New York","Estadio Azteca, Mexico City","BC Place, Vancouver"],"correct":2,"explanation":"The 2026 World Cup opened at the Estadio Azteca in Mexico City.","category":"2026","difficulty":"medium"},
  {"id":28,"question":"Which team has appeared in the most World Cup finals without ever winning?","options":["Netherlands","Hungary","Czechoslovakia","Sweden"],"correct":0,"explanation":"The Netherlands have appeared in three World Cup finals (1974, 1978, 2010) without winning.","category":"records","difficulty":"hard"},
  {"id":29,"question":"How old was Lamine Yamal when he played at the 2026 World Cup?","options":["16","17","18","19"],"correct":1,"explanation":"Lamine Yamal was 17 years old during the 2026 World Cup.","category":"2026","difficulty":"easy"},
  {"id":30,"question":"Germany beat which host nation 7-1 in the 2014 World Cup semi-final?","options":["Argentina","Brazil","Netherlands","France"],"correct":1,"explanation":"Germany's 7-1 destruction of host Brazil in 2014 — the 'Mineirazo' — is legendary.","category":"history","difficulty":"easy"},
  {"id":31,"question":"Which country won the 2022 FIFA World Cup?","options":["France","Brazil","Argentina","Morocco"],"correct":2,"explanation":"Argentina won their third World Cup in Qatar 2022, with Lionel Messi lifting the trophy.","category":"history","difficulty":"easy"},
  {"id":32,"question":"How many World Cups did Lionel Messi participate in throughout his career?","options":["4","5","6","3"],"correct":1,"explanation":"Messi played in five World Cups: 2006, 2010, 2014, 2018 and 2022.","category":"players","difficulty":"medium"},
  {"id":33,"question":"Which nation made a surprise run to the 2022 World Cup semi-finals — the first African team ever to do so?","options":["Senegal","Cameroon","Morocco","Ghana"],"correct":2,"explanation":"Morocco made history by reaching the 2022 World Cup semi-finals.","category":"history","difficulty":"easy"},
  {"id":34,"question":"Which player won the Golden Ball (best player) at the 2022 World Cup?","options":["Kylian Mbappé","Luka Modric","Lionel Messi","Julian Alvarez"],"correct":2,"explanation":"Lionel Messi won the Golden Ball award at Qatar 2022.","category":"history","difficulty":"easy"},
  {"id":35,"question":"How many times has Germany won the World Cup?","options":["3","4","5","2"],"correct":1,"explanation":"Germany (including West Germany) have won four World Cups: 1954, 1974, 1990 and 2014.","category":"history","difficulty":"easy"},
  {"id":36,"question":"Which country lost the 2010 World Cup final to Spain?","options":["Germany","Brazil","Netherlands","Argentina"],"correct":2,"explanation":"The Netherlands lost 1-0 to Spain in the 2010 final, with Andres Iniesta scoring the winner.","category":"history","difficulty":"easy"},
  {"id":37,"question":"Who scored the winning goal for Spain in the 2010 World Cup final?","options":["David Villa","Xavi","Fernando Torres","Andres Iniesta"],"correct":3,"explanation":"Andres Iniesta scored in extra time to give Spain their first ever World Cup title.","category":"history","difficulty":"medium"},
  {"id":38,"question":"Which goalkeeper famously saved penalties to make Cape Verde's 0-0 draw with Spain at WC2026 possible?","options":["Edvandro","Vozinha","Marchesin","Dibu"],"correct":1,"explanation":"Vozinha, a 40-year-old keeper playing in the Portuguese second division, made extraordinary saves to hold Spain scoreless.","category":"2026","difficulty":"hard"},
  {"id":39,"question":"What did Zinedine Zidane do in the 2006 World Cup final that made global headlines?","options":["Scored with his knee","Was sent off for a headbutt","Missed the decisive penalty","Refused to shake hands"],"correct":1,"explanation":"Zidane was sent off for headbutting Marco Materazzi in extra time of the 2006 final — his last ever professional game.","category":"history","difficulty":"easy"},
  {"id":40,"question":"Which country hosted the 2014 World Cup?","options":["Argentina","Mexico","Brazil","Colombia"],"correct":2,"explanation":"Brazil hosted the 2014 World Cup and was famously beaten 7-1 by Germany in the semi-final.","category":"history","difficulty":"easy"},
  {"id":41,"question":"Which player is known by the nickname 'O Fenômeno' (The Phenomenon)?","options":["Pelé","Ronaldo (Brazilian)","Ronaldinho","Romario"],"correct":1,"explanation":"Ronaldo Nazário — the Brazilian striker — was nicknamed 'O Fenômeno'.","category":"players","difficulty":"medium"},
  {"id":42,"question":"How many goals did Ronaldo (Brazil) score in the 2002 World Cup final against Germany?","options":["1","2","3","0"],"correct":1,"explanation":"Ronaldo scored twice in the 2002 final as Brazil beat Germany 2-0.","category":"history","difficulty":"medium"},
  {"id":43,"question":"Which team did Italy beat in the 1982 World Cup final?","options":["West Germany","Brazil","France","Argentina"],"correct":0,"explanation":"Italy beat West Germany 3-1 in the 1982 final. Paolo Rossi was top scorer with 6 goals.","category":"history","difficulty":"medium"},
  {"id":44,"question":"Which player scored a hat-trick in the 1966 World Cup final for England?","options":["Bobby Moore","Geoff Hurst","Martin Peters","Bobby Charlton"],"correct":1,"explanation":"Geoff Hurst scored a hat-trick in the 1966 final against West Germany — the only hat-trick in a World Cup final.","category":"records","difficulty":"medium"},
  {"id":45,"question":"Which team scored the fastest goal in World Cup history, in just 11 seconds?","options":["Turkey","Mexico","Czech Republic","Spain"],"correct":0,"explanation":"Hakan Şükür scored for Turkey after just 11 seconds against South Korea in the 2002 third-place playoff.","category":"records","difficulty":"hard"},
  {"id":46,"question":"Which player has appeared in the most World Cup finals across their career?","options":["Cafu","Pelé","Franz Beckenbauer","Lothar Matthäus"],"correct":0,"explanation":"Cafu of Brazil appeared in three World Cup finals (1994, 1998, 2002), winning twice.","category":"records","difficulty":"hard"},
  {"id":47,"question":"Just Fontaine holds the record for most goals scored at a single World Cup. How many did he score?","options":["11","13","15","9"],"correct":1,"explanation":"Just Fontaine of France scored 13 goals at the 1958 World Cup — a record that still stands.","category":"records","difficulty":"hard"},
  {"id":48,"question":"Which nation won the World Cup without losing a single game across the entire tournament in 1970?","options":["West Germany","Italy","England","Brazil"],"correct":3,"explanation":"Brazil won the 1970 World Cup winning all six matches — widely regarded as the greatest World Cup team ever.","category":"history","difficulty":"medium"},
  {"id":49,"question":"England won their only World Cup in which year?","options":["1962","1966","1970","1974"],"correct":1,"explanation":"England won their only World Cup in 1966, beating West Germany 4-2 in the final at Wembley.","category":"history","difficulty":"easy"},
  {"id":50,"question":"Which team has never missed a World Cup since they first qualified?","options":["Brazil","Germany","Argentina","France"],"correct":0,"explanation":"Brazil are the only team to have qualified for every single FIFA World Cup since 1930.","category":"records","difficulty":"medium"},
  {"id":51,"question":"How many times has Argentina won the World Cup?","options":["2","3","4","1"],"correct":1,"explanation":"Argentina have won the World Cup three times: 1978, 1986 and 2022.","category":"history","difficulty":"easy"},
  {"id":52,"question":"Which player was voted the best goalkeeper (Golden Glove) at the 2022 World Cup?","options":["Yassine Bounou","Emiliano Martínez","Thibaut Courtois","Dominik Livakovic"],"correct":1,"explanation":"Emiliano Martínez won the Golden Glove at the 2022 World Cup.","category":"history","difficulty":"medium"},
  {"id":53,"question":"Which player is known as 'La Pulga' (The Flea)?","options":["Neymar","Lionel Messi","Luis Suárez","David Silva"],"correct":1,"explanation":"Lionel Messi is nicknamed 'La Pulga' due to his small stature and quick, agile playing style.","category":"players","difficulty":"easy"},
  {"id":54,"question":"Which player scored the most goals at the 2026 World Cup group stage?","options":["Jonathan David","Erling Haaland","Lionel Messi","Kylian Mbappé"],"correct":2,"explanation":"Lionel Messi led the group stage scoring charts with his hat-trick against Algeria plus a goal against Austria.","category":"2026","difficulty":"medium"},
  {"id":55,"question":"Which World Cup was the first to be held outside Europe or the Americas?","options":["1966 England","1994 USA","2002 Japan & South Korea","2010 South Africa"],"correct":2,"explanation":"The 2002 World Cup in Japan and South Korea was the first held in Asia.","category":"history","difficulty":"medium"},
  {"id":56,"question":"Which player scored in the 2022 World Cup semi-final AND the final for Argentina?","options":["Angel Di Maria","Julian Alvarez","Enzo Fernández","Lautaro Martinez"],"correct":1,"explanation":"Julian Alvarez scored twice vs Croatia in the semi-final and once in the final.","category":"history","difficulty":"medium"},
  {"id":57,"question":"Mexico co-hosted the 2026 World Cup. They also hosted the World Cup in which two previous years?","options":["1970 and 1994","1970 and 1986","1986 and 1994","1978 and 1986"],"correct":1,"explanation":"Mexico hosted the World Cup in 1970 and 1986, making 2026 their third time hosting.","category":"history","difficulty":"medium"},
  {"id":58,"question":"Which country qualified for the 2026 World Cup knockouts by topping Group E?","options":["Ecuador","Ivory Coast","Germany","Curaçao"],"correct":2,"explanation":"Germany topped Group E with wins including their famous 7-1 win over Curaçao.","category":"2026","difficulty":"easy"},
  {"id":59,"question":"Which player won the Young Player Award at the 2022 World Cup?","options":["Gavi","Pedri","Enzo Fernández","Eduardo Camavinga"],"correct":2,"explanation":"Enzo Fernández of Argentina won the Young Player Award at Qatar 2022.","category":"history","difficulty":"medium"},
  {"id":60,"question":"How many own goals were scored at the 2022 World Cup in Qatar — a new record?","options":["5","7","9","11"],"correct":2,"explanation":"There were 9 own goals at the 2022 World Cup in Qatar, a new tournament record.","category":"records","difficulty":"hard"},
  {"id":61,"question":"Which player scored the fastest hat-trick in World Cup history?","options":["Laszlo Kiss","Just Fontaine","Sándor Kocsis","Gerd Müller"],"correct":0,"explanation":"Laszlo Kiss of Hungary scored three times in 7 minutes against El Salvador in 1982.","category":"records","difficulty":"hard"},
  {"id":62,"question":"Which Italian player headbutted Zidane in the 2006 World Cup final?","options":["Fabio Cannavaro","Marco Materazzi","Gennaro Gattuso","Alessandro Del Piero"],"correct":1,"explanation":"Marco Materazzi provoked Zinedine Zidane into a headbutt in the 2006 final.","category":"history","difficulty":"medium"},
  {"id":63,"question":"Which team has scored the most goals in a single World Cup tournament?","options":["Brazil (1970)","West Germany (1954)","Hungary (1954)","France (1958)"],"correct":2,"explanation":"Hungary scored 27 goals in just 5 matches at the 1954 World Cup.","category":"records","difficulty":"hard"},
  {"id":64,"question":"Belgium drew both their 2026 World Cup group games. Who did they draw with?","options":["Egypt and France","Iran and Egypt","Iran and New Zealand","Egypt and New Zealand"],"correct":1,"explanation":"Belgium drew 1-1 with Egypt and 0-0 with Iran in their Group G games.","category":"2026","difficulty":"medium"},
  {"id":65,"question":"Which player scored twice for Cody Gakpo's Netherlands in the 5-1 win over Sweden at WC2026?","options":["Memphis Depay","Cody Gakpo","Donyell Malen","Wout Weghorst"],"correct":1,"explanation":"Cody Gakpo scored twice in the Netherlands' 5-1 demolition of Sweden.","category":"2026","difficulty":"medium"},
  {"id":66,"question":"Japan beat Tunisia 4-0 at the 2026 World Cup. Which player scored twice for Japan?","options":["Kaoru Mitoma","Junya Ito","Daichi Kamada","Takumi Nakamura"],"correct":3,"explanation":"Nakamura scored twice as Japan beat Tunisia 4-0 in Group F.","category":"2026","difficulty":"hard"},
  {"id":67,"question":"Scotland beat Haiti 1-0 at the 2026 World Cup. What was significant about this?","options":["It was Scotland's first WC win in 24 years","It was Scotland's first WC win ever","It qualified Scotland for the knockouts","It eliminated Haiti immediately"],"correct":0,"explanation":"Scotland beat Haiti 1-0 — their first World Cup win in 24 years.","category":"2026","difficulty":"medium"},
  {"id":68,"question":"Erling Haaland scored twice for Norway against which team at the 2026 World Cup?","options":["Senegal","France","Iraq","Algeria"],"correct":2,"explanation":"Erling Haaland scored twice for Norway in their group stage win over Iraq.","category":"2026","difficulty":"medium"},
  {"id":69,"question":"Which African nation beat Argentina 1-0 in a famous 1990 World Cup group stage upset?","options":["Nigeria","Cameroon","Morocco","Algeria"],"correct":1,"explanation":"Cameroon beat defending champions Argentina 1-0 in the 1990 opening match.","category":"history","difficulty":"medium"},
  {"id":70,"question":"Which player is the youngest ever to score at a World Cup?","options":["Pelé","Cesc Fàbregas","Lamine Yamal","Norman Whiteside"],"correct":0,"explanation":"Pelé scored at 17 years and 239 days old at the 1958 World Cup.","category":"records","difficulty":"medium"},
  {"id":71,"question":"Uruguay drew 2-2 with Cape Verde at the 2026 World Cup. What was surprising about this result?","options":["Uruguay were 2-0 up at half time","Cape Verde were already eliminated","It was Uruguay's first draw ever","Uruguay had won 10 straight games"],"correct":0,"explanation":"Uruguay led 2-0 but Cape Verde equalised — dropping two crucial points.","category":"2026","difficulty":"medium"},
  {"id":72,"question":"How many goals did Germany score across their two 2026 World Cup group stage games?","options":["7","9","8","6"],"correct":1,"explanation":"Germany scored 9 goals: 7-1 vs Curaçao and 2-1 vs Ivory Coast.","category":"2026","difficulty":"medium"},
  {"id":73,"question":"Which player scored twice for Brazil against Haiti at the 2026 World Cup?","options":["Vinicius Jr.","Rodrygo","Richarlison","Neymar"],"correct":0,"explanation":"Vinicius Jr. scored twice as Brazil beat Haiti 3-0.","category":"2026","difficulty":"medium"},
  {"id":74,"question":"Which team did Morocco beat 1-0 to win 2026 World Cup Group C?","options":["Brazil","Haiti","Scotland","Jordan"],"correct":2,"explanation":"Morocco beat Scotland 1-0 in their Group C clash, helping them top the group.","category":"2026","difficulty":"medium"},
  {"id":75,"question":"Which player scored a stunning bicycle kick at the 2018 World Cup that was voted goal of the tournament?","options":["Gareth Bale","Benjamin Pavard","Cristiano Ronaldo","Neymar"],"correct":1,"explanation":"Benjamin Pavard scored a stunning right-foot volley for France against Argentina in 2018 — voted goal of the tournament.","category":"history","difficulty":"hard"},
  {"id":76,"question":"How many red cards were shown at the 2022 World Cup?","options":["3","6","9","12"],"correct":1,"explanation":"Six red cards were shown at the 2022 World Cup in Qatar.","category":"history","difficulty":"hard"},
  {"id":77,"question":"Which team knocked out the holders Brazil at the 2010 World Cup quarter-finals?","options":["Spain","Germany","Argentina","Netherlands"],"correct":3,"explanation":"The Netherlands eliminated Brazil 2-1 in the 2010 quarter-finals.","category":"history","difficulty":"medium"},
  {"id":78,"question":"Which team was in the same 2026 World Cup group as Netherlands, Japan and Sweden?","options":["South Korea","Ivory Coast","Tunisia","Qatar"],"correct":2,"explanation":"Tunisia were in Group F at the 2026 World Cup alongside Netherlands, Japan and Sweden.","category":"2026","difficulty":"medium"},
  {"id":79,"question":"Ecuador drew 0-0 with which team at the 2026 World Cup?","options":["Qatar","Bosnia","Curaçao","Uzbekistan"],"correct":2,"explanation":"Ecuador drew 0-0 with Curaçao in Group E of the 2026 World Cup.","category":"2026","difficulty":"hard"},
  {"id":80,"question":"Which country's goalkeeper Dayne St. Clair kept a clean sheet in a 6-0 win at the 2026 World Cup?","options":["USA","Mexico","Canada","France"],"correct":2,"explanation":"Dayne St. Clair was Canada's first-choice goalkeeper in their 6-0 win over Qatar.","category":"2026","difficulty":"hard"},
  {"id":81,"question":"Which player won the 2022 World Cup's best goalkeeper award after saving two penalties in the final shootout?","options":["Yassine Bounou","Emiliano Martínez","Hugo Lloris","Dominik Livakovic"],"correct":1,"explanation":"Emiliano 'Dibu' Martínez won the Golden Glove after saving two penalties in the final shootout.","category":"history","difficulty":"medium"},
  {"id":82,"question":"Which team did Australia beat in the 2022 World Cup Round of 16 — their best World Cup result at the time?","options":["Argentina","France","Denmark","Tunisia"],"correct":2,"explanation":"Australia beat Denmark 1-0 in the 2022 Round of 16.","category":"history","difficulty":"medium"},
  {"id":83,"question":"Germany beat Ivory Coast 2-1 at the 2026 World Cup. In which Canadian city was this match played?","options":["Montreal","Vancouver","Toronto","Calgary"],"correct":2,"explanation":"Germany beat Ivory Coast 2-1 in Toronto at the 2026 World Cup.","category":"2026","difficulty":"hard"},
  {"id":84,"question":"What was the score of the 2022 World Cup final after 90 minutes?","options":["2-0 Argentina","1-0 France","2-2","1-1"],"correct":0,"explanation":"Argentina led 2-0 after 90 minutes before Mbappé scored twice in two minutes to equalise, making it 2-2.","category":"history","difficulty":"hard"},
  {"id":85,"question":"Norway beat Iraq 4-1 at the 2026 World Cup. In which US city?","options":["Dallas","Seattle","Toronto","Vancouver"],"correct":1,"explanation":"Norway's 4-1 win over Iraq was played in Seattle.","category":"2026","difficulty":"hard"},
  {"id":86,"question":"Which player scored the most goals at a single Women's World Cup?","options":["Marta","Birgit Prinz","Abby Wambach","Michelle Akers"],"correct":0,"explanation":"Marta scored 17 goals across multiple World Cups, with her best single tournament being 2007 (7 goals).","category":"records","difficulty":"hard"},
  {"id":87,"question":"Which 2026 World Cup group was known as the toughest, with Argentina, Austria, Algeria and Jordan?","options":["Group H","Group I","Group J","Group K"],"correct":2,"explanation":"Group J — containing Argentina, Austria, Algeria and Jordan — was considered one of the tournament's toughest groups.","category":"2026","difficulty":"medium"},
  {"id":88,"question":"Egypt beat New Zealand 3-1 in the 2026 World Cup. Which group did they play in?","options":["Group F","Group G","Group H","Group E"],"correct":1,"explanation":"Egypt and New Zealand were in Group G at the 2026 World Cup.","category":"2026","difficulty":"medium"},
  {"id":89,"question":"Paraguay beat Turkey 1-0 at the 2026 World Cup in which group?","options":["Group C","Group D","Group E","Group F"],"correct":1,"explanation":"Paraguay beat Turkey 1-0 in Group D of the 2026 World Cup.","category":"2026","difficulty":"medium"},
  {"id":90,"question":"Spain beat Saudi Arabia 4-0 at the 2026 World Cup. After a disappointing opening result, what was Spain's first game result?","options":["1-0 win","2-1 win","0-0 draw","1-1 draw"],"correct":2,"explanation":"Spain drew 0-0 with Cape Verde in their opening game before bouncing back to beat Saudi Arabia 4-0.","category":"2026","difficulty":"medium"},
  {"id":91,"question":"Which legendary striker scored 15 World Cup goals across three tournaments for Brazil before Ronaldo broke his record?","options":["Pelé","Ronaldinho","Romario","Zico"],"correct":0,"explanation":"Pelé scored 12 World Cup goals across 1958, 1962 and 1966 — not 15. Ronaldo held the record with 15 before Klose broke it.","category":"records","difficulty":"hard"},
  {"id":92,"question":"Which country qualified from 2026 World Cup Group B alongside Canada?","options":["Qatar","Bosnia","Switzerland","Uzbekistan"],"correct":2,"explanation":"Switzerland qualified from Group B alongside Canada, with both teams advancing.","category":"2026","difficulty":"medium"},
  {"id":93,"question":"France's Kylian Mbappé became his country's all-time leading scorer at the 2026 World Cup against which team?","options":["Iraq","Senegal","Algeria","Norway"],"correct":1,"explanation":"Mbappé scored twice against Senegal to become France's all-time leading scorer.","category":"2026","difficulty":"medium"},
  {"id":94,"question":"Which African team surprisingly beat Spain 2-1 in the 2022 World Cup Round of 16?","options":["Senegal","Cameroon","Morocco","Tunisia"],"correct":2,"explanation":"Morocco beat Spain on penalties in the 2022 Round of 16 after a 0-0 draw — one of the biggest shocks of the tournament.","category":"history","difficulty":"medium"},
  {"id":95,"question":"Scotland lost to Morocco in the 2026 World Cup. What was the final score?","options":["1-0","2-0","2-1","0-0"],"correct":0,"explanation":"Morocco beat Scotland 1-0 in their Group C clash.","category":"2026","difficulty":"medium"},
  {"id":96,"question":"Which country's team plays their home games at the Maracanã stadium in Rio de Janeiro?","options":["Argentina","Uruguay","Brazil","Colombia"],"correct":2,"explanation":"The Maracanã is Brazil's most famous football stadium, home to the Brazilian national team.","category":"players","difficulty":"easy"},
  {"id":97,"question":"At the 2026 World Cup, which group had Belgium, Egypt, Iran and New Zealand?","options":["Group F","Group G","Group H","Group E"],"correct":1,"explanation":"Belgium, Egypt, Iran and New Zealand were all in Group G.","category":"2026","difficulty":"medium"},
  {"id":98,"question":"Which 2022 World Cup star scored against both Japan in the group stage and Brazil in the quarter-final for South Korea?","options":["Heung-min Son","Cho Gue-sung","Hwang Hee-chan","Lee Jae-sung"],"correct":2,"explanation":"Hwang Hee-chan scored the winner against Portugal and a crucial goal against Brazil for South Korea in 2022.","category":"history","difficulty":"hard"},
  {"id":99,"question":"Brazil beat which team 3-0 to qualify from Group C at the 2026 World Cup?","options":["Scotland","Morocco","Haiti","Jordan"],"correct":2,"explanation":"Brazil beat Haiti 3-0 in their Group C game to advance to the knockout rounds.","category":"2026","difficulty":"easy"},
  {"id":100,"question":"Which World Cup final venue is in East Rutherford, New Jersey, USA?","options":["Rose Bowl","MetLife Stadium","Allegiant Stadium","AT&T Stadium"],"correct":1,"explanation":"MetLife Stadium in East Rutherford, NJ, is scheduled to host the 2026 World Cup final.","category":"2026","difficulty":"medium"},
  {"id":101,"question":"Spain won the 2010 World Cup — the first time they had won it. True or false?","options":["True","False","They won it in 2008 too","They won it in 1982"],"correct":0,"explanation":"Spain's 2010 triumph was their first and only World Cup victory.","category":"history","difficulty":"easy"},
  {"id":102,"question":"Which 2026 World Cup group had USA, Paraguay, Australia and Turkey?","options":["Group C","Group D","Group E","Group F"],"correct":1,"explanation":"The USA, Paraguay, Australia and Turkey were in Group D.","category":"2026","difficulty":"easy"},
  {"id":103,"question":"Norway qualified from the 2026 World Cup group stage ahead of which team in their group?","options":["France","Senegal","Iraq","All of them"],"correct":1,"explanation":"Norway finished second in Group I behind France, with Senegal third and Iraq eliminated.","category":"2026","difficulty":"medium"},
  {"id":104,"question":"Which French player became their all-time top scorer at the 2026 World Cup?","options":["Antoine Griezmann","Olivier Giroud","Kylian Mbappé","Thierry Henry"],"correct":2,"explanation":"Kylian Mbappé surpassed Olivier Giroud to become France's all-time top scorer during the 2026 World Cup.","category":"2026","difficulty":"medium"},
  {"id":105,"question":"In what year was FIFA founded?","options":["1900","1904","1910","1920"],"correct":1,"explanation":"FIFA (Fédération Internationale de Football Association) was founded in Paris on 21 May 1904.","category":"history","difficulty":"medium"},
  {"id":106,"question":"Which World Cup had the infamous 'Battle of Santiago' — one of the most violent matches ever played?","options":["1950","1958","1962","1966"],"correct":2,"explanation":"The 'Battle of Santiago' between Chile and Italy at the 1962 World Cup saw two sendings-off and multiple fights in a notorious match.","category":"history","difficulty":"hard"},
  {"id":107,"question":"Which team won the inaugural FIFA World Cup in 1930 without a single defeat?","options":["Argentina","Brazil","Uruguay","Chile"],"correct":2,"explanation":"Uruguay went unbeaten through the 1930 World Cup, winning all four of their matches.","category":"history","difficulty":"medium"},
  {"id":108,"question":"Which Australian city would have fans watching the 2026 World Cup final at 6am local time?","options":["Perth","Sydney","Brisbane","Darwin"],"correct":1,"explanation":"Sydney (AEDT) is UTC+10 in winter, so a 4pm New York kickoff would be 6am the following morning in Sydney.","category":"2026","difficulty":"hard"},
  {"id":109,"question":"Which player scored an extraordinary chip goal for Nigeria against Spain at the 1998 World Cup?","options":["Jay-Jay Okocha","Nwankwo Kanu","Rashidi Yekini","Finidi George"],"correct":0,"explanation":"Jay-Jay Okocha scored a stunning chip against Spain at France '98 in a classic moment.","category":"history","difficulty":"hard"},
  {"id":110,"question":"How many goals did Spain score in the 2026 World Cup group stage?","options":["3","4","5","6"],"correct":1,"explanation":"Spain scored 4 goals in the group stage: 0 vs Cape Verde, 4 vs Saudi Arabia.","category":"2026","difficulty":"medium"},
  {"id":111,"question":"At the 2026 World Cup, Group K had Portugal, Colombia, DR Congo and which other team?","options":["Jordan","Uzbekistan","Bosnia","Algeria"],"correct":1,"explanation":"Group K consisted of Portugal, Colombia, DR Congo and Uzbekistan.","category":"2026","difficulty":"medium"},
  {"id":112,"question":"Which country has hosted the most World Cups?","options":["Brazil","Germany","France","Mexico"],"correct":3,"explanation":"Mexico hosted the World Cup in 1970, 1986 and 2026 — more times than any other country.","category":"history","difficulty":"medium"},
  {"id":113,"question":"Ecuador drew 0-0 with Curaçao at WC2026. Which sweepstake participant owns Ecuador?","options":["Crowle","Morris","T Rankin","Silk"],"correct":0,"explanation":"Crowle holds Ecuador in the WC2026 sweepstake.","category":"sweepstake","difficulty":"easy"},
  {"id":114,"question":"In the sweepstake, which participant owns both Brazil and Uruguay?","options":["Poncho Man","Morris","Cronan","Kenna"],"correct":1,"explanation":"Morris owns both Brazil and Uruguay in the WC2026 sweepstake.","category":"sweepstake","difficulty":"easy"},
  {"id":115,"question":"Which sweepstake participant owns France — the tournament favourite?","options":["Silk","Cronan","Poncho Man","Hankin"],"correct":1,"explanation":"Cronan owns France, giving them the highest win probability in the sweepstake.","category":"sweepstake","difficulty":"easy"},
  {"id":116,"question":"Which participant owns Argentina AND Morocco in the sweepstake?","options":["Same","Cronan","Poncho Man","T Rankin"],"correct":2,"explanation":"Poncho Man owns Argentina and Morocco — two teams who performed well in the group stage.","category":"sweepstake","difficulty":"easy"},
  {"id":117,"question":"Which sweepstake participant owns the most teams?","options":["Same","Kenna","Poncho Man","Cronan"],"correct":1,"explanation":"Kenna owns 8 teams — Spain, Senegal, South Korea, Egypt, Jordan, New Zealand, Curaçao and Haiti.","category":"sweepstake","difficulty":"easy"},
  {"id":118,"question":"Varcoe owns Japan, Switzerland, DR Congo and which other team?","options":["Mexico","Australia","Canada","Belgium"],"correct":2,"explanation":"Varcoe owns Canada, who famously beat Qatar 6-0 at the 2026 World Cup.","category":"sweepstake","difficulty":"easy"},
  {"id":119,"question":"Which participant owns Germany — their flagship asset who qualified from Group E?","options":["T Rankin","P Rankin","Hankin","Crowle"],"correct":1,"explanation":"P Rankin owns Germany in the WC2026 sweepstake.","category":"sweepstake","difficulty":"easy"},
  {"id":120,"question":"Which sweepstake participant owns the Netherlands, who beat Sweden 5-1?","options":["T Rankin","P Rankin","Silk","Morris"],"correct":0,"explanation":"T Rankin owns the Netherlands in the WC2026 sweepstake.","category":"sweepstake","difficulty":"easy"},
  {"id":121,"question":"Hankin owns Norway, Mexico, Ivory Coast and which other team?","options":["Iran","Belgium","Saudi Arabia","Scotland"],"correct":2,"explanation":"Hankin owns Saudi Arabia — though they were eliminated in the group stage after Spain beat them 4-0.","category":"sweepstake","difficulty":"easy"},
  {"id":122,"question":"Which sweepstake participant owns England and the USA?","options":["Cronan","Poncho Man","Silk","Same"],"correct":2,"explanation":"Silk owns England and USA — both strong performers at the 2026 World Cup.","category":"sweepstake","difficulty":"easy"},
  {"id":123,"question":"Same owns Portugal, Colombia, Paraguay and which other team?","options":["Jordan","Cape Verde","New Zealand","Tunisia"],"correct":1,"explanation":"Same owns Cape Verde — the team that famously drew 0-0 with Spain despite heavy pressure.","category":"sweepstake","difficulty":"easy"},
  {"id":124,"question":"Which participant owns Belgium, Ecuador, Bosnia and Uzbekistan?","options":["Morris","Crowle","T Rankin","Same"],"correct":1,"explanation":"Crowle owns Belgium, Ecuador, Bosnia and Uzbekistan — currently winless in the group stage.","category":"sweepstake","difficulty":"easy"},
  {"id":125,"question":"In the sweepstake, which participant owns Norway — the team shortening in the odds?","options":["Poncho Man","Hankin","P Rankin","Morris"],"correct":1,"explanation":"Hankin owns Norway, who impressed with a 4-1 win over Iraq at the 2026 World Cup.","category":"sweepstake","difficulty":"easy"},
  {"id":126,"question":"Which 2026 World Cup group had Spain, Saudi Arabia, Cape Verde and Uruguay?","options":["Group G","Group H","Group I","Group J"],"correct":1,"explanation":"Spain, Saudi Arabia, Cape Verde and Uruguay were all in Group H.","category":"2026","difficulty":"medium"},
  {"id":127,"question":"Which 2026 World Cup group had Belgium, Egypt, Iran and New Zealand?","options":["Group E","Group F","Group G","Group H"],"correct":2,"explanation":"Belgium, Egypt, Iran and New Zealand were all in Group G.","category":"2026","difficulty":"medium"},
  {"id":128,"question":"Which 2026 World Cup group had Germany, Curaçao, Ivory Coast and Ecuador?","options":["Group D","Group E","Group F","Group G"],"correct":1,"explanation":"Germany, Curaçao, Ivory Coast and Ecuador were in Group E.","category":"2026","difficulty":"medium"},
  {"id":129,"question":"Which 2026 World Cup group had Netherlands, Japan, Sweden and Tunisia?","options":["Group E","Group F","Group G","Group H"],"correct":1,"explanation":"Netherlands, Japan, Sweden and Tunisia were in Group F.","category":"2026","difficulty":"medium"},
  {"id":130,"question":"The 2026 World Cup final is scheduled at MetLife Stadium. In which US state is it located?","options":["New York","New Jersey","Pennsylvania","Connecticut"],"correct":1,"explanation":"MetLife Stadium is in East Rutherford, New Jersey — just across the Hudson River from New York City.","category":"2026","difficulty":"medium"}
]


def generate_trivia_schedule(data):
    """
    Pre-compute the full remaining trivia schedule for the tournament.
    Assigns 5 non-repeating questions per day from today until the WC final.
    Stored in data['trivia_schedule'] as {date: [question_ids]}.
    Called once per day — only generates for dates not yet scheduled.
    """
    from datetime import date, timedelta

    today = date.today()
    end = date.fromisoformat(WC_END_DATE)

    # Load existing schedule
    existing = data.get("trivia_schedule", {})
    existing_ids = set()
    for ids in existing.values():
        existing_ids.update(ids)

    # Available question IDs (not yet scheduled)
    all_ids = [q["id"] for q in ALL_QUESTIONS]
    available = [qid for qid in all_ids if qid not in existing_ids]

    # Generate schedule for remaining days
    current = today
    new_days = 0
    while current <= end:
        date_str = current.isoformat()
        if date_str not in existing:
            if len(available) < 5:
                print(f"  Warning: only {len(available)} questions left for {date_str}")
                break
            # Pick next 5 questions in order (already randomised by question bank design)
            todays_ids = available[:5]
            available = available[5:]
            existing[date_str] = todays_ids
            new_days += 1
        current += timedelta(days=1)

    data["trivia_schedule"] = existing
    data["trivia_questions"] = ALL_QUESTIONS
    data["meta"]["trivia_schedule_generated"] = datetime.now(timezone.utc).isoformat()

    days_covered = len(existing)
    remaining = (end - today).days + 1
    print(f"  Trivia schedule: {days_covered} days covered, {new_days} new days added")
    print(f"  Tournament days remaining: {remaining}")
    print(f"  Questions in bank: {len(ALL_QUESTIONS)}, questions scheduled: {sum(len(v) for v in existing.values())}")
    return data


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

    # Post-process: detect and warn about eliminated team mentions
    teams_in_odds_set = {o["team"] for o in data.get("odds", [])}
    all_participant_teams = set()
    for info in data.get("participants", {}).values():
        all_participant_teams.update(info.get("teams", []))
    eliminated_check = all_participant_teams - teams_in_odds_set
    for c in commentary:
        flagged = [t for t in eliminated_check if t in c.get("body","") or t in c.get("title","")]
        if flagged:
            # Truncate body to just the first sentence mentioning an alive team
            print(f"  WARN: {c['participant']} mentions eliminated teams {flagged} — replacing body")
            c["body"] = (
                f"{c['participant']} is still in the sweepstake with "
                + next((f"{o['team']} at {o['now']}" for o in data.get('odds',[]) if o['owner']==c['participant']), "their team")
                + ". [Commentary regeneration required — eliminated team reference detected and removed.]"
            )

    # 3. Write back to data.json
    data["exec_summary"] = exec_summary
    data["commentary"]   = commentary
    data["meta"]["last_commentary_participants"] = participants
    data["meta"]["last_commentary_generated"]    = datetime.now(timezone.utc).isoformat()
    data["meta"]["edition"] = data["meta"].get("edition", 1) + 1

    # 3. Generate/update trivia schedule
    data = generate_trivia_schedule(data)

    # Write via GitHub API to avoid push conflicts with concurrent runs
    import base64
    github_token = os.environ.get("GITHUB_TOKEN", "")
    if github_token:
        try:
            repo = os.environ.get("GITHUB_REPOSITORY", "")
            api_url = f"https://api.github.com/repos/{repo}/contents/data/data.json"
            headers = {
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github.v3+json"
            }
            sha = requests.get(api_url, headers=headers, timeout=15).json().get("sha", "")
            encoded = base64.b64encode(
                json.dumps(data, indent=2, ensure_ascii=False).encode()
            ).decode()
            put = requests.put(api_url, headers=headers, json={
                "message": f"chore: daily commentary {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                "content": encoded,
                "sha": sha
            }, timeout=15)
            if put.status_code in (200, 201):
                print(f"  data.json written via GitHub API ✓")
            else:
                raise Exception(f"API write failed: {put.status_code}")
        except Exception as e:
            print(f"  API write failed ({e}), falling back to local")
            with open(DATA_FILE, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    else:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"  Done. Edition written.")
    for c in commentary:
        print(f"    → {c['title']}")


if __name__ == "__main__":
    main()
