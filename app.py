#!/usr/bin/env python3
"""
IPL 2026 Fantasy Points Calculator

Uses the ESPN Cricinfo API to fetch scorecard data for an IPL 2026 match and
calculates fantasy points for every player based on batting, bowling,
and fielding contributions.

Usage:
    streamlit run app.py
"""

import re
import html
import requests
import streamlit as st
import pandas as pd
from collections import defaultdict

# ── API Configuration ────────────────────────────────────────────────

SERIES_ID = "1510719"
SCOREBOARD_URL = (
    "https://site.web.api.espn.com/apis/site/v2/sports/cricket/8048/scoreboard"
    f"?lang=en&region=us&league={SERIES_ID}&limit=70&dates=2026"
)
SUMMARY_URL_TEMPLATE = (
    "https://site.web.api.espn.com/apis/site/v2/sports/cricket/8048/summary"
    "?event={event_id}"
)
HEADERS = {"User-Agent": "Mozilla/5.0"}

# Bypass any system/env proxy so ESPN API is reached directly
_SESSION = requests.Session()
_SESSION.trust_env = False
_SESSION.headers.update(HEADERS)

# ── Fantasy Point Values ──────────────────────────────────────────────

BAT_RUN = 1
BAT_BOUNDARY_BONUS = 1          # per 4 or 6
BAT_SCORE_30 = 4
BAT_SCORE_50 = 8
BAT_SCORE_100 = 12
BAT_DUCK = -4

BOWL_DOT = 1
BOWL_WICKET = 20
BOWL_MAIDEN = 15
BOWL_BOWLED_LBW = 8
BOWL_3W = 4
BOWL_4W = 8
BOWL_5W = 12
BOWL_ECO_LT6 = 4               # economy < 6 (min 2 overs)
BOWL_ECO_LT7 = 2               # economy >= 6 and < 7 (min 2 overs)

FIELD_CATCH = 8
FIELD_STUMPING = 12
FIELD_RUNOUT_DIRECT = 12
FIELD_RUNOUT_PARTIAL = 6

# ── Fantasy Draft Teams ───────────────────────────────────────────────

FANTASY_TEAMS = {
    "VS": [
        "Karthik Sharma", "Prashant Veer", "Kuldeep Yadav", "Sai Sudharsan",
        "Mohammed Siraj", "Cameron Green", "Ajinkya Rahane", "Wanindu Hasaranga",
        "Suryakumar Yadav", "Robin Minz", "Prabhsimran Singh", "Yuzvendra Chahal",
        "Ravindra Jadeja", "Devdut Padikkal", "Krunal Pandya", "Aniket Verma",
    ],
    "Sakthi": [
        "Matt Henry", "KL Rahul", "Nitish Rana", "Jason Holder",
        "Glenn Phillips", "Finn Allen", "Nicholas Pooran", "Aiden Markram",
        "Tilak Varma", "Jasprit Bumrah", "Arshdeep Singh", "Riyan Parag",
        "Nandre Burger", "Rajat Patidar", "Phil Salt", "Zeeshan Ansari",
    ],
    "Kama/Bulb": [
        "Ruturaj Gaikwad", "Shivam Dube", "Axar Patel", "Vipraj Nigam",
        "Jos Buttler", "Rahul Tewatia", "Vaibhav Arora", "Avesh Khan",
        "Corbin Bosch", "Trent Boult", "Shasank Singh", "Yashasvi Jaiswal",
        "Jofra Archer", "Venkatesh Iyer", "Bhuvneshwar Kumar", "Liam Livingstone",
    ],
    "Sakhi": [
        "Dewald Brevis", "Sanju Samson", "Lungi Ngidi", "Rashid Khan",
        "Sai Kishore", "Rinku Singh", "Angkrish Raghuvanshi", "Ayush Badoni",
        "Will Jacks", "Priyansh Arya", "Cooper Connolly", "Donovan Ferreira",
        "Tim David", "Suyash Sharma", "Heinrich Klaasen", "Ishan Kishan",
    ],
    "Abi": [
        "Noor Ahmed", "Khaleel Ahmed", "David Miller", "Washington Sundar",
        "Tim Seifert", "Varun Chakravarthy", "Shahbaz Ahamad", "Mohammed Shami",
        "Rohit Sharma", "Ryan Rickelton", "Harpreet Brar", "Dhruv Jurel",
        "Ravi Bishnoi", "Virat Kohli", "Jacob Bethell", "Nitish Kumar Reddy",
    ],
    "Vignesh": [
        "MS Dhoni", "Akeal Hossain", "Tristan Stubbs", "Prasidh Krishna",
        "Matheesha Pathirana", "Rishabh Pant", "Mitchell Marsh", "Hardik Pandya",
        "Deepak Chahar", "Marco Jansen", "Marcus Stoinis", "Shimron Hetmyer",
        "Sandeep Sharma", "Romario Shepherd", "Abhishek Sharma", "Travis Head",
    ],
    "Kums": [
        "Jamie Overton", "Ayush Mathre", "Abishek Porel", "Auqib Nabi",
        "Shubman Gill", "Sunil Narine", "Ramandeep Singh", "Digvesh Rathi",
        "Quinton De Kock", "Shardul Thakur", "Shreyas Iyer", "Vaibhav Sooryavanshi",
        "Jitesh Sharma", "Josh Hazlewood", "Harshal Patel", "Jaydev Unadkat",
    ],
}

