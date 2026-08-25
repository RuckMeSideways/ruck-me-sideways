"""
Ruck Me Sideways - international data bridge
Runs inside GitHub Actions. Pulls international rugby (Six Nations, Rugby
Championship, Autumn Nations Series, Rugby World Cup) from the API-Sports
Rugby API, since the club-focused rugbypy bridge doesn't cover full
national sides. Kept as a SEPARATE script/workflow from update_data.py so
it can't break the working club-data pipeline.

Place this file at: scripts/update_international.py
Requires a GitHub Actions secret named APISPORTS_KEY.
"""
import json
import os
import time
from pathlib import Path

import requests

API_KEY = os.environ["APISPORTS_KEY"]
BASE = "https://v1.rugby.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

DATA_DIR = Path("data/international")

# One call per name here, so keep this list short - each one costs a
# request against the 100/day free quota.
LEAGUE_SEARCHES = ["Six Nations", "Rugby Championship", "Autumn Nations Series", "Rugby World Cup"]
SEASONS = [2022, 2023, 2024, 2025, 2026]
REQUEST_PAUSE_SECONDS = 0.5


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":"))


def api_get(endpoint, params=None):
    r = requests.get(f"{BASE}/{endpoint}", headers=HEADERS, params=params or {}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        print(f"  ! API returned errors for {endpoint} {params}: {data['errors']}")
    return data.get("response", [])


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Discovering international leagues...")
    leagues = {}
    for name in LEAGUE_SEARCHES:
        try:
            results = api_get("leagues", {"search": name})
            print(f"  '{name}': {len(results)} result(s)")
            for lg in results:
                lid = lg.get("id") or (lg.get("league") or {}).get("id")
                lname = lg.get("name") or (lg.get("league") or {}).get("name") or name
                if lid:
                    leagues[lid] = lname
        except Exception as e:
            print(f"  ! failed searching leagues for '{name}': {e}")
        time.sleep(REQUEST_PAUSE_SECONDS)

    save_json(DATA_DIR / "leagues.json", [{"id": k, "name": v} for k, v in leagues.items()])
    print(f"Found {len(leagues)} league(s): {leagues}")

    print("Fetching games for each league/season...")
    all_games = []
    for lid in leagues:
        for season in SEASONS:
            try:
                games = api_get("games", {"league": lid, "season": season})
                if games:
                    print(f"  league {lid} season {season}: {len(games)} game(s)")
                all_games.extend(games)
            except Exception as e:
                print(f"  ! failed fetching games for league {lid} season {season}: {e}")
            time.sleep(REQUEST_PAUSE_SECONDS)

    save_json(DATA_DIR / "games.json", all_games)
    print(f"Total games saved: {len(all_games)}")

    # Build the team list straight from the games we already fetched -
    # no extra API calls needed.
    teams = {}
    for g in all_games:
        for side in ("home", "away"):
            t = (g.get("teams") or {}).get(side) or {}
            tid, tname = t.get("id"), t.get("name")
            if tid and tname:
                teams[tid] = tname
    save_json(DATA_DIR / "teams.json", [{"id": k, "name": v} for k, v in teams.items()])
    print(f"Derived {len(teams)} team(s) from games")

    print("Done.")


if __name__ == "__main__":
    main()
