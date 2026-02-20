#!/usr/bin/env python3
import hashlib
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pytz
import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from icalendar import Calendar, Event
from dateutil import parser as dateparser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "dist")

TZ = pytz.timezone("Europe/Prague")
YEAR = 2026

TEAM_CZ = "CZE"

EVENTS = {
    "women": {
        "category": "women",
        "label": "ženy",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Ice_hockey_at_the_2026_Winter_Olympics_%E2%80%93_Women%27s_tournament",
        "out_file": "zoh-2026-hokej-zeny-cze.ics",
    },
    "men": {
        "category": "men",
        "label": "muži",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Ice_hockey_at_the_2026_Winter_Olympics_%E2%80%93_Men%27s_tournament",
        "out_file": "zoh-2026-hokej-muzi-cze.ics",
    },
}

MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

TEAM_NAMES_CZ = {
    "CZE": "Česko",
    "FIN": "Finsko",
    "SWE": "Švédsko",
    "USA": "USA",
    "CAN": "Kanada",
    "SUI": "Švýcarsko",
    "GER": "Německo",
    "SVK": "Slovensko",
    "LAT": "Lotyšsko",
    "DEN": "Dánsko",
    "NOR": "Norsko",
    "AUT": "Rakousko",
    "FRA": "Francie",
    "ITA": "Itálie",
    "JPN": "Japonsko",
    "CHN": "Čína",
    "KOR": "Jižní Korea",
}

TEAM_FLAGS = {
    "CZE": "🇨🇿",
    "FIN": "🇫🇮",
    "SWE": "🇸🇪",
    "USA": "🇺🇸",
    "CAN": "🇨🇦",
    "SUI": "🇨🇭",
    "GER": "🇩🇪",
    "SVK": "🇸🇰",
    "LAT": "🇱🇻",
    "DEN": "🇩🇰",
    "NOR": "🇳🇴",
    "AUT": "🇦🇹",
    "FRA": "🇫🇷",
    "ITA": "🇮🇹",
    "JPN": "🇯🇵",
    "CHN": "🇨🇳",
    "KOR": "🇰🇷",
}

TEAM_CODE_ALIASES = {
    "Czech Republic": "CZE",
    "Czechia": "CZE",
    "Czech Republic (CZE)": "CZE",
    "Finland": "FIN",
    "Sweden": "SWE",
    "United States": "USA",
    "United States of America": "USA",
    "Canada": "CAN",
    "Switzerland": "SUI",
    "Germany": "GER",
    "Slovakia": "SVK",
    "Latvia": "LAT",
    "Denmark": "DEN",
    "Norway": "NOR",
    "Austria": "AUT",
    "France": "FRA",
    "Italy": "ITA",
    "Japan": "JPN",
    "China": "CHN",
    "South Korea": "KOR",
}

TEAM_ALIAS_LOOKUP = {k.lower(): v for k, v in TEAM_CODE_ALIASES.items()}

PHASE_CZ = {
    "preliminary": "Skupina",
    "quarterfinals": "Čtvrtfinále",
    "semifinals": "Semifinále",
    "bronze": "O bronz",
    "gold": "Finále",
}

PLAYOFF_PHASES = {"quarterfinals", "semifinals", "bronze", "gold"}
GENDER_EMOJI = {"women": "👩", "men": "👨"}
MEDAL_EMOJI = {"bronze": "🥉", "gold": "🥇"}


@dataclass
class Game:
    category: str
    start: datetime
    team1: str
    team2: str
    phase_key: str
    phase_label: str
    group_label: Optional[str]
    venue: Optional[str]
    gamecenter: Optional[str] = None
    score1: Optional[int] = None
    score2: Optional[int] = None
    status_suffix: Optional[str] = None
    playoff_index: Optional[int] = None


def log(msg: str) -> None:
    print(msg, file=sys.stderr)