BOWLERS = {
    "Noor Ahmed", "Mitchell Starc", "Arshad Khan", "Varun Chakravarthy",
    "Mayank Yadav", "Mitchell Santner", "Arshdeep Singh", "Jofra Archer",
    "Josh Hazlewood", "Shivam Mavi", "Khaleel Ahmed", "T Natarajan",
    "Kagiso Rabada", "Navdeep Saini", "Avesh Khan", "Trent Boult",
    "Yuzvendra Chahal", "Tushar Deshpande", "Bhuvneshwar Kumar",
    "Brydon Carse", "Anshul Kamboj", "Mukesh Kumar", "Mohammed Siraj",
    "Umran Malik", "Mohsin Khan", "Jasprit Bumrah", "Vyshak Vijaykumar",
    "Sandeep Sharma", "Rasikh Salam", "Pat Cummins", "Matt Henry",
    "Dushmantha Chameera", "Prasidh Krishna", "Matheesha Pathirana",
    "Murugan Siddharth", "Deepak Chahar", "Yash Thakur", "Kwena Maphaka",
    "Suyash Sharma", "Jaydev Unadkat", "Spencer Johnson", "Kuldeep Yadav",
    "Ishant Sharma", "Vaibhav Arora", "Digvesh Rathi", "Ashwani Kumar",
    "Xavier Bartlett", "Nandre Burger", "Nuwan Thushara", "Eshan Malinga",
    "Rahul Chahar", "Auqib Nabi", "Rashid Khan", "Kartik Tyagi",
    "Mohammed Shami", "Mayank Markande", "Lockie Ferguson", "Ravi Bishnoi",
    "Jacob Duffy", "Zeeshan Ansari", "Kyle Jamieson", "Sai Kishore",
    "Anrich Nortje", "Shardul Thakur", "Ben Dwarshuis", "Adam Milne",
    "Lungi Ngidi", "Wanindu Hasaranga", "Allah Ghazanfar", "Pravin Dubey",
    "Kuldeep Sen", "Vignesh Puthur",
}


# ── Utilities ─────────────────────────────────────────────────────────

def ordinal(n):
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def parse_overs_to_float(overs_str):
    """Convert overs string like '3.4' to a float (3.4, not 3.666)."""
    overs_str = str(overs_str).strip()
    if "." in overs_str:
        whole, part = overs_str.split(".")
        return int(whole) + int(part) / 10
    return float(overs_str)


# ── Name Resolution ──────────────────────────────────────────────────

class NameResolver:
    """Maps short/fielding names (used in dismissal text) to canonical display names."""

    def __init__(self):
        self.display_names = set()
        self.fielding_to_display = {}
        self.last_name_index = {}

    def register(self, display_name, fielding_name=None):
        self.display_names.add(display_name)
        if fielding_name and fielding_name != display_name:
            self.fielding_to_display[fielding_name] = display_name
        last = display_name.split()[-1].lower()
        self.last_name_index.setdefault(last, []).append(display_name)

    def resolve(self, text_name):
        name = text_name.strip()
        if not name:
            return name
        if name in self.display_names:
            return name
        if name in self.fielding_to_display:
            return self.fielding_to_display[name]
        last = name.split()[-1].lower()
        candidates = self.last_name_index.get(last, [])
        if len(candidates) == 1:
            return candidates[0]
        for cand in candidates:
            if name.lower() in cand.lower() or cand.lower() in name.lower():
                return cand
        return name


# ── Dismissal Parsing ─────────────────────────────────────────────────

