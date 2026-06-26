"""
fetch_scores.py
Pulls live WC2026 results from football-data.org and updates data/data.json
Runs every 30 minutes via GitHub Actions.
"""

import os
import json
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
API_KEY     = os.environ["FOOTBALL_API_KEY"]   # set in GitHub secrets
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")  # The Odds API key for AU bookmaker odds
API_BASE    = "https://api.football-data.org/v4"
WC_COMP_ID  = 2000   # football-data.org competition ID for FIFA World Cup
DATA_FILE   = Path(__file__).parent.parent / "data" / "data.json"
AEST        = timezone(timedelta(hours=10))

HEADERS = {
    "X-Auth-Token": API_KEY,
    "Accept": "application/json"
}

# ── Participant map ───────────────────────────────────────────────────────────
# Maps football-data.org team names → our sweepstake participant
TEAM_TO_OWNER = {
    # Kenna
    "Spain": "Kenna", "Senegal": "Kenna", "Korea Republic": "Kenna",
    "Egypt": "Kenna", "Jordan": "Kenna", "New Zealand": "Kenna",
    "Curaçao": "Kenna", "Haiti": "Kenna",
    # Cronan
    "France": "Cronan", "Austria": "Cronan", "Australia": "Cronan", "Panama": "Cronan",
    # Silk
    "England": "Silk", "USA": "Silk", "United States": "Silk",
    "Algeria": "Silk", "Qatar": "Silk",
    # Same
    "Portugal": "Same", "Colombia": "Same", "Paraguay": "Same", "Cape Verde": "Same",
    # Galbraith
    "Argentina": "Galbraith", "Morocco": "Galbraith",
    "Türkiye": "Galbraith", "Turkey": "Galbraith", "South Africa": "Galbraith",
    # Morris
    "Brazil": "Morris", "Uruguay": "Morris", "Scotland": "Morris", "Iran": "Morris",
    # P Rankin
    "Germany": "P Rankin", "Czech Republic": "P Rankin", "Czechia": "P Rankin",
    "Iraq": "P Rankin", "Sweden": "P Rankin",
    # T Rankin
    "Netherlands": "T Rankin", "Croatia": "T Rankin",
    "Ghana": "T Rankin", "Tunisia": "T Rankin",
    # Hankin
    "Norway": "Hankin", "Mexico": "Hankin",
    "Côte d'Ivoire": "Hankin", "Ivory Coast": "Hankin", "Saudi Arabia": "Hankin",
    # Varcoe
    "Japan": "Varcoe", "Switzerland": "Varcoe",
    "DR Congo": "Varcoe", "Congo DR": "Varcoe",
    "Democratic Republic of Congo": "Varcoe", "Canada": "Varcoe",
    # Crowle
    "Belgium": "Crowle", "Ecuador": "Crowle",
    "Bosnia and Herzegovina": "Crowle", "Bosnia": "Crowle", "Uzbekistan": "Crowle",
}

DISPLAY_NAMES = {
    "Korea Republic": "South Korea", "Türkiye": "Turkey",
    "Côte d'Ivoire": "Ivory Coast", "Congo DR": "DR Congo",
    "Democratic Republic of Congo": "DR Congo",
    "United States": "USA", "Bosnia and Herzegovina": "Bosnia",
    "Czechia": "Czech Republic",
}

def get_display_name(api_name):
    return DISPLAY_NAMES.get(api_name, api_name)

def get_owner(api_name):
    return TEAM_TO_OWNER.get(api_name, TEAM_TO_OWNER.get(get_display_name(api_name), "?"))