def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=1.0,
        status_forcelist=[403, 408, 429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

SESSION = build_session()

def fetch_url(url: str, timeout: int = 30) -> str:
    log(f"Fetching {url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "cs-CZ,cs;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    resp = SESSION.get(url, timeout=timeout, headers=headers)
    log(f"HTTP {resp.status_code} for {url}")
    resp.raise_for_status()
    return resp.text


def normalize_team(code: str) -> str:
    if not code:
        return "TBD"
    return code.strip().upper()


def normalize_team_name(name: str) -> str:
    if not name:
        return "TBD"
    cleaned = re.sub(r"\s+", " ", re.sub(r"\[.*?\]", "", name)).strip()
    if not cleaned:
        return "TBD"
    alias = TEAM_ALIAS_LOOKUP.get(cleaned.lower())
    if alias:
        return alias
    m = re.search(r"\b([A-Z]{3})\b", cleaned)
    if m:
        return m.group(1)
    return "TBD"


def parse_game_text(game_text: str) -> Tuple[str, str, Optional[str], Optional[str]]:
    phase_key = "preliminary"
    phase_label = "Preliminary Round"
    group_label = None

    if "Preliminary" in game_text:
        phase_key = "preliminary"
        phase_label = "Preliminary Round"
    elif "Quarterfinal" in game_text:
        phase_key = "quarterfinals"
        phase_label = "Quarterfinals"
    elif "Semifinal" in game_text:
        phase_key = "semifinals"
        phase_label = "Semifinals"
    elif "Bronze" in game_text:
        phase_key = "bronze"
        phase_label = "Bronze Medal Game"
    elif "Gold" in game_text or "Final" in game_text:
        phase_key = "gold"
        phase_label = "Gold Medal Game"

    m_group = re.search(r"Group\s+([A-Z])", game_text)
    if m_group:
        group_label = f"Skupina {m_group.group(1)}"

    m_teams = re.search(r"\b([A-Z]{3}|TBD)\s+vs\s+([A-Z]{3}|TBD)\b", game_text)
    if m_teams:
        team1 = normalize_team(m_teams.group(1))
        team2 = normalize_team(m_teams.group(2))
    else:
        team1 = "TBD"
        team2 = "TBD"

    return team1, team2, phase_key, group_label



def parse_wikipedia_schedule(url: str, category: str) -> List[Game]:
    html = fetch_url(url)
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table", class_=re.compile(r"wikitable"))
    games: List[Game] = []

    for table in tables:
        caption_text = ""
        caption = table.find("caption")
        if caption:
            caption_text = caption.get_text(" ", strip=True)

        header_cells = table.find_all("th")
        header_texts = [h.get_text(" ", strip=True).lower() for h in header_cells]
        date_idx = time_idx = venue_idx = None
        team1_idx = team2_idx = None
        for idx, h in enumerate(header_texts):
            if date_idx is None and "date" in h:
                date_idx = idx
            if time_idx is None and "time" in h:
                time_idx = idx
            if venue_idx is None and "venue" in h:
                venue_idx = idx
            if "home" in h or "team 1" in h:
                team1_idx = idx
            if "away" in h or "team 2" in h:
                team2_idx = idx

        current_date: Optional[datetime] = None
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if not cells:
                continue
            texts = [c.get_text(" ", strip=True) for c in cells]
            row_text = " ".join(texts)
            if not row_text or "schedule" in row_text.lower():
                continue

            raw_date = texts[date_idx] if date_idx is not None and date_idx < len(texts) else ""
            raw_time = texts[time_idx] if time_idx is not None and time_idx < len(texts) else ""

            if raw_date:
                if raw_date.strip().lower() in {"date", "datum"}:
                    raw_date = ""
                if raw_date:
                    try:
                        dt = dateparser.parse(raw_date, dayfirst=True, fuzzy=True)
                    except (ValueError, TypeError):
                        dt = None
                    if dt:
                        if dt.year == 1900:
                            dt = dt.replace(year=YEAR)
                        current_date = dt

            time_match = re.search(r"\b(\d{1,2}:\d{2})\b", raw_time or row_text)
            if not time_match or not current_date:
                continue
            time_str = time_match.group(1)
            dt = dateparser.parse(f"{current_date.date()} {time_str}", fuzzy=True)
            if not dt:
                continue
            start = TZ.localize(datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute))

            phase_key = "preliminary"
            group_label = None
            phase_text = f"{caption_text} {row_text}"
            if re.search(r"quarterfinal", phase_text, re.IGNORECASE):
                phase_key = "quarterfinals"
            elif re.search(r"semifinal", phase_text, re.IGNORECASE):
                phase_key = "semifinals"
            elif re.search(r"bronze", phase_text, re.IGNORECASE):
                phase_key = "bronze"
            elif re.search(r"gold|final", phase_text, re.IGNORECASE):
                phase_key = "gold"

            m_group = re.search(r"Group\s+([A-Z])", phase_text)
            if m_group:
                group_label = f"Skupina {m_group.group(1)}"

            team1 = team2 = "TBD"
            if team1_idx is not None and team1_idx < len(texts):
                team1 = normalize_team_name(texts[team1_idx])
            if team2_idx is not None and team2_idx < len(texts):
                team2 = normalize_team_name(texts[team2_idx])
            if team1 == "TBD" or team2 == "TBD":
                found = []
                for cell_text in texts:
                    code = normalize_team_name(cell_text)
                    if code != "TBD" and code not in found:
                        found.append(code)
                if len(found) >= 2:
                    team1, team2 = found[0], found[1]

            venue = texts[venue_idx] if venue_idx is not None and venue_idx < len(texts) else None

            games.append(
                Game(
                    category=category,
                    start=start,
                    team1=team1,
                    team2=team2,
                    phase_key=phase_key,
                    phase_label=PHASE_CZ.get(phase_key, "Skupina"),
                    group_label=group_label,
                    venue=venue,
                )
            )

    log(f"Wikipedia tables parsed games: {len(games)}")
    if games:
        return games

    vevent_games = parse_wikipedia_vevents(html, category)
    log(f"Wikipedia vevent parsed games: {len(vevent_games)}")
    if vevent_games:
        return vevent_games

    fallback_games = parse_wikipedia_schedule_text(html, category)
    log(f"Wikipedia text fallback games: {len(fallback_games)}")
    if fallback_games:
        return fallback_games

    api_games = parse_wikipedia_wikitext(url, category)
    log(f"Wikipedia wikitext parsed games: {len(api_games)}")
    return api_games


def parse_wikipedia_schedule_text(html: str, category: str) -> List[Game]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    raw_lines = [line.strip() for line in soup.get_text("\n").splitlines()]
    lines = [re.sub(r"\s+", " ", line) for line in raw_lines if line.strip()]

    team_names = sorted(TEAM_ALIAS_LOOKUP.keys(), key=len, reverse=True)
    team_names += ["tbd"]
    venues = ["PalaItalia", "Fiera Milano", "PalaItalia Santa Giulia"]

    games: List[Game] = []
    current_date: Optional[datetime] = None
    current_time: Optional[Tuple[int, int]] = None
    current_phase = "preliminary"
    current_group: Optional[str] = None

    i = 0
    while i < len(lines):
        line = lines[i]

        if re.search(r"\bGroup\s+[A-Z]\b", line):
            m = re.search(r"Group\s+([A-Z])", line)
            if m:
                current_group = f"Skupina {m.group(1)}"
                current_phase = "preliminary"
            i += 1
            continue
        if re.search(r"Quarter-finals|Quarterfinals", line, re.IGNORECASE):
            current_phase = "quarterfinals"
            current_group = None
            i += 1
            continue
        if re.search(r"Semi-finals|Semifinals", line, re.IGNORECASE):
            current_phase = "semifinals"
            current_group = None
            i += 1
            continue
        if re.search(r"Bronze medal game|Bronze", line, re.IGNORECASE):
            current_phase = "bronze"
            current_group = None
            i += 1
            continue
        if re.search(r"Gold medal game|Gold|Final", line, re.IGNORECASE):
            current_phase = "gold"
            current_group = None
            i += 1
            continue

        m_date = re.search(r"\b(\d{1,2}\s+[A-Za-z]+\s+20\d{2})\b", line)
        if m_date:
            try:
                current_date = dateparser.parse(m_date.group(1), dayfirst=True, fuzzy=True)
            except (ValueError, TypeError):
                current_date = None
            if current_date and current_date.year == 1900:
                current_date = current_date.replace(year=YEAR)
            i += 1
            continue

        m_time = re.fullmatch(r"\d{1,2}:\d{2}", line)
        if m_time:
            parts = m_time.group(0).split(":")
            current_time = (int(parts[0]), int(parts[1]))
            i += 1
            continue

        if not current_date or not current_time:
            i += 1
            continue

        lower = line.lower()
        if "attendance" in lower or "goalies" in lower or "referees" in lower or "linesmen" in lower:
            i += 1
            continue

        found = []
        positions = []
        for name in team_names:
            idx = lower.find(name)
            if idx != -1:
                found.append(name)
                positions.append((idx, name))
        if len(found) >= 2 or "tbd v tbd" in lower:
            if "tbd v tbd" in lower:
                team1 = "TBD"
                team2 = "TBD"
            else:
                positions.sort(key=lambda x: x[0])
                team1 = normalize_team_name(positions[0][1])
                team2 = normalize_team_name(positions[1][1])

            score1 = score2 = None
            m_score = re.search(r"(\d+)\s*[–-]\s*(\d+)", line)
            if m_score:
                score1 = int(m_score.group(1))
                score2 = int(m_score.group(2))

            venue = None
            for v in venues:
                if v.lower() in lower:
                    venue = v
                    break
            if not venue and i + 1 < len(lines):
                next_line = lines[i + 1]
                for v in venues:
                    if v.lower() in next_line.lower():
                        venue = v
                        break

            start = TZ.localize(
                datetime(current_date.year, current_date.month, current_date.day, current_time[0], current_time[1])
            )
            games.append(
                Game(
                    category=category,
                    start=start,
                    team1=team1,
                    team2=team2,
                    phase_key=current_phase,
                    phase_label=PHASE_CZ.get(current_phase, "Skupina"),
                    group_label=current_group,
                    venue=venue,
                    score1=score1,
                    score2=score2,
                )
            )
        i += 1

    return games


def parse_wikipedia_vevents(html: str, category: str) -> List[Game]:
    soup = BeautifulSoup(html, "lxml")
    games: List[Game] = []

    def infer_phase_from_heading(node) -> Tuple[str, Optional[str]]:
        heading = node.find_previous(["h2", "h3"])
        if not heading:
            return "preliminary", None
        heading_id = (heading.get("id") or "").lower()
        heading_text = heading.get_text(" ", strip=True).lower()

        if "group_a" in heading_id or "group a" in heading_text:
            return "preliminary", "Skupina A"
        if "group_b" in heading_id or "group b" in heading_text:
            return "preliminary", "Skupina B"
        if "quarter" in heading_id or "quarter" in heading_text:
            return "quarterfinals", None
        if "semi" in heading_id or "semi" in heading_text:
            return "semifinals", None
        if "bronze" in heading_id or "bronze" in heading_text:
            return "bronze", None
        if "gold" in heading_id or "gold" in heading_text or "final" in heading_id or "final" in heading_text:
            return "gold", None
        return "preliminary", None

    for summary in soup.select("table.vevent tr.summary"):
        cells = summary.find_all("td")
        if len(cells) < 4:
            continue

        left_text = " ".join(cells[0].stripped_strings)
        m_date = re.search(r"(\d{1,2}\s+[A-Za-z]+\s+2026)", left_text)
        m_time = re.search(r"\b(\d{1,2}:\d{2})\b", left_text)
        if not (m_date and m_time):
            continue
        try:
            dt = dateparser.parse(f"{m_date.group(1)} {m_time.group(1)}", dayfirst=True, fuzzy=True)
        except (ValueError, TypeError):
            continue
        start = TZ.localize(datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute))

        team1 = normalize_team_name(cells[1].get_text(" ", strip=True))
        team2 = normalize_team_name(cells[3].get_text(" ", strip=True))

        score1 = score2 = None
        status_suffix = None
        center_text = cells[2].get_text(" ", strip=True)
        m_score = re.search(r"(\d+)\s*[–-]\s*(\d+)", center_text)
        if m_score:
            score1 = int(m_score.group(1))
            score2 = int(m_score.group(2))
            if re.search(r"GWS|SO", center_text, re.IGNORECASE):
                status_suffix = "SO"
            elif re.search(r"OT", center_text, re.IGNORECASE):
                status_suffix = "OT"
            else:
                status_suffix = "FT"

        venue = None
        location = cells[4].get_text(" ", strip=True) if len(cells) > 4 else ""
        if location:
            venue = location

        phase_key, group_label = infer_phase_from_heading(summary)
        anchor_text = cells[0].get_text(" ", strip=True)
        anchor = cells[0].find("a", href=True)
        anchor_id = anchor["href"][1:] if anchor and anchor["href"].startswith("#") else ""
        anchor_key = anchor_id.lower()

        if "group_a" in anchor_key or "group a" in anchor_text.lower():
            phase_key = "preliminary"
            group_label = "Skupina A"
        elif "group_b" in anchor_key or "group b" in anchor_text.lower():
            phase_key = "preliminary"
            group_label = "Skupina B"
        elif "quarter" in anchor_key:
            phase_key = "quarterfinals"
            group_label = None
        elif "semi" in anchor_key:
            phase_key = "semifinals"
            group_label = None
        elif "bronze" in anchor_key:
            phase_key = "bronze"
            group_label = None
        elif "gold" in anchor_key or "final" in anchor_key:
            phase_key = "gold"
            group_label = None

        games.append(
            Game(
                category=category,
                start=start,
                team1=team1,
                team2=team2,
                phase_key=phase_key,
                phase_label=PHASE_CZ.get(phase_key, "Skupina"),
                group_label=group_label,
                venue=venue,
                score1=score1,
                score2=score2,
                status_suffix=status_suffix,
            )
        )

    return games


