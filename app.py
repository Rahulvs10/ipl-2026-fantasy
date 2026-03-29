#!/usr/bin/env python3
"""
IPL 2026 Fantasy Points Calculator

Scrapes the Cricbuzz scorecard for a given IPL 2026 match number and
calculates fantasy points for every player based on batting, bowling,
and fielding contributions.

Usage:
    streamlit run app.py
"""

import re
import requests
import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
from collections import defaultdict

SERIES_MATCHES_URL = (
    "https://www.cricbuzz.com/cricket-series/9241/"
    "indian-premier-league-2026/matches"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
}

# ── Fantasy Point Values ──────────────────────────────────────────────

BAT_RUN = 1
BAT_BOUNDARY_BONUS = 1          # per 4 or 6
BAT_SCORE_30 = 4
BAT_SCORE_50 = 8
BAT_SCORE_100 = 12
BAT_DUCK = 0                   # bowlers excluded (batting pos >= 8)

BOWL_WICKET = 20
BOWL_MAIDEN = 15
BOWL_BOWLED_LBW = 8             # per dismissal that is bowled or lbw
BOWL_3W = 4
BOWL_4W = 8
BOWL_5W = 12
BOWL_HATTRICK = 15
BOWL_ECO_LT6 = 4               # economy < 6 (min 2 overs)
BOWL_ECO_LT7 = 2               # economy >= 6 and < 7 (min 2 overs)

FIELD_CATCH = 8
FIELD_STUMPING = 12
FIELD_RUNOUT_DIRECT = 12
FIELD_RUNOUT_PARTIAL = 6

DUCK_EXEMPT_POSITION = 8        # batting position >= this is exempt


# ── Utilities ─────────────────────────────────────────────────────────

def ordinal(n):
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def clean_name(raw):
    """Remove captain/keeper tags and extra whitespace from a player name."""
    name = re.sub(r"\s*\(.*?\)\s*", "", raw).strip()
    name = re.sub(r"\s+", " ", name)
    return name


def parse_overs_to_float(overs_str):
    """Convert overs string like '3.4' to a float for ball count."""
    overs_str = overs_str.strip()
    if "." in overs_str:
        whole, part = overs_str.split(".")
        return int(whole) + int(part) / 10
    return float(overs_str)


def overs_to_balls(overs_str):
    overs_str = overs_str.strip()
    if "." in overs_str:
        whole, part = overs_str.split(".")
        return int(whole) * 6 + int(part)
    return int(overs_str) * 6


# ── Name Resolution ──────────────────────────────────────────────────

class PlayerRegistry:
    """Maps variant names (from dismissal text) to canonical player names."""

    def __init__(self):
        self.canonical_names = {}   # clean_name -> clean_name (identity)
        self.last_name_index = {}   # last_name -> [clean_name, ...]

    def register(self, raw_name):
        name = clean_name(raw_name)
        if name and name not in self.canonical_names:
            self.canonical_names[name] = name
            last = name.split()[-1].lower()
            self.last_name_index.setdefault(last, []).append(name)
        return name

    def resolve(self, text_name):
        """Given a name from dismissal text, find the matching registered player."""
        name = text_name.strip()
        if name in self.canonical_names:
            return name

        last = name.split()[-1].lower()
        candidates = self.last_name_index.get(last, [])
        if len(candidates) == 1:
            return candidates[0]

        for cand in candidates:
            if name.lower() in cand.lower() or cand.lower() in name.lower():
                return cand

        return name


# ── Dismissal Parsing ─────────────────────────────────────────────────