def get_badge(match):
    """Assign a badge based on match context."""
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    hs = match["score"]["fullTime"]["home"]
    as_ = match["score"]["fullTime"]["away"]
    if hs is None or as_ is None:
        return ""
    diff = abs(hs - as_)
    home_owner = get_owner(home)
    away_owner = get_owner(away)
    # High-profile favourites losing or drawing
    big_teams = {"Spain", "France", "Argentina", "Brazil", "England", "Germany",
                 "Netherlands", "Portugal"}
    home_disp = get_display_name(home)
    away_disp = get_display_name(away)
    if home_disp in big_teams and as_ > hs:
        return "SHOCK RESULT"
    if away_disp in big_teams and hs > as_:
        return "SHOCK RESULT"
    if diff >= 4:
        return "STATEMENT WIN"
    return ""

def fetch_matches():
    """Fetch all WC2026 matches from football-data.org."""
    url = f"{API_BASE}/competitions/{WC_COMP_ID}/matches"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json().get("matches", [])

def format_aest(utc_str):
    """Convert UTC ISO string to AEST display string."""
    if not utc_str:
        return ""
    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    dt_aest = dt.astimezone(AEST)
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    day = day_names[dt_aest.weekday()]
    hour = dt_aest.strftime("%-I:%M%p").lower().replace("am", "am").replace("pm", "pm")
    return f"{day} {hour}"

def format_date_short(utc_str):
    """Format as '22 Jun'."""
    if not utc_str:
        return ""
    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    dt_aest = dt.astimezone(AEST)
    return dt_aest.strftime("%-d %b")

def format_date_iso(utc_str):
    """Format as 'YYYY-MM-DD' in AEST."""
    if not utc_str:
        return ""
    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    dt_aest = dt.astimezone(AEST)
    return dt_aest.strftime("%Y-%m-%d")

def build_standings(matches):
    """
    Build participant standings from match results.
    Win% is NOT calculated here (needs odds API) — preserved from existing data.
    """
    stats = {}
    for name in TEAM_TO_OWNER.values():
        if name not in stats:
            stats[name] = {"w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pld": 0}

    for m in matches:
        if m["status"] != "FINISHED":
            continue
        home_name = m["homeTeam"]["name"]
        away_name = m["awayTeam"]["name"]
        hs = m["score"]["fullTime"]["home"]
        as_ = m["score"]["fullTime"]["away"]
        if hs is None or as_ is None:
            continue

        home_owner = get_owner(home_name)
        away_owner = get_owner(away_name)

        for owner, gf, ga in [(home_owner, hs, as_), (away_owner, as_, hs)]:
            if owner == "?":
                continue
            stats[owner]["pld"] += 1
            stats[owner]["gf"] += gf
            stats[owner]["ga"] += ga
            if gf > ga:
                stats[owner]["w"] += 1
            elif gf == ga:
                stats[owner]["d"] += 1
            else:
                stats[owner]["l"] += 1

    result = []
    for name, s in stats.items():
        pts = s["w"] * 3 + s["d"]
        gd = s["gf"] - s["ga"]
        result.append({
            "name": name,
            "pld": s["pld"],
            "w": s["w"],
            "d": s["d"],
            "l": s["l"],
            "pts": pts,
            "gd": gd,
        })

    # Sort by pts desc, then gd desc
    result.sort(key=lambda x: (-x["pts"], -x["gd"]))
    for i, r in enumerate(result):
        r["rank"] = i + 1
    return result