def parse_wikipedia_wikitext(url: str, category: str) -> List[Game]:
    m = re.search(r"/wiki/([^#?]+)", url)
    if not m:
        return []
    title = m.group(1)
    api_url = f"https://en.wikipedia.org/w/api.php?action=parse&prop=wikitext&format=json&page={title}"
    text = fetch_url(api_url)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    wikitext = data.get("parse", {}).get("wikitext", {}).get("*", "")
    if not wikitext:
        return []

    lines = wikitext.splitlines()
    games: List[Game] = []
    current_phase = "preliminary"
    current_group: Optional[str] = None
    current_date: Optional[datetime] = None

    def update_context(line: str) -> None:
        nonlocal current_phase, current_group
        if line.startswith("==="):
            if "Group " in line:
                m_group = re.search(r"Group\s+([A-Z])", line)
                if m_group:
                    current_group = f"Skupina {m_group.group(1)}"
                    current_phase = "preliminary"
        if line.startswith("=="):
            if "Quarter" in line:
                current_phase = "quarterfinals"
                current_group = None
            elif "Semi" in line:
                current_phase = "semifinals"
                current_group = None
            elif "Bronze" in line:
                current_phase = "bronze"
                current_group = None
            elif "Gold" in line or "Final" in line:
                current_phase = "gold"
                current_group = None

    def extract_teams(row_text: str) -> Tuple[str, str]:
        teams = []
        for pattern in [r"\{\{flag\|([^}|]+)", r"\{\{flagicon\|([^}|]+)", r"\{\{flagcountry\|([^}|]+)"]:
            for m_team in re.finditer(pattern, row_text):
                teams.append(normalize_team_name(m_team.group(1)))
        teams = [t for t in teams if t != "TBD"]
        if len(teams) >= 2:
            return teams[0], teams[1]
        return "TBD", "TBD"

    row_buffer: List[str] = []
    for line in lines:
        update_context(line)
        if line.startswith("|-"):
            row_text = " ".join(row_buffer)
            row_buffer = []
            m_date = re.search(r"(\d{1,2}\s+February\s+2026)", row_text)
            if m_date:
                try:
                    current_date = dateparser.parse(m_date.group(1), dayfirst=True, fuzzy=True)
                except (ValueError, TypeError):
                    current_date = None
                if current_date and current_date.year == 1900:
                    current_date = current_date.replace(year=YEAR)
            m_time = re.search(r"\b(\d{1,2}:\d{2})\b", row_text)
            if not (current_date and m_time):
                continue
            time_str = m_time.group(1)
            dt = dateparser.parse(f"{current_date.date()} {time_str}", fuzzy=True)
            if not dt:
                continue
            start = TZ.localize(datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute))
            team1, team2 = extract_teams(row_text)
            if team1 == "TBD" and team2 == "TBD":
                continue

            score1 = score2 = None
            status_suffix = None
            m_score = re.search(r"(\d+)\s*[–-]\s*(\d+)", row_text)
            if m_score:
                score1 = int(m_score.group(1))
                score2 = int(m_score.group(2))
                if "SO" in row_text:
                    status_suffix = "SO"
                elif "OT" in row_text:
                    status_suffix = "OT"
                else:
                    status_suffix = "FT"

            venue = None
            for v in ["Fiera Milano", "PalaItalia", "PalaItalia Santa Giulia"]:
                if v in row_text:
                    venue = v
                    break

            games.append(
                Game(
                    category=category,
                    start=start,
                    team1=team1,
                    team2=team2,
                    phase_key=current_phase,
                    phase_label=PHASE_CZ.get(current_phase, "Skupina"),
                    group_label=current_group,
                    venue=venue,
                    score1=score1,
                    score2=score2,
                    status_suffix=status_suffix,
                )
            )
        else:
            row_buffer.append(line)

    return games


