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
    # Poncho Man
    "Argentina": "Poncho Man", "Morocco": "Poncho Man",
    "Türkiye": "Poncho Man", "Turkey": "Poncho Man", "South Africa": "Poncho Man",
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
    "Bosnia and Herzegovina": "Crowle", "Bosnia": "Crowle",
    "Bosnia-Herzegovina": "Crowle", "Bosnia & Herzegovina": "Crowle",
    "Uzbekistan": "Crowle",
}

DISPLAY_NAMES = {
    "Korea Republic": "South Korea", "Türkiye": "Turkey",
    "Côte d'Ivoire": "Ivory Coast", "Congo DR": "DR Congo",
    "Democratic Republic of Congo": "DR Congo",
    "United States": "USA",
    "Bosnia and Herzegovina": "Bosnia",
    "Bosnia-Herzegovina": "Bosnia",
    "Bosnia & Herzegovina": "Bosnia",
    "Czechia": "Czech Republic",
    "Cape Verde Islands": "Cape Verde",
    "IR Iran": "Iran",
}

def get_display_name(api_name):
    return DISPLAY_NAMES.get(api_name, api_name)

def get_owner(api_name):
    if not api_name:
        return "?"
    display = get_display_name(api_name)
    return (TEAM_TO_OWNER.get(api_name)
         or TEAM_TO_OWNER.get(display)
         or TEAM_TO_OWNER.get(api_name.replace("-", " and "))
         or TEAM_TO_OWNER.get(api_name.replace("-", " "))
         or "?")