def build_results(matches):
    """
    Build results list:
    - IN_PLAY / PAUSED games always shown first with live score + match minute
    - FINISHED games from the last 24 hours only
    - Sorted by kick-off time descending (most recent first)
    """
    now_utc = datetime.now(timezone.utc)
    cutoff_24h = now_utc - timedelta(hours=24)

    results = []

    # 1. Live / in-progress games first
    for m in matches:
        if m["status"] not in ("IN_PLAY", "PAUSED"):
            continue
        home_name = m["homeTeam"]["name"]
        away_name = m["awayTeam"]["name"]
        home_owner = get_owner(home_name)
        away_owner = get_owner(away_name)
        group = m.get("group", "").replace("GROUP_", "Group ").replace("_", " ")

        # Score — try fullTime first, fallback to currentPeriodStartScore then 0
        score = m.get("score", {})
        hs = (score.get("fullTime") or {}).get("home")
        as_ = (score.get("fullTime") or {}).get("away")
        if hs is None:
            hs = (score.get("halfTime") or {}).get("home", 0)
            as_ = (score.get("halfTime") or {}).get("away", 0)

        # Match minute — football-data.org doesn't always provide this,
        # so we estimate from kick-off time
        utc_str = m.get("utcDate", "")
        match_minute = ""
        if utc_str:
            try:
                ko = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                elapsed = int((now_utc - ko).total_seconds() / 60)
                if 0 <= elapsed <= 90:
                    match_minute = f"{elapsed}'"
                elif elapsed > 90:
                    match_minute = "90+'"
            except:
                pass

        results.append({
            "date": format_date_short(utc_str),
            "aest_time": format_aest(utc_str),
            "group": group,
            "home": get_display_name(home_name),
            "home_owner": home_owner,
            "away": get_display_name(away_name),
            "away_owner": away_owner,
            "home_score": hs,
            "away_score": as_,
            "status": "LIVE",
            "match_minute": match_minute,
            "badge": "LIVE",
            "sweepstake_relevant": home_owner != "?" or away_owner != "?",
            "sort_key": "0_live"
        })

    # 2. Finished games from last 24 hours
    finished = [m for m in matches if m["status"] == "FINISHED"]
    finished.sort(key=lambda m: m.get("utcDate", ""), reverse=True)

    for m in finished:
        utc_str = m.get("utcDate", "")
        if utc_str:
            try:
                dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                if dt < cutoff_24h:
                    continue  # older than 24 hours — skip
            except:
                pass

        home_name = m["homeTeam"]["name"]
        away_name = m["awayTeam"]["name"]
        home_owner = get_owner(home_name)
        away_owner = get_owner(away_name)
        hs = (m["score"].get("fullTime") or {}).get("home")
        as_ = (m["score"].get("fullTime") or {}).get("away")
        group = m.get("group", "").replace("GROUP_", "Group ").replace("_", " ")

        results.append({
            "date": format_date_short(utc_str),
            "aest_time": format_aest(utc_str),
            "group": group,
            "home": get_display_name(home_name),
            "home_owner": home_owner,
            "away": get_display_name(away_name),
            "away_owner": away_owner,
            "home_score": hs,
            "away_score": as_,
            "status": "FT",
            "match_minute": "",
            "badge": get_badge(m),
            "sweepstake_relevant": home_owner != "?" or away_owner != "?",
            "sort_key": "1_" + utc_str
        })

    # Sort: live first, then finished by kick-off descending
    results.sort(key=lambda r: r["sort_key"])
    return results

def build_upcoming(matches):
    """Build upcoming fixtures for the next 48 hours."""
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=48)

    upcoming = []
    scheduled = [m for m in matches if m["status"] in ("SCHEDULED", "TIMED", "IN_PLAY", "PAUSED")]
    scheduled.sort(key=lambda m: m.get("utcDate", ""))

    for m in scheduled:
        utc_str = m.get("utcDate", "")
        if not utc_str:
            continue
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        if dt > cutoff:
            continue

        home_name = m["homeTeam"]["name"]
        away_name = m["awayTeam"]["name"]
        home_owner = get_owner(home_name)
        away_owner = get_owner(away_name)
        group = m.get("group", "").replace("GROUP_", "").replace("_", " ").strip()
        status = m["status"]

        entry = {
            "aest_time": format_aest(utc_str),
            "group": group,
            "home": get_display_name(home_name),
            "home_owner": home_owner,
            "away": get_display_name(away_name),
            "away_owner": away_owner,
            "status": status,
            "context": ""
        }

        # Add live score if in play
        if status in ("IN_PLAY", "PAUSED"):
            hs = m["score"].get("fullTime", {}).get("home") or m["score"].get("halfTime", {}).get("home", 0)
            as_ = m["score"].get("fullTime", {}).get("away") or m["score"].get("halfTime", {}).get("away", 0)
            entry["live_score"] = f"{hs}–{as_}"
            entry["aest_time"] = "🔴 LIVE"

        upcoming.append(entry)

    return upcoming