def team_display(code: str) -> str:
    return TEAM_NAMES_CZ.get(code, code)

def team_display_with_flag(code: str) -> str:
    if code == "TBD":
        return "TBD 🏒"
    name = TEAM_NAMES_CZ.get(code, code)
    flag = TEAM_FLAGS.get(code)
    if flag:
        return f"{flag} {name}"
    return name


def build_uid(category: str, start: datetime, team1: str, team2: str) -> str:
    base = f"{category}|{start.strftime('%Y-%m-%d %H:%M')}|{team1}|{team2}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest() + "@zoh-hokej-ics"


def should_include(game: Game) -> bool:
    if game.phase_key in PLAYOFF_PHASES:
        return True
    return TEAM_CZ in (game.team1, game.team2)


def assign_playoff_indices(games: List[Game]) -> None:
    counters: Dict[str, int] = {k: 0 for k in PLAYOFF_PHASES}
    for game in sorted(games, key=lambda g: g.start):
        if game.phase_key in PLAYOFF_PHASES:
            counters[game.phase_key] += 1
            game.playoff_index = counters[game.phase_key]


def build_summary(game: Game) -> str:
    emoji = GENDER_EMOJI.get(game.category, "")
    medal = MEDAL_EMOJI.get(game.phase_key, "")
    prefix_parts = [p for p in [emoji, medal] if p]
    prefix = f"{' '.join(prefix_parts)} " if prefix_parts else ""
    if game.phase_key in PLAYOFF_PHASES and (game.team1 == "TBD" or game.team2 == "TBD"):
        index = game.playoff_index or 1
        return f"{prefix}{PHASE_CZ[game.phase_key]} {index}"
    t1 = team_display_with_flag(game.team1)
    t2 = team_display_with_flag(game.team2)
    summary = f"{prefix}{t1} – {t2}"
    if game.score1 is not None and game.score2 is not None and game.status_suffix:
        summary += f" {game.score1}:{game.score2} ({game.status_suffix})"
    return summary