def parse_dismissal(text, resolver):
    """
    Parse a dismissal string and return a dict with:
      type: 'caught' | 'bowled' | 'lbw' | 'stumped' | 'run_out' |
            'caught_and_bowled' | 'hit_wicket' | 'not_out' | 'retired' | 'other'
      bowler: str | None
      fielders: [(name, role)]
      is_sub_fielder: bool
    """
    text = text.strip()
    result = {
        "type": "other",
        "bowler": None,
        "fielders": [],
        "is_sub_fielder": False,
    }

    if text == "not out" or text == "":
        result["type"] = "not_out"
        return result

    if "retired" in text.lower():
        result["type"] = "retired"
        return result

    m = re.match(r"c\s*&\s*b\s+(.+)", text)
    if m:
        bowler = resolver.resolve(m.group(1).strip())
        result["type"] = "caught_and_bowled"
        result["bowler"] = bowler
        result["fielders"] = [(bowler, "catch")]
        return result

    m = re.match(r"c\s+sub\s*\((.+?)\)\s*b\s+(.+)", text, re.IGNORECASE)
    if m:
        result["type"] = "caught"
        result["bowler"] = resolver.resolve(m.group(2).strip())
        result["is_sub_fielder"] = True
        return result

    m = re.match(r"st\s+sub\s*\((.+?)\)\s*b\s+(.+)", text, re.IGNORECASE)
    if m:
        result["type"] = "stumped"
        result["bowler"] = resolver.resolve(m.group(2).strip())
        result["is_sub_fielder"] = True
        return result

    m = re.match(r"c\s+(.+?)\s+b\s+(.+)", text)
    if m:
        fielder = resolver.resolve(m.group(1).strip())
        bowler = resolver.resolve(m.group(2).strip())
        result["type"] = "caught"
        result["bowler"] = bowler
        result["fielders"] = [(fielder, "catch")]
        return result

    m = re.match(r"st\s+(.+?)\s+b\s+(.+)", text)
    if m:
        fielder = resolver.resolve(m.group(1).strip())
        bowler = resolver.resolve(m.group(2).strip())
        result["type"] = "stumped"
        result["bowler"] = bowler
        result["fielders"] = [(fielder, "stumping")]
        return result

    m = re.match(r"run\s+out\s*\((.+?)\)", text, re.IGNORECASE)
    if m:
        names_str = m.group(1).strip()
        if "sub" in names_str.lower():
            result["type"] = "run_out"
            result["is_sub_fielder"] = True
            return result
        names = [n.strip() for n in re.split(r"[/]", names_str) if n.strip()]
        result["type"] = "run_out"
        if len(names) == 1:
            result["fielders"] = [(resolver.resolve(names[0]), "runout_direct")]
        else:
            result["fielders"] = [
                (resolver.resolve(n), "runout_partial") for n in names
            ]
        return result

    m = re.match(r"^b\s+(.+)", text)
    if m:
        result["type"] = "bowled"
        result["bowler"] = resolver.resolve(m.group(1).strip())
        return result

    m = re.match(r"lbw\s+b\s+(.+)", text, re.IGNORECASE)
    if m:
        result["type"] = "lbw"
        result["bowler"] = resolver.resolve(m.group(1).strip())
        return result

    m = re.match(r"hit\s+wicket\s+b\s+(.+)", text, re.IGNORECASE)
    if m:
        result["type"] = "hit_wicket"
        result["bowler"] = resolver.resolve(m.group(1).strip())
        return result

    return result


# ── ESPN API Data Fetching ────────────────────────────────────────────