# ── Knockout bracket builder ──────────────────────────────────────────────────
# football-data.org stage names for WC2026 knockout rounds
STAGE_ORDER = ["ROUND_OF_32", "LAST_16", "QUARTER_FINALS", "SEMI_FINALS", "FINAL"]
STAGE_LABELS = {
    "ROUND_OF_32": "R32",
    "LAST_16": "R16",
    "QUARTER_FINALS": "QF",
    "SEMI_FINALS": "SF",
    "FINAL": "F",
}

def build_knockout(matches):
    """
    Build knockout bracket data from all matches.
    Returns a dict with stage data including results and placeholders.
    Each match entry has:
      id, stage, date_aest, date_iso, home, home_owner, home_score,
      away, away_owner, away_score, status, winner, venue
    """
    ko_stages = {}
    for stage in STAGE_ORDER:
        ko_stages[stage] = []

    for m in matches:
        stage = m.get("stage", "")
        if stage not in STAGE_ORDER:
            continue

        utc_str = m.get("utcDate", "")
        home_name = m["homeTeam"].get("name") or m["homeTeam"].get("shortName") or ""
        away_name = m["awayTeam"].get("name") or m["awayTeam"].get("shortName") or ""

        # Placeholder teams appear as empty strings or None in the API
        home_display = get_display_name(home_name) if home_name else None
        away_display = get_display_name(away_name) if away_name else None
        home_owner = get_owner(home_name) if home_name else None
        away_owner = get_owner(away_name) if away_name else None

        score = m.get("score", {})
        hs = (score.get("fullTime") or {}).get("home")
        as_ = (score.get("fullTime") or {}).get("away")

        # Determine winner for finished matches
        winner = None
        if m["status"] == "FINISHED" and hs is not None and as_ is not None:
            if hs > as_:
                winner = "home"
            elif as_ > hs:
                winner = "away"
            else:
                # Check penalties/ET
                penalties = score.get("penalties") or {}
                ph = penalties.get("home")
                pa = penalties.get("away")
                if ph is not None and pa is not None:
                    winner = "home" if ph > pa else "away"

        # Score display: for ET/Penalties show ET score
        et_score = score.get("extraTime") or {}
        et_h = et_score.get("home")
        et_a = et_score.get("away")
        pen_score = score.get("penalties") or {}
        pen_h = pen_score.get("home")
        pen_a = pen_score.get("away")

        score_note = ""
        if pen_h is not None:
            score_note = f"(pens {pen_h}–{pen_a})"
        elif et_h is not None:
            score_note = "(aet)"

        status = m["status"]
        # Normalise live statuses
        if status in ("IN_PLAY", "PAUSED"):
            status = "LIVE"

        venue = m.get("venue", "") or ""

        ko_stages[stage].append({
            "id": m.get("id"),
            "stage": stage,
            "stage_label": STAGE_LABELS[stage],
            "date_aest": format_aest(utc_str),
            "date_short": format_date_short(utc_str),
            "date_iso": format_date_iso(utc_str),
            "home": home_display,
            "home_owner": home_owner if home_owner != "?" else None,
            "home_score": hs,
            "away": away_display,
            "away_owner": away_owner if away_owner != "?" else None,
            "away_score": as_,
            "score_note": score_note,
            "status": status,
            "winner": winner,
            "venue": venue,
        })

    # Sort each stage by date
    for stage in ko_stages:
        ko_stages[stage].sort(key=lambda x: x.get("date_iso") or "")

    # Build flat list in bracket order (R32 first)
    stages_list = []
    for stage in STAGE_ORDER:
        if ko_stages[stage]:
            stages_list.append({
                "stage": stage,
                "label": STAGE_LABELS[stage],
                "matches": ko_stages[stage],
            })

    return stages_list