def build_description(game: Game) -> str:
    parts: List[str] = []
    if game.group_label:
        parts.append(game.group_label)
    else:
        parts.append(PHASE_CZ.get(game.phase_key, "Skupina"))
    if game.venue:
        parts.append(game.venue)
    if game.gamecenter:
        parts.append(game.gamecenter)
    return "\n".join(parts)


def games_to_calendar(games: List[Game], cal_name: str) -> Calendar:
    cal = Calendar()
    cal.add("prodid", "-//zoh-hokej-2026-ics//CZ")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", cal_name)
    cal.add("x-wr-timezone", "Europe/Prague")

    for game in games:
        event = Event()
        summary = build_summary(game)
        event.add("summary", summary)
        event.add("dtstart", game.start)
        event.add("dtend", game.start + timedelta(hours=3))
        event.add("uid", build_uid(game.category, game.start, game.team1, game.team2))
        description = build_description(game)
        if description:
            event.add("description", description)
        cal.add_component(event)

    return cal


def write_calendar(cal: Calendar, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(cal.to_ical())


def load_schedule_for_category(cfg: Dict[str, str]) -> List[Game]:
    try:
        games = parse_wikipedia_schedule(cfg["wikipedia_url"], cfg["category"])
        if games:
            return games
    except Exception as wiki_exc:
        log(f"Wikipedia fetch failed ({wiki_exc})")
    return []


def main() -> int:
    all_games: Dict[str, List[Game]] = {}

    for key, cfg in EVENTS.items():
        games = load_schedule_for_category(cfg)
        if not games:
            log(f"No games for {key}, skipping")
            all_games[key] = []
            continue

        assign_playoff_indices(games)

        games = [g for g in games if should_include(g)]
        games.sort(key=lambda g: g.start)
        all_games[key] = games

        cal = games_to_calendar(games, f"ZOH 2026 – hokej ({cfg['label']})")
        out_path = os.path.join(DIST_DIR, cfg["out_file"])
        write_calendar(cal, out_path)
        log(f"Wrote {out_path}")

    combined = []
    for games in all_games.values():
        combined.extend(games)
    if combined:
        combined.sort(key=lambda g: g.start)
        cal = games_to_calendar(combined, "ZOH 2026 – hokej (Česko)")
        out_path = os.path.join(DIST_DIR, "zoh-2026-hokej-cesko.ics")
        write_calendar(cal, out_path)
        log(f"Wrote {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