def fetch_schedule():
    """Fetch all IPL 2026 match events from the ESPN API.

    Returns a list of dicts:
        {match_number, event_id, teams, team_abbr, state, status_detail}
    """
    resp = _SESSION.get(SCOREBOARD_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if "events" not in data:
        raise ValueError(f"Unexpected API response: {data}")

    matches = []
    for i, event in enumerate(data.get("events", []), 1):
        if not event.get("competitions"):
            continue
        comp = event["competitions"][0]
        status_type = comp["status"]["type"]

        teams = []
        team_abbr = {}
        for c in comp["competitors"]:
            tname = c["team"]["displayName"]
            teams.append(tname)
            team_abbr[tname] = c["team"]["abbreviation"]

        matches.append({
            "match_number": i,
            "event_id": event["id"],
            "teams": teams,
            "team_abbr": team_abbr,
            "state": status_type.get("state", ""),
            "status_detail": status_type.get("detail", ""),
        })

    return matches


def find_match_by_number(match_number):
    """Find the match dict for a given 1-indexed match number."""
    matches = cached_schedule()
    if 1 <= match_number <= len(matches):
        return matches[match_number - 1]
    return None


def find_current_or_latest_match():
    """Return the live match if one is ongoing, otherwise the latest completed match."""
    matches = cached_schedule()
    live = [m for m in matches if m["state"] == "in"]
    if live:
        return live[0]
    completed = [m for m in matches if m["state"] == "post"]
    return completed[-1] if completed else None


# ── Scorecard Parsing ─────────────────────────────────────────────────

def _extract_player_stats(player, period):
    """Extract all stats for a player in a given innings period."""
    for ls_period in player.get("linescores", []):
        if ls_period.get("period") != period:
            continue
        inner_ls = ls_period.get("linescores", [])
        if not inner_ls:
            return {}

        stats = {}
        for cat in inner_ls[0].get("statistics", {}).get("categories", []):
            for s in cat.get("stats", []):
                name = s["name"]
                val = s.get("value")
                dv = s.get("displayValue", "")

                if name == "overs":
                    stats[name] = dv if dv and dv != "-" else "0"
                    continue

                if isinstance(val, (int, float)):
                    stats[name] = val
                elif isinstance(val, str):
                    if val in ("", "-"):
                        stats[name] = 0
                    else:
                        try:
                            stats[name] = int(val)
                        except ValueError:
                            try:
                                stats[name] = float(val)
                            except ValueError:
                                stats[name] = val
                elif val is None:
                    if dv in ("", "-"):
                        stats[name] = 0
                    else:
                        try:
                            stats[name] = int(dv)
                        except ValueError:
                            try:
                                stats[name] = float(dv)
                            except ValueError:
                                stats[name] = dv
                else:
                    stats[name] = val
        return stats
    return {}


def parse_scorecard(event_id):
    """Fetch and parse the full scorecard from the ESPN summary API.

    Returns:
        match_info  – dict with teams, team_abbr, result, event_id
        innings_list – list of innings dicts (batting, bowling, dnb)
        resolver     – NameResolver for mapping short names
    """
    url = SUMMARY_URL_TEMPLATE.format(event_id=event_id)
    resp = _SESSION.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    header = data["header"]
    comp = header["competitions"][0]
    status = comp["status"]["type"]

    teams = []
    team_abbr = {}
    for c in comp["competitors"]:
        tname = c["team"]["displayName"]
        teams.append(tname)
        team_abbr[tname] = c["team"]["abbreviation"]

    result_text = ""
    status_full = comp.get("status", {})
    if status.get("state") == "post":
        result_text = (
            status_full.get("summary", "")
            or status.get("detail", "")
        )

    match_info = {
        "teams": teams,
        "team_abbr": team_abbr,
        "result": result_text,
        "event_id": event_id,
    }

    # ── Build name resolver from rosters ──────────────────────────
    resolver = NameResolver()
    rosters = data.get("rosters", [])
    team_roster_map = {}
    for roster_entry in rosters:
        tname = roster_entry["team"]["displayName"]
        players = roster_entry.get("roster", [])
        team_roster_map[tname] = players
        for p in players:
            dn = p["athlete"]["displayName"]
            fn = p["athlete"].get("fieldingName", "")
            resolver.register(dn, fn or None)

    # ── Determine batting team per period ─────────────────────────
    batting_team_by_period = {}
    for c in comp["competitors"]:
        tname = c["team"]["displayName"]
        for ls in c.get("linescores", []):
            if ls.get("isBatting"):
                batting_team_by_period[ls["period"]] = tname

    # ── Collect dismissal text from wicket data ───────────────────
    dismissal_text_map = {}  # {period: {batter_name: shortText}}

    for c in comp["competitors"]:
        for ls in c.get("linescores", []):
            if not ls.get("isBatting"):
                continue
            period = ls["period"]

            wicket_by_num = {}
            overs_sets = ls.get("statistics", {}).get("overs", [])
            for overs_set in (overs_sets if isinstance(overs_sets, list) else []):
                if not isinstance(overs_set, list):
                    continue
                for over_data in overs_set:
                    for w in over_data.get("wicket", []):
                        wnum = w.get("number", 0)
                        short_text = html.unescape(w.get("shortText", "")).strip()
                        short_text = short_text.replace("\u2020", "")
                        wicket_by_num[wnum] = short_text

            fow_by_num = {}
            for f in ls.get("fow", []):
                wnum = f.get("wicketNumber", 0)
                batter = f.get("athlete", {}).get("displayName", "")
                fow_by_num[wnum] = batter

            dtm = {}
            for wnum, batter_name in fow_by_num.items():
                if wnum in wicket_by_num:
                    dtm[batter_name] = wicket_by_num[wnum]
            dismissal_text_map[period] = dtm

    # ── Build innings list ────────────────────────────────────────
    innings_list = []
    for period in sorted(batting_team_by_period.keys()):
        if period > 2:
            break

        batting_team = batting_team_by_period[period]
        bowling_team = next((t for t in teams if t != batting_team), None)

        batting = []
        for player in team_roster_map.get(batting_team, []):
            stats = _extract_player_stats(player, period)
            if not stats or not stats.get("batted"):
                continue

            name = player["athlete"]["displayName"]
            d_text = dismissal_text_map.get(period, {}).get(name, "not out")

            batting.append({
                "name": name,
                "runs": int(stats.get("runs", 0)),
                "balls": int(stats.get("ballsFaced", 0)),
                "fours": int(stats.get("fours", 0)),
                "sixes": int(stats.get("sixes", 0)),
                "dismissal_text": d_text,
                "position": int(stats.get("battingPosition", 0)),
            })

        batting.sort(key=lambda x: x["position"])

        bowling = []
        if bowling_team:
            for player in team_roster_map.get(bowling_team, []):
                stats = _extract_player_stats(player, period)
                if not stats or not stats.get("inningsBowled"):
                    continue

                name = player["athlete"]["displayName"]
                bowling.append({
                    "name": name,
                    "overs": str(stats.get("overs", "0")),
                    "maidens": int(stats.get("maidens", 0)),
                    "runs": int(stats.get("conceded", 0)),
                    "wickets": int(stats.get("wickets", 0)),
                    "dots": int(stats.get("dots", 0)),
                    "economy": float(stats.get("economyRate", 0)),
                })

        innings_list.append({
            "team": batting_team,
            "batting": batting,
            "bowling": bowling,
            "dnb": [],
        })

    return match_info, innings_list, resolver


# ── Fantasy Points Calculation ────────────────────────────────────────

def calculate_fantasy_points(innings_list, resolver):
    """
    Calculate fantasy points for every player across both innings.

    Returns a dict:  name -> {team, bat_pts, bowl_pts, field_pts, total,
                               batting_detail, bowling_detail, fielding_detail}
    """
    players = defaultdict(lambda: {
        "team": "",
        "bat_pts": 0,
        "bowl_pts": 0,
        "field_pts": 0,
        "total": 0,
        "batting_detail": "",
        "bowling_detail": "",
        "fielding_detail": "",
    })

    for innings in innings_list:
        team = innings["team"]

        # ── Batting points ────────────────────────────────────
        for batter in innings["batting"]:
            name = batter["name"]
            players[name]["team"] = team
            runs = batter["runs"]
            fours = batter["fours"]
            sixes = batter["sixes"]
            pos = batter["position"]
            dismissal = parse_dismissal(batter["dismissal_text"], resolver)

            pts = 0
            details = []

            pts += runs * BAT_RUN
            if runs > 0:
                details.append(f"{runs}r")

            boundary_bonus = (fours + sixes) * BAT_BOUNDARY_BONUS
            pts += boundary_bonus
            if boundary_bonus:
                details.append(f"{fours}×4 {sixes}×6")

            if runs >= 100:
                pts += BAT_SCORE_100
                details.append("100+ bonus")
            elif runs >= 50:
                pts += BAT_SCORE_50
                details.append("50+ bonus")
            elif runs >= 30:
                pts += BAT_SCORE_30
                details.append("30+ bonus")

            is_out = dismissal["type"] not in ("not_out", "retired")
            if runs == 0 and is_out and name not in BOWLERS:
                pts += BAT_DUCK
                details.append("duck")

            players[name]["bat_pts"] += pts
            players[name]["batting_detail"] = ", ".join(details)

        # ── Bowling points ────────────────────────────────────
        for bowler in innings["bowling"]:
            name = bowler["name"]
            if not players[name]["team"]:
                opposing = [
                    inn["team"] for inn in innings_list if inn["team"] != team
                ]
                players[name]["team"] = opposing[0] if opposing else ""

            pts = 0
            details = []

            wickets = bowler["wickets"]
            maidens = bowler["maidens"]
            dots = bowler["dots"]
            economy = bowler["economy"]
            total_overs = parse_overs_to_float(bowler["overs"])

            if dots > 0:
                pts += dots * BOWL_DOT
                details.append(f"{dots}dot")

            if wickets > 0:
                pts += wickets * BOWL_WICKET
                details.append(f"{wickets}w")

            if maidens > 0:
                pts += maidens * BOWL_MAIDEN
                details.append(f"{maidens}maiden")

            if wickets >= 5:
                pts += BOWL_5W
                details.append("5w bonus")
            elif wickets >= 4:
                pts += BOWL_4W
                details.append("4w bonus")
            elif wickets >= 3:
                pts += BOWL_3W
                details.append("3w bonus")

            if total_overs >= 2:
                if economy < 6:
                    pts += BOWL_ECO_LT6
                    details.append(f"eco {economy:.1f}")
                elif economy < 7:
                    pts += BOWL_ECO_LT7
                    details.append(f"eco {economy:.1f}")

            players[name]["bowl_pts"] += pts
            players[name]["bowling_detail"] = ", ".join(details)

        # ── Bowled / LBW bonus → attributed to the bowler ─────
        for batter in innings["batting"]:
            dismissal = parse_dismissal(batter["dismissal_text"], resolver)
            if dismissal["type"] in ("bowled", "lbw") and dismissal["bowler"]:
                bowler_name = dismissal["bowler"]
                players[bowler_name]["bowl_pts"] += BOWL_BOWLED_LBW
                existing = players[bowler_name]["bowling_detail"]
                tag = "bowled" if dismissal["type"] == "bowled" else "lbw"
                players[bowler_name]["bowling_detail"] = (
                    f"{existing}, {tag} bonus" if existing else f"{tag} bonus"
                )

        # ── Fielding points ───────────────────────────────────
        for batter in innings["batting"]:
            dismissal = parse_dismissal(batter["dismissal_text"], resolver)
            if dismissal["is_sub_fielder"]:
                continue

            for fielder_name, role in dismissal["fielders"]:
                if not players[fielder_name]["team"]:
                    opposing = [
                        inn["team"]
                        for inn in innings_list
                        if inn["team"] != team
                    ]
                    players[fielder_name]["team"] = (
                        opposing[0] if opposing else ""
                    )

                if role == "catch":
                    players[fielder_name]["field_pts"] += FIELD_CATCH
                    existing = players[fielder_name]["fielding_detail"]
                    players[fielder_name]["fielding_detail"] = (
                        f"{existing}, catch" if existing else "catch"
                    )
                elif role == "stumping":
                    players[fielder_name]["field_pts"] += FIELD_STUMPING
                    existing = players[fielder_name]["fielding_detail"]
                    players[fielder_name]["fielding_detail"] = (
                        f"{existing}, stumping" if existing else "stumping"
                    )
                elif role == "runout_direct":
                    players[fielder_name]["field_pts"] += FIELD_RUNOUT_DIRECT
                    existing = players[fielder_name]["fielding_detail"]
                    players[fielder_name]["fielding_detail"] = (
                        f"{existing}, run out (direct)"
                        if existing
                        else "run out (direct)"
                    )
                elif role == "runout_partial":
                    players[fielder_name]["field_pts"] += FIELD_RUNOUT_PARTIAL
                    existing = players[fielder_name]["fielding_detail"]
                    players[fielder_name]["fielding_detail"] = (
                        f"{existing}, run out (partial)"
                        if existing
                        else "run out (partial)"
                    )

    for name, p in players.items():
        p["total"] = p["bat_pts"] + p["bowl_pts"] + p["field_pts"]

    return players


# ── Helpers for building DataFrames ───────────────────────────────────

def _build_team_df(players, innings_list, team):
    bat_stats = {}
    bowl_stats = {}
    for inn in innings_list:
        for b in inn["batting"]:
            bat_stats[b["name"]] = b
        for b in inn["bowling"]:
            bowl_stats[b["name"]] = b

    rows = []
    for name, data in sorted(
        players.items(), key=lambda x: x[1]["total"], reverse=True
    ):
        if data["team"] != team:
            continue

        bat = bat_stats.get(name)
        bowl = bowl_stats.get(name)
        parts = []
        if bat:
            s = f"{bat['runs']}({bat['balls']})"
            if bat["fours"] or bat["sixes"]:
                s += f"  {bat['fours']}×4 {bat['sixes']}×6"
            parts.append(s)
        if bowl and (bowl["wickets"] or bowl["overs"] != "0"):
            parts.append(f"{bowl['wickets']}/{bowl['runs']} ({bowl['overs']}ov)")

        rows.append({
            "Player": name,
            "Stats": "  |  ".join(parts) if parts else "-",
            "Bat": data["bat_pts"],
            "Bowl": data["bowl_pts"],
            "Field": data["field_pts"],
            "Total": data["total"],
        })

    return pd.DataFrame(rows)


def _build_leaderboard_df(players, match_info):
    abbr = match_info.get("team_abbr", {})
    rows = []
    for rank, (name, data) in enumerate(
        sorted(players.items(), key=lambda x: x[1]["total"], reverse=True), 1
    ):
        rows.append({
            "#": rank,
            "Player": name,
            "Team": abbr.get(data["team"], data["team"][:3].upper()),
            "Bat": data["bat_pts"],
            "Bowl": data["bowl_pts"],
            "Field": data["field_pts"],
            "Total": data["total"],
        })
    return pd.DataFrame(rows)


# ── Fantasy Team Helpers ───────────────────────────────────────────────

def _normalize_name(name):
    """Lowercase, collapse dots and extra whitespace for fuzzy matching."""
    return re.sub(r"[.\s]+", " ", name).strip().lower()


def _find_espn_name(fantasy_name, players_dict):
    """Return the ESPN display name for a fantasy player, or None if not found.

    Matching order:
      1. Exact string match
      2. Normalized exact match (dots/extra spaces removed, lowercased)
      3. Prefix-compatible first name + exact last name
         e.g. 'Mohd.' → 'Mohammed' because 'mohammed'.startswith('mohd') is True
         but 'Abhishek' ≠ 'Ashok' because neither is a prefix of the other.
         Only fires when exactly one candidate qualifies.
    """
    if fantasy_name in players_dict:
        return fantasy_name

    norm = _normalize_name(fantasy_name)
    norm_map = {_normalize_name(n): n for n in players_dict}

    if norm in norm_map:
        return norm_map[norm]

    parts = norm.split()
    if len(parts) >= 2:
        first, last = parts[0], parts[-1]
        candidates = []
        for espn_name in players_dict:
            espn_parts = _normalize_name(espn_name).split()
            if len(espn_parts) < 2:
                continue
            if espn_parts[-1] != last:
                continue
            espn_first = espn_parts[0]
            # One first name must be a prefix of the other (handles abbreviations)
            if first.startswith(espn_first) or espn_first.startswith(first):
                candidates.append(espn_name)
        if len(candidates) == 1:
            return candidates[0]

    return None


def _build_fantasy_team_df(fantasy_players, players, innings_list):
    """Build a per-player points breakdown DataFrame for one fantasy team."""
    bat_stats = {}
    bowl_stats = {}
    for inn in innings_list:
        for b in inn["batting"]:
            bat_stats[b["name"]] = b
        for b in inn["bowling"]:
            bowl_stats[b["name"]] = b

    rows = []
    for fantasy_name in fantasy_players:
        espn_name = _find_espn_name(fantasy_name, players)
        if not espn_name:
            continue  # didn't play in this match
        data = players[espn_name]
        bat = bat_stats.get(espn_name)
        bowl = bowl_stats.get(espn_name)
        parts = []
        if bat:
            s = f"{bat['runs']}({bat['balls']})"
            if bat["fours"] or bat["sixes"]:
                s += f"  {bat['fours']}×4 {bat['sixes']}×6"
            parts.append(s)
        if bowl and (bowl["wickets"] or bowl["overs"] != "0"):
            parts.append(f"{bowl['wickets']}/{bowl['runs']} ({bowl['overs']}ov)")
        rows.append({
            "Player": espn_name,
            "Stats": "  |  ".join(parts) if parts else "—",
            "Bat": data["bat_pts"],
            "Bowl": data["bowl_pts"],
            "Field": data["field_pts"],
            "Total": data["total"],
        })

    return pd.DataFrame(rows).sort_values("Total", ascending=False)


# ── Streamlit UI ──────────────────────────────────────────────────────

@st.cache_data(ttl=30, show_spinner=False)
def cached_schedule():
    return fetch_schedule()


@st.cache_data(ttl=300, show_spinner="Fetching scorecard…")
def cached_scorecard(event_id, _live=False):
    return parse_scorecard(event_id)


def get_scorecard(event_id, is_live=False):
    """Wrapper that uses a short TTL for live matches."""
    if is_live:
        cached_scorecard.clear()
    return cached_scorecard(event_id, _live=is_live)


def main():
    st.set_page_config(page_title="IPL 2026 Fantasy Points", layout="wide")
    st.title("🏏 IPL 2026 Fantasy Points Calculator")

    with st.sidebar:
        st.header("Match Selection")
        use_auto = st.toggle("Auto (live or latest)", value=True)

        if use_auto:
            with st.spinner("Finding match…"):
                match = find_current_or_latest_match()
            if not match:
                st.error("No live or completed IPL 2026 matches found yet.")
                st.stop()
            label = "LIVE" if match["state"] == "in" else f"Match #{match['match_number']}"
            abbr0 = match["team_abbr"].get(match["teams"][0], "?")
            abbr1 = match["team_abbr"].get(match["teams"][1], "?")
            if match["state"] == "in":
                st.info(f"🔴 {label} – {abbr0} vs {abbr1}")
            else:
                st.success(f"{label} – {abbr0} vs {abbr1}")
            event_id = match["event_id"]
        else:
            match_number = st.number_input(
                "Match number", min_value=1, max_value=70, value=1, step=1
            )
            match = find_match_by_number(match_number)
            if not match:
                st.error(
                    f"Match #{match_number} not found in the schedule."
                )
                st.stop()
            if match["state"] == "pre":
                st.error(
                    f"Match #{match_number} has not started yet."
                )
                st.stop()
            event_id = match["event_id"]

        scorecard_url = (
            f"https://www.espncricinfo.com/series/ipl-2026-{SERIES_ID}"
            f"/{event_id}/full-scorecard"
        )
        st.caption(f"[Scorecard on ESPNcricinfo]({scorecard_url})")
        if st.button("Clear cache & reload"):
            st.cache_data.clear()
            st.rerun()

    is_live = match["state"] == "in"
    match_info, innings_list, resolver = get_scorecard(event_id, is_live=is_live)

    if not innings_list:
        st.error("Could not parse scorecard — no innings data available yet.")
        st.stop()

    if is_live:
        st.caption("🔴 Match in progress — points are provisional")

    players = calculate_fantasy_points(innings_list, resolver)

    if match_info.get("result"):
        st.markdown(f"**{match_info['result']}**")

    tab_fantasy, tab_match, tab_lb = st.tabs(["Fantasy Teams", "Match", "Leaderboard"])

    # ── Fantasy Teams tab ─────────────────────────────────────────────
    with tab_fantasy:
        # Rank teams by their combined total for this match
        team_totals = {}
        for team_name, roster in FANTASY_TEAMS.items():
            total = 0
            for fantasy_name in roster:
                espn_name = _find_espn_name(fantasy_name, players)
                if espn_name:
                    total += players[espn_name]["total"]
            team_totals[team_name] = total

        sorted_teams = sorted(team_totals.items(), key=lambda x: x[1], reverse=True)

        col_config = {
            "Total": st.column_config.NumberColumn(format="%d"),
            "Bat": st.column_config.NumberColumn(format="%d"),
            "Bowl": st.column_config.NumberColumn(format="%d"),
            "Field": st.column_config.NumberColumn(format="%d"),
        }

        for rank, (team_name, team_total) in enumerate(sorted_teams, 1):
            with st.expander(
                f"#{rank}  **{team_name}** — {team_total} pts", expanded=True
            ):
                df = _build_fantasy_team_df(
                    FANTASY_TEAMS[team_name], players, innings_list
                )
                st.dataframe(
                    df,
                    use_container_width=True,
                    hide_index=True,
                    column_config=col_config,
                )

    # ── Match tab (cricket teams) ─────────────────────────────────────
    with tab_match:
        match_teams = match_info.get("teams", [])
        for team in match_teams:
            df = _build_team_df(players, innings_list, team)
            st.subheader(team)
            if df.empty:
                st.info("No player data available.")
            else:
                st.dataframe(
                    df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Total": st.column_config.NumberColumn(format="%d"),
                        "Bat": st.column_config.NumberColumn(format="%d"),
                        "Bowl": st.column_config.NumberColumn(format="%d"),
                        "Field": st.column_config.NumberColumn(format="%d"),
                    },
                )

    # ── Leaderboard tab ───────────────────────────────────────────────
    with tab_lb:
        st.subheader("Fantasy Points Leaderboard")
        lb = _build_leaderboard_df(players, match_info)
        st.dataframe(
            lb,
            use_container_width=True,
            hide_index=True,
            column_config={
                "#": st.column_config.NumberColumn(format="%d", width="small"),
                "Total": st.column_config.NumberColumn(format="%d"),
                "Bat": st.column_config.NumberColumn(format="%d"),
                "Bowl": st.column_config.NumberColumn(format="%d"),
                "Field": st.column_config.NumberColumn(format="%d"),
            },
        )


if __name__ == "__main__":
    main()