def get_badge(match):
    """Assign a badge based on match context."""
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    hs = (match["score"].get("fullTime") or {}).get("home")
    as_ = (match["score"].get("fullTime") or {}).get("away")
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
        home_name = m["homeTeam"].get("name") or m["homeTeam"].get("shortName") or "TBD"
        away_name = m["awayTeam"].get("name") or m["awayTeam"].get("shortName") or "TBD"
        home_owner = get_owner(home_name) if home_name != "TBD" else "?"
        away_owner = get_owner(away_name) if away_name != "TBD" else "?"
        group_raw = m.get("group") or m.get("stage") or ""
        group = group_raw.replace("GROUP_", "Group ").replace("ROUND_OF_32","Round of 32").replace("LAST_32","Round of 32").replace("LAST_16","Round of 16").replace("QUARTER_FINALS","Quarter-Final").replace("SEMI_FINALS","Semi-Final").replace("FINAL","Final").replace("_", " ")

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

        home_name = m["homeTeam"].get("name") or m["homeTeam"].get("shortName") or "TBD"
        away_name = m["awayTeam"].get("name") or m["awayTeam"].get("shortName") or "TBD"
        home_owner = get_owner(home_name) if home_name != "TBD" else "?"
        away_owner = get_owner(away_name) if away_name != "TBD" else "?"
        hs = (m["score"].get("fullTime") or {}).get("home")
        as_ = (m["score"].get("fullTime") or {}).get("away")
        group_raw = m.get("group") or m.get("stage") or ""
        group = group_raw.replace("GROUP_", "Group ").replace("ROUND_OF_32","Round of 32").replace("LAST_32","Round of 32").replace("LAST_16","Round of 16").replace("QUARTER_FINALS","Quarter-Final").replace("SEMI_FINALS","Semi-Final").replace("FINAL","Final").replace("_", " ")

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

        home_name = m["homeTeam"].get("name") or m["homeTeam"].get("shortName") or "TBD"
        away_name = m["awayTeam"].get("name") or m["awayTeam"].get("shortName") or "TBD"
        home_owner = get_owner(home_name) if home_name != "TBD" else "?"
        away_owner = get_owner(away_name) if away_name != "TBD" else "?"
        group_raw = m.get("group") or m.get("stage") or ""
        group = group_raw.replace("GROUP_", "").replace("ROUND_OF_32","R32").replace("LAST_32","R32").replace("LAST_16","R16").replace("QUARTER_FINALS","QF").replace("SEMI_FINALS","SF").replace("FINAL","F").replace("_", " ").strip()
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
STAGE_ORDER = ["ROUND_OF_32", "LAST_32", "LAST_16", "QUARTER_FINALS", "SEMI_FINALS", "FINAL"]
STAGE_LABELS = {
    "ROUND_OF_32": "R32",
    "LAST_32": "R32",   # football-data.org uses LAST_32 for 2026 WC
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
        "England":"Silk","USA":"Silk","United States":"Silk","Algeria":"Silk","Qatar":"Silk",
        "Portugal":"Same","Colombia":"Same","Paraguay":"Same","Cape Verde":"Same",
        "Argentina":"Poncho Man","Morocco":"Poncho Man","Turkey":"Poncho Man","South Africa":"Poncho Man",
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
        # Normalise name — API uses "United States", we store "USA" etc.
        display_team = get_display_name(team)
        owner = OWNER_MAP.get(team) or OWNER_MAP.get(display_team)
        if not owner:
            continue  # skip teams not in sweepstake
        team = display_team  # store under normalised name

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

def fetch_h2h_odds():
    """
    Fetch head-to-head match odds for upcoming WC fixtures from AU bookmakers.
    Returns dict keyed by normalised team pair: { "TeamA_vs_TeamB": { home, away, home_price, draw_price, away_price, source } }
    """
    if not ODDS_API_KEY:
        return {}
    try:
        resp = requests.get(
            "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds/",
            params={
                "apiKey": ODDS_API_KEY,
                "regions": "au",
                "markets": "h2h",
                "oddsFormat": "decimal",
                "daysFrom": 7
            },
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        print(f"  H2H odds: {len(data)} matches, {resp.headers.get('x-requests-remaining')} requests remaining")

        h2h = {}
        for event in data:
            home_raw = event['home_team']
            away_raw = event['away_team']
            home = get_display_name(home_raw)
            away = get_display_name(away_raw)

            # Get best price per outcome across all AU bookmakers
            best = {}
            for bm in event.get('bookmakers', []):
                bm_name = bm['title']
                for market in bm.get('markets', []):
                    if market['key'] == 'h2h':
                        for o in market['outcomes']:
                            name = o['name']
                            price = o['price']
                            # Normalise team name in outcome
                            norm_name = get_display_name(name) if name != 'Draw' else 'Draw'
                            if norm_name not in best or price > best[norm_name]['price']:
                                best[norm_name] = {'price': price, 'bookmaker': bm_name}

            # Store under normalised key
            key = f"{home}_vs_{away}"
            h2h[key] = {
                'home': home,
                'away': away,
                'home_price': best.get(home, best.get(home_raw, {})).get('price'),
                'home_source': best.get(home, best.get(home_raw, {})).get('bookmaker'),
                'draw_price': best.get('Draw', {}).get('price'),
                'draw_source': best.get('Draw', {}).get('bookmaker'),
                'away_price': best.get(away, best.get(away_raw, {})).get('price'),
                'away_source': best.get(away, best.get(away_raw, {})).get('bookmaker'),
            }
            # Also store reverse key for lookup flexibility
            h2h[f"{away}_vs_{home}"] = h2h[key]

        return h2h
    except Exception as e:
        print(f"  H2H odds fetch failed: {e}")
        return {}


def attach_h2h_to_knockout(knockout_data, h2h_odds):
    """Match h2h odds to knockout bracket matches and attach prices."""
    if not h2h_odds:
        return knockout_data
    
    attached = 0
    for stage in knockout_data:
        for match in stage.get('matches', []):
            home = match.get('home')
            away = match.get('away')
            if not home or not away:
                continue
            
            # Try both orderings
            key1 = f"{home}_vs_{away}"
            key2 = f"{away}_vs_{home}"
            h2h = h2h_odds.get(key1) or h2h_odds.get(key2)
            
            if h2h:
                # Ensure prices are from home team's perspective
                if h2h_odds.get(key1):
                    match['h2h_home_price'] = h2h['home_price']
                    match['h2h_draw_price'] = h2h['draw_price']
                    match['h2h_away_price'] = h2h['away_price']
                    match['h2h_source'] = h2h.get('home_source', 'Betfair')
                else:
                    # reverse — swap home/away prices
                    match['h2h_home_price'] = h2h['away_price']
                    match['h2h_draw_price'] = h2h['draw_price']
                    match['h2h_away_price'] = h2h['home_price']
                    match['h2h_source'] = h2h.get('away_source', 'Betfair')
                attached += 1
            else:
                # Clear stale h2h data for finished matches
                match.pop('h2h_home_price', None)
                match.pop('h2h_draw_price', None)
                match.pop('h2h_away_price', None)
                match.pop('h2h_source', None)
    
    print(f"  H2H odds attached to {attached} knockout matches")
    return knockout_data


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
    # Recalculate win_pct from current odds table — eliminates stale data
    # A participant is eliminated if NONE of their teams appear in the odds
    current_odds_by_team = {o["team"]: o["now_decimal"] for o in existing.get("odds", [])}
    participants_map = existing.get("participants", {})

    for s in merged_standings:
        owner_teams = participants_map.get(s["name"], {}).get("teams", [])
        alive_teams = [t for t in owner_teams if t in current_odds_by_team]

        if alive_teams:
            # Sum of (1/odds) for all alive teams = combined win probability
            combined_pct = sum(1.0 / current_odds_by_team[t] * 100 for t in alive_teams)
            s["win_pct"] = round(combined_pct, 2)
            s["eliminated"] = False
        else:
            s["win_pct"] = 0.0
            s["eliminated"] = True

    # Re-sort: alive participants by win_pct first, eliminated last
    merged_standings.sort(key=lambda x: (x.get("eliminated", False), -x["win_pct"]))
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

    # Fetch and update AU outright odds
    best_odds = fetch_au_odds()
    if best_odds:
        existing = update_odds(existing, best_odds, {})

    # Fetch h2h match odds for knockout fixtures
    h2h_odds = fetch_h2h_odds()
    if h2h_odds and new_knockout:
        new_knockout = attach_h2h_to_knockout(new_knockout, h2h_odds)
    
    # Also attach to upcoming_fixtures
    if h2h_odds:
        for f in new_upcoming:
            home = f.get('home')
            away = f.get('away')
            if not home or not away:
                continue
            key1 = f"{home}_vs_{away}"
            key2 = f"{away}_vs_{home}"
            h2h = h2h_odds.get(key1) or h2h_odds.get(key2)
            if h2h:
                if h2h_odds.get(key1):
                    f['h2h_home_price'] = h2h['home_price']
                    f['h2h_draw_price'] = h2h['draw_price']
                    f['h2h_away_price'] = h2h['away_price']
                else:
                    f['h2h_home_price'] = h2h['away_price']
                    f['h2h_draw_price'] = h2h['draw_price']
                    f['h2h_away_price'] = h2h['home_price']

    # Write back
    existing["standings"] = merged_standings
    existing["recent_results"] = new_results
    existing["upcoming_fixtures"] = new_upcoming
    existing["knockout"] = new_knockout

    # Write via GitHub API (avoids git merge conflicts from concurrent runs)
    github_token = os.environ.get("GITHUB_TOKEN", "")
    if github_token:
        try:
            import base64
            # Get current file SHA first
            repo = os.environ.get("GITHUB_REPOSITORY", "")
            api_url = f"https://api.github.com/repos/{repo}/contents/data/data.json"
            headers = {
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github.v3+json"
            }
            get_resp = requests.get(api_url, headers=headers, timeout=15)
            sha = get_resp.json().get("sha", "")
            new_content = json.dumps(existing, indent=2, ensure_ascii=False)
            encoded = base64.b64encode(new_content.encode()).decode()
            put_resp = requests.put(api_url, headers=headers, json={
                "message": f"chore: scores + odds {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
                "content": encoded,
                "sha": sha
            }, timeout=15)
            if put_resp.status_code in (200, 201):
                print(f"  data.json written via GitHub API ✓")
            else:
                raise Exception(f"API write failed: {put_resp.status_code} {put_resp.text[:100]}")
        except Exception as e:
            print(f"  GitHub API write failed ({e}), falling back to local write")
            with open(DATA_FILE, "w") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
    else:
        # Local run fallback
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