def parse_dismissal(text, registry):
    """
    Parse a Cricbuzz dismissal string and return a dict with:
      type: 'caught' | 'bowled' | 'lbw' | 'stumped' | 'run_out' |
            'caught_and_bowled' | 'hit_wicket' | 'not_out' | 'retired' | 'other'
      bowler: str | None
      fielders: [(name, role)]   role = 'catch' | 'stumping' | 'runout_direct' | 'runout_partial'
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

    # caught and bowled: "c & b Player"
    m = re.match(r"c\s*&\s*b\s+(.+)", text)
    if m:
        bowler = registry.resolve(m.group(1).strip())
        result["type"] = "caught_and_bowled"
        result["bowler"] = bowler
        result["fielders"] = [(bowler, "catch")]
        return result

    # caught by sub: "c sub (Name) b Bowler" or "c †Name b Bowler"
    m = re.match(r"c\s+sub\s*\((.+?)\)\s*b\s+(.+)", text, re.IGNORECASE)
    if m:
        result["type"] = "caught"
        result["bowler"] = registry.resolve(m.group(2).strip())
        result["is_sub_fielder"] = True
        return result

    # stumped by sub
    m = re.match(r"st\s+sub\s*\((.+?)\)\s*b\s+(.+)", text, re.IGNORECASE)
    if m:
        result["type"] = "stumped"
        result["bowler"] = registry.resolve(m.group(2).strip())
        result["is_sub_fielder"] = True
        return result

    # regular caught: "c Fielder b Bowler"
    m = re.match(r"c\s+(.+?)\s+b\s+(.+)", text)
    if m:
        fielder = registry.resolve(m.group(1).strip())
        bowler = registry.resolve(m.group(2).strip())
        result["type"] = "caught"
        result["bowler"] = bowler
        result["fielders"] = [(fielder, "catch")]
        return result

    # stumped: "st Fielder b Bowler"
    m = re.match(r"st\s+(.+?)\s+b\s+(.+)", text)
    if m:
        fielder = registry.resolve(m.group(1).strip())
        bowler = registry.resolve(m.group(2).strip())
        result["type"] = "stumped"
        result["bowler"] = bowler
        result["fielders"] = [(fielder, "stumping")]
        return result

    # run out with multiple fielders: "run out (Name1/Name2)"
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
            result["fielders"] = [(registry.resolve(names[0]), "runout_direct")]
        else:
            result["fielders"] = [
                (registry.resolve(n), "runout_partial") for n in names
            ]
        return result

    # bowled: "b Bowler"
    m = re.match(r"^b\s+(.+)", text)
    if m:
        result["type"] = "bowled"
        result["bowler"] = registry.resolve(m.group(1).strip())
        return result

    # lbw: "lbw b Bowler"
    m = re.match(r"lbw\s+b\s+(.+)", text, re.IGNORECASE)
    if m:
        result["type"] = "lbw"
        result["bowler"] = registry.resolve(m.group(1).strip())
        return result

    # hit wicket: "hit wicket b Bowler"
    m = re.match(r"hit\s+wicket\s+b\s+(.+)", text, re.IGNORECASE)
    if m:
        result["type"] = "hit_wicket"
        result["bowler"] = registry.resolve(m.group(1).strip())
        return result

    return result


# ── Scorecard Scraping ────────────────────────────────────────────────

COMPLETED_RE = re.compile(r"\bwon\b|tied|no result|abandon", re.IGNORECASE)
MATCH_NUM_RE = re.compile(r"(\d+)(?:st|nd|rd|th)-match-indian-premier-league-2026")


def _fetch_match_links():
    """Return a list of (match_number, href, link_text) for all IPL 2026 matches."""
    resp = requests.get(SERIES_MATCHES_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    matches = []
    seen = set()
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "indian-premier-league-2026" not in href or "-match-" not in href:
            continue
        if href in seen:
            continue
        seen.add(href)

        m = MATCH_NUM_RE.search(href)
        if not m:
            continue
        num = int(m.group(1))
        text = link.get_text(strip=True)
        matches.append((num, href, text))

    return matches


def find_match_scorecard_url(match_number):
    """Find the scorecard URL for a specific IPL 2026 match number."""
    for num, href, _ in _fetch_match_links():
        if num == match_number:
            scorecard_url = href.replace(
                "/live-cricket-scores/", "/live-cricket-scorecard/"
            )
            if not scorecard_url.startswith("http"):
                scorecard_url = "https://www.cricbuzz.com" + scorecard_url
            return scorecard_url
    return None


def find_latest_completed_match():
    """Find the most recent completed IPL 2026 match. Returns (match_number, scorecard_url) or (None, None)."""
    matches = _fetch_match_links()
    completed = [
        (num, href) for num, href, text in matches if COMPLETED_RE.search(text)
    ]
    if not completed:
        return None, None

    completed.sort(key=lambda x: x[0], reverse=True)
    num, href = completed[0]
    scorecard_url = href.replace(
        "/live-cricket-scores/", "/live-cricket-scorecard/"
    )
    if not scorecard_url.startswith("http"):
        scorecard_url = "https://www.cricbuzz.com" + scorecard_url
    return num, scorecard_url


def parse_scorecard(url):
    """
    Fetch and parse the full scorecard from the given URL.

    Returns:
        match_info: dict with match title, teams, result
        innings_list: list of dicts, each with:
            team: str
            batting: [{name, runs, balls, fours, sixes, dismissal_text, position}]
            bowling: [{name, overs, maidens, runs, wickets, economy}]
            dnb: [name, ...]            (did not bat)
    """
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    # Find innings divs (pattern: scard-team-{id}-innings-{n})
    seen_ids = set()
    innings_divs = []
    team_headers = []

    for div in soup.find_all("div", id=re.compile(r"^scard-team-\d+-innings-\d+$")):
        div_id = div["id"]
        if div_id not in seen_ids:
            seen_ids.add(div_id)
            innings_divs.append(div)

    for div in soup.find_all("div", id=re.compile(r"^team-\d+-innings-\d+$")):
        div_id = div["id"]
        if div_id not in seen_ids:
            seen_ids.add(div_id)
            team_headers.append(div)

    # Extract team names and short codes from header child divs:
    # child[0] = short code (e.g. "SRH"), child[1] = full name, child[2] = score
    team_names = []
    team_short = []
    for hdr in team_headers:
        child_divs = [
            c for c in hdr.children
            if hasattr(c, "name") and c.name == "div"
        ]
        if len(child_divs) >= 2:
            team_short.append(child_divs[0].get_text(strip=True))
            team_names.append(child_divs[1].get_text(strip=True))
        else:
            text = hdr.get_text(strip=True)
            team_names.append(text)
            team_short.append(text[:3].upper())

    # Extract match result from page
    result_text = ""
    result_div = soup.find("div", string=re.compile(r"won by|Match tied|No result", re.IGNORECASE))
    if result_div:
        result_text = result_div.get_text(strip=True)
    else:
        for el in soup.find_all(string=re.compile(r"won by|Match tied|No result", re.IGNORECASE)):
            result_text = el.strip()
            break

    team_abbr = {}
    for i in range(min(len(team_names), len(team_short))):
        team_abbr[team_names[i]] = team_short[i]

    match_info = {
        "url": url,
        "result": result_text,
        "teams": team_names[:2] if len(team_names) >= 2 else [],
        "team_abbr": team_abbr,
    }

    registry = PlayerRegistry()
    innings_list = []

    # Only process the first 2 innings (skip Super Over if any)
    for idx, innings_div in enumerate(innings_divs[:2]):
        team = team_names[idx] if idx < len(team_names) else f"Team {idx + 1}"
        sections = innings_div.find_all("div", class_="mb-2", recursive=False)

        batting = []
        bowling = []
        dnb = []

        # Section 0: Batting
        if len(sections) > 0:
            batting = _parse_batting_section(sections[0], registry)

        # Section 1: Bowling
        if len(sections) > 1:
            bowling = _parse_bowling_section(sections[1], registry)

        innings_list.append({
            "team": team,
            "batting": batting,
            "bowling": bowling,
            "dnb": dnb,
        })

    return match_info, innings_list, registry


def _parse_batting_section(section, registry):
    """Parse all batting rows from a batting section div."""
    rows = []
    text_xs = section.find("div", class_="text-xs")
    if not text_xs:
        return rows

    position = 0
    for div in text_xs.children:
        if not hasattr(div, "find"):
            continue

        classes = " ".join(div.get("class", []))

        if "scorecard-bat-grid" in classes:
            link = div.find("a", href=re.compile(r"/profiles/"))
            if not link:
                continue

            raw_name = link.get_text(strip=True)
            name = registry.register(raw_name)
            position += 1

            # Get direct children (div/a elements) of the grid row
            children = [
                c for c in div.children
                if hasattr(c, "name") and c.name in ("div", "a")
            ]

            # child[0] = container with player name + dismissal
            # child[1..5] = runs, balls, fours, sixes, SR
            dismissal_text = ""
            if children:
                inner_div = children[0].find("div")
                if inner_div:
                    dismissal_text = inner_div.get_text(strip=True)

            stats = [c.get_text(strip=True) for c in children[1:6]]

            runs = int(stats[0]) if len(stats) > 0 and stats[0].isdigit() else 0
            balls = int(stats[1]) if len(stats) > 1 and stats[1].isdigit() else 0
            fours = int(stats[2]) if len(stats) > 2 and stats[2].isdigit() else 0
            sixes = int(stats[3]) if len(stats) > 3 and stats[3].isdigit() else 0

            rows.append({
                "name": name,
                "runs": runs,
                "balls": balls,
                "fours": fours,
                "sixes": sixes,
                "dismissal_text": dismissal_text,
                "position": position,
            })

        text = div.get_text(strip=True)
        if text.startswith("Did not Bat"):
            for a in div.find_all("a", href=re.compile(r"/profiles/")):
                registry.register(a.get_text(strip=True))

    return rows


def _parse_bowling_section(section, registry):
    """Parse all bowling rows from a bowling section div."""
    rows = []
    text_xs = section.find("div", class_="text-xs")
    container = text_xs if text_xs else section

    seen = set()
    for div in container.descendants:
        if not hasattr(div, "get"):
            continue
        classes = " ".join(div.get("class", []))
        if "scorecard-bowl-grid" not in classes:
            continue

        link = div.find("a", href=re.compile(r"/profiles/"))
        if not link:
            continue

        raw_name = link.get_text(strip=True)
        name = registry.register(raw_name)
        if name in seen:
            continue
        seen.add(name)

        children = [
            c for c in div.children
            if hasattr(c, "name") and c.name in ("div", "a")
        ]
        # children: [name_link], overs, maidens, runs, wickets, NB, WD, eco, highlights
        # But the first child is the <a> link, so stats start at index 1
        # Actually the <a> is a child, let me get all children including <a>
        all_children = [
            c for c in div.children
            if hasattr(c, "name") and c.name
        ]
        # Skip the first <a> (player name) and last <a> (highlights)
        stat_children = [
            c for c in all_children
            if c.name == "div"
        ]
        stats = [c.get_text(strip=True) for c in stat_children]

        overs = stats[0] if len(stats) > 0 else "0"
        maidens = int(stats[1]) if len(stats) > 1 and stats[1].isdigit() else 0
        runs_conceded = int(stats[2]) if len(stats) > 2 and stats[2].isdigit() else 0
        wickets = int(stats[3]) if len(stats) > 3 and stats[3].isdigit() else 0
        economy = 0.0
        # Economy might be at different positions depending on NB/WD visibility
        for s in reversed(stats):
            try:
                economy = float(s)
                break
            except ValueError:
                continue

        rows.append({
            "name": name,
            "overs": overs,
            "maidens": maidens,
            "runs": runs_conceded,
            "wickets": wickets,
            "economy": economy,
        })

    return rows


# ── Fantasy Points Calculation ────────────────────────────────────────

def calculate_fantasy_points(innings_list, registry):
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
            dismissal = parse_dismissal(batter["dismissal_text"], registry)

            pts = 0
            details = []

            # Runs
            pts += runs * BAT_RUN
            if runs > 0:
                details.append(f"{runs}r")

            # Boundary bonus (4s and 6s)
            boundary_bonus = (fours + sixes) * BAT_BOUNDARY_BONUS
            pts += boundary_bonus
            if boundary_bonus:
                details.append(f"{fours}×4 {sixes}×6")

            # Milestone bonus (highest applicable tier only)
            if runs >= 100:
                pts += BAT_SCORE_100
                details.append("100+ bonus")
            elif runs >= 50:
                pts += BAT_SCORE_50
                details.append("50+ bonus")
            elif runs >= 30:
                pts += BAT_SCORE_30
                details.append("30+ bonus")

            # Duck penalty (bowlers batting at pos >= 8 are exempt)
            is_out = dismissal["type"] not in ("not_out", "retired")
            if runs == 0 and is_out and pos < DUCK_EXEMPT_POSITION:
                pts += BAT_DUCK
                details.append("duck")

            players[name]["bat_pts"] += pts
            players[name]["batting_detail"] = ", ".join(details)

        # ── Bowling points ────────────────────────────────────
        for bowler in innings["bowling"]:
            name = bowler["name"]
            if not players[name]["team"]:
                opposing = [inn["team"] for inn in innings_list if inn["team"] != team]
                players[name]["team"] = opposing[0] if opposing else ""

            pts = 0
            details = []

            wickets = bowler["wickets"]
            maidens = bowler["maidens"]
            overs_str = bowler["overs"]
            economy = bowler["economy"]
            total_overs = parse_overs_to_float(overs_str)

            # Wickets
            if wickets > 0:
                pts += wickets * BOWL_WICKET
                details.append(f"{wickets}w")

            # Maidens
            if maidens > 0:
                pts += maidens * BOWL_MAIDEN
                details.append(f"{maidens}maiden")

            # Wicket milestone (highest applicable tier only)
            if wickets >= 5:
                pts += BOWL_5W
                details.append("5w bonus")
            elif wickets >= 4:
                pts += BOWL_4W
                details.append("4w bonus")
            elif wickets >= 3:
                pts += BOWL_3W
                details.append("3w bonus")

            # Economy bonus (minimum 2 overs)
            if total_overs >= 2:
                if economy < 6:
                    pts += BOWL_ECO_LT6
                    details.append(f"eco {economy:.1f}")
                elif economy < 7:
                    pts += BOWL_ECO_LT7
                    details.append(f"eco {economy:.1f}")

            players[name]["bowl_pts"] += pts
            players[name]["bowling_detail"] = ", ".join(details)

        # ── Bowled / LBW bonus → goes to the bowler ──────────
        for batter in innings["batting"]:
            dismissal = parse_dismissal(batter["dismissal_text"], registry)
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
            dismissal = parse_dismissal(batter["dismissal_text"], registry)
            if dismissal["is_sub_fielder"]:
                continue

            for fielder_name, role in dismissal["fielders"]:
                # Fielders belong to the bowling/fielding team
                if not players[fielder_name]["team"]:
                    opposing = [inn["team"] for inn in innings_list if inn["team"] != team]
                    players[fielder_name]["team"] = opposing[0] if opposing else ""

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
                        f"{existing}, run out (direct)" if existing else "run out (direct)"
                    )
                elif role == "runout_partial":
                    players[fielder_name]["field_pts"] += FIELD_RUNOUT_PARTIAL
                    existing = players[fielder_name]["fielding_detail"]
                    players[fielder_name]["fielding_detail"] = (
                        f"{existing}, run out (partial)" if existing else "run out (partial)"
                    )

    # Compute totals
    for name, p in players.items():
        p["total"] = p["bat_pts"] + p["bowl_pts"] + p["field_pts"]

    return players


# ── Helpers for building DataFrames ───────────────────────────────────

def _build_team_df(players, innings_list, team):
    """Build a DataFrame for one team's players."""
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
    """Build a combined leaderboard DataFrame."""
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