def fetch_au_odds():
    """
    Fetch World Cup winner outright odds from Australian bookmakers
    via The Odds API (the-odds-api.com).
    Returns list of {team, owner, prev, now, now_decimal, direction, source} dicts.
    """
    if not ODDS_API_KEY:
        print("  No ODDS_API_KEY set, skipping odds update")
        return None

    OWNER_MAP = {
        "Spain":"Kenna","Senegal":"Kenna","South Korea":"Kenna","Egypt":"Kenna",
        "Jordan":"Kenna","New Zealand":"Kenna","Curaçao":"Kenna","Curacao":"Kenna","Haiti":"Kenna",
        "France":"Cronan","Austria":"Cronan","Australia":"Cronan","Panama":"Cronan",
        "England":"Silk","United States":"Silk","Algeria":"Silk","Qatar":"Silk",
        "Portugal":"Same","Colombia":"Same","Paraguay":"Same","Cape Verde":"Same",
        "Argentina":"Galbraith","Morocco":"Galbraith","Turkey":"Galbraith","South Africa":"Galbraith",
        "Brazil":"Morris","Uruguay":"Morris","Scotland":"Morris","Iran":"Morris",
        "Germany":"P Rankin","Czech Republic":"P Rankin","Iraq":"P Rankin","Sweden":"P Rankin",
        "Netherlands":"T Rankin","Croatia":"T Rankin","Ghana":"T Rankin","Tunisia":"T Rankin",
        "Norway":"Hankin","Mexico":"Hankin","Ivory Coast":"Hankin","Côte d'Ivoire":"Hankin","Saudi Arabia":"Hankin",
        "Japan":"Varcoe","Switzerland":"Varcoe","DR Congo":"Varcoe","Congo DR":"Varcoe","Canada":"Varcoe",
        "Belgium":"Crowle","Ecuador":"Crowle","Bosnia and Herzegovina":"Crowle","Bosnia":"Crowle","Uzbekistan":"Crowle",
    }

    try:
        resp = requests.get(
            "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup_winner/odds/",
            params={
                "apiKey": ODDS_API_KEY,
                "regions": "au",
                "markets": "outrights",
                "oddsFormat": "decimal"
            },
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        remaining = resp.headers.get("x-requests-remaining", "?")
        print(f"  Odds API requests remaining: {remaining}")

        if not data:
            print("  No odds data returned")
            return None

        event = data[0]
        # Get best price per team across all AU bookmakers
        best = {}
        for bm in event.get("bookmakers", []):
            bm_name = bm["title"]
            for o in bm.get("markets", [{}])[0].get("outcomes", []):
                team = o["name"]
                price = o["price"]
                if team not in best or price > best[team]["price"]:
                    best[team] = {"price": price, "bookmaker": bm_name}

        return best, OWNER_MAP

    except Exception as e:
        print(f"  Odds fetch error: {e}")
        return None


def update_odds(existing_data, best_odds, owner_map):
    """Merge fresh AU odds into existing data, tracking price movement."""
    if not best_odds:
        return existing_data

    best, OWNER_MAP = best_odds
    old_odds_map = {o["team"]: o for o in existing_data.get("odds", [])}

    new_odds = []
    for team, curr in best.items():
        owner = OWNER_MAP.get(team)
        if not owner:
            continue  # skip teams not in sweepstake

        curr_price = curr["price"]
        bm = curr["bookmaker"]
        old = old_odds_map.get(team, {})

        try:
            old_price = float(str(old.get("now_decimal", curr_price)))
            if curr_price < old_price - 0.05:
                direction = "shortened"
            elif curr_price > old_price + 0.05:
                direction = "drifted"
            else:
                direction = "unchanged"
            prev_display = f"${old_price:.1f}"
        except:
            direction = "unchanged"
            prev_display = f"${curr_price:.1f}"

        new_odds.append({
            "team": team,
            "owner": owner,
            "prev": prev_display,
            "now": f"${curr_price:.1f}",
            "now_decimal": curr_price,
            "direction": direction,
            "source": bm
        })

    new_odds.sort(key=lambda x: x["now_decimal"])
    existing_data["odds"] = new_odds
    existing_data["meta"]["odds_format"] = "decimal (Australian)"
    existing_data["meta"]["odds_source"] = "The Odds API — Unibet, TAB, Betfair AU"
    existing_data["meta"]["odds_last_updated"] = datetime.now(AEST).strftime("%-d %b %Y %-I:%Mam AEST").replace("am","am").replace("pm","pm")
    print(f"  Odds updated: {len(new_odds)} teams, best AU prices")
    return existing_data

def main():
    print("Fetching WC2026 matches...")
    matches = fetch_matches()
    print(f"  Got {len(matches)} matches total")

    # Load existing data to preserve win_pct, commentary, odds
    with open(DATA_FILE) as f:
        existing = json.load(f)

    # Build fresh data
    new_standings_raw = build_standings(matches)
    new_results = build_results(matches)
    new_upcoming = build_upcoming(matches)
    new_knockout = build_knockout(matches)

    # Merge standings: update on-pitch stats, preserve win_pct/move from existing
    existing_standing_map = {s["name"]: s for s in existing.get("standings", [])}
    merged_standings = []
    for s in new_standings_raw:
        ex = existing_standing_map.get(s["name"], {})
        merged_standings.append({
            **s,
            "left": ex.get("left", 0),
            "win_pct": ex.get("win_pct", 0.0),
            "move": ex.get("move", "same"),
            "move_note": ex.get("move_note", ""),
        })
    # Re-sort by win_pct (primary sweepstake metric)
    merged_standings.sort(key=lambda x: -x["win_pct"])
    for i, s in enumerate(merged_standings):
        s["rank"] = i + 1

    # Update meta
    now_aest = datetime.now(AEST)
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day = day_names[now_aest.weekday()]
    refresh_aest = datetime.now(AEST)
    existing["meta"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    existing["meta"]["last_score_refresh"] = refresh_aest.strftime("%-d %b %Y %-I:%M%p AEST").replace("AM","am").replace("PM","pm")
    existing["meta"]["last_updated_aest"] = now_aest.strftime(
        f"{day} %-d %b %Y, %-I:%M%p AEST"
    ).replace("AM","am").replace("PM","pm")

    # Merge upcoming: preserve context notes where we have them
    existing_fixture_map = {}
    for f in existing.get("upcoming_fixtures", []):
        key = f"{f['home']}_{f['away']}"
        existing_fixture_map[key] = f.get("context", "")
    for f in new_upcoming:
        key = f"{f['home']}_{f['away']}"
        if not f.get("context") and key in existing_fixture_map:
            f["context"] = existing_fixture_map[key]

    # Fetch and update AU odds
    best_odds = fetch_au_odds()
    if best_odds:
        existing = update_odds(existing, best_odds, {})

    # Write back
    existing["standings"] = merged_standings
    existing["recent_results"] = new_results
    existing["upcoming_fixtures"] = new_upcoming
    existing["knockout"] = new_knockout

    with open(DATA_FILE, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    finished_count = len([m for m in matches if m["status"] == "FINISHED"])
    live_count = len([m for m in matches if m["status"] in ("IN_PLAY", "PAUSED")])
    ko_count = sum(len(s["matches"]) for s in new_knockout)
    print(f"  Finished: {finished_count}, Live: {live_count}")
    print(f"  Knockout matches found: {ko_count}")
    print(f"  Updated {DATA_FILE}")
    print(f"  Last updated: {existing['meta']['last_updated_aest']}")

if __name__ == "__main__":
    main()