# ── Streamlit UI ──────────────────────────────────────────────────────

@st.cache_data(ttl=120, show_spinner=False)
def cached_match_links():
    return _fetch_match_links()


@st.cache_data(ttl=300, show_spinner="Fetching scorecard…")
def cached_scorecard(url):
    return parse_scorecard(url)


def main():
    st.set_page_config(page_title="IPL 2026 Fantasy Points", layout="wide")
    st.title("🏏 IPL 2026 Fantasy Points Calculator")

    # ── Sidebar: match selection ──────────────────────────────────
    with st.sidebar:
        st.header("Match Selection")
        use_latest = st.toggle("Use latest completed match", value=True)

        if use_latest:
            with st.spinner("Finding latest completed match…"):
                match_number, url = find_latest_completed_match()
            if not url:
                st.error("No completed IPL 2026 matches found yet.")
                st.stop()
            st.success(f"Match #{match_number}")
        else:
            match_number = st.number_input(
                "Match number", min_value=1, max_value=70, value=1, step=1
            )
            url = find_match_scorecard_url(match_number)
            if not url:
                st.error(
                    f"Match #{match_number} not found. "
                    "It may not have been played yet."
                )
                st.stop()

        st.caption(f"[Scorecard on Cricbuzz]({url.replace('/live-cricket-scorecard/', '/live-cricket-scores/')})")

    # ── Fetch & calculate ─────────────────────────────────────────
    match_info, innings_list, registry = cached_scorecard(url)

    if not innings_list:
        st.error("Could not parse scorecard. The match may still be in progress.")
        st.stop()

    players = calculate_fantasy_points(innings_list, registry)

    # ── Match header ──────────────────────────────────────────────
    if match_info.get("result"):
        st.markdown(f"**{match_info['result']}**")

    # ── Team tabs ─────────────────────────────────────────────────
    teams = match_info.get("teams", [])
    abbr = match_info.get("team_abbr", {})
    tab_labels = [abbr.get(t, t[:3].upper()) for t in teams] + ["Leaderboard"]
    tabs = st.tabs(tab_labels)

    for i, team in enumerate(teams):
        with tabs[i]:
            df = _build_team_df(players, innings_list, team)
            if df.empty:
                st.info("No player data available.")
                continue

            st.subheader(team)
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

    # ── Combined leaderboard ──────────────────────────────────────
    with tabs[-1]:
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
