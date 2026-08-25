"""
Ruck Me Sideways - international data bridge (v2 - Highlightly)
Runs inside GitHub Actions. Pulls international rugby (Six Nations, Rugby
Championship, Rugby World Cup, Super Rugby, Autumn Nations Series) from
the Highlightly Rugby API, since the club-focused rugbypy bridge doesn't
cover full national sides.

Replaces the earlier API-Sports version of this bridge - Highlightly
properly covers Rugby Championship (South Africa, New Zealand etc.) and
has a much more workable rate limit (1000 req/hour vs API-Sports' 10/min).

Place this file at: scripts/update_international.py
Requires a GitHub Actions secret named HIGHLIGHTLY_KEY (a RapidAPI key
for the "Rugby Highlights API" by Highlightly).
"""
import json
import os
import time
from pathlib import Path

import requests

API_KEY = os.environ["HIGHLIGHTLY_KEY"]
BASE = "https://rugby-highlights-api.p.rapidapi.com"
HEADERS = {
    "x-rapidapi-key": API_KEY,
    "x-rapidapi-host": "rugby-highlights-api.p.rapidapi.com",
}

DATA_DIR = Path("data/international")

# One call per name here, so keep this list short - each one costs a
# request against the 100/day free quota.
LEAGUE_SEARCHES = ["Six Nations", "Rugby Championship", "Rugby World Cup", "Super Rugby", "Autumn Nations Series"]
# Leagues to drop even if a search above matches them - e.g. competitions
# already covered by the club-data bridge (update_data.py), which would
# otherwise waste quota re-fetching duplicate data here.
EXCLUDE_LEAGUE_NAME_PARTS = ["united rugby championship"]
PAGE_LIMIT = 100
MAX_PAGES_PER_LEAGUE_SEASON = 3  # safety cap - avoids runaway pagination burning quota
REQUEST_PAUSE_SECONDS = 1.0  # well under the 1000/hour throttle, just to be polite


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":"))


def api_get(endpoint, params=None):
    r = requests.get(f"{BASE}/{endpoint}", headers=HEADERS, params=params or {}, timeout=30)
    if r.status_code != 200:
        print(f"  ! {endpoint} {params} returned HTTP {r.status_code}: {r.text[:200]}")
        return [], {}
    body = r.json()
    return body.get("data", []), body.get("pagination", {})


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Discovering international leagues...")
    # league id -> {"name": ..., "seasons": [2022, 2023, ...]}
    leagues = {}
    for name in LEAGUE_SEARCHES:
        try:
            results, _ = api_get("leagues", {"leagueName": name})
            print(f"  '{name}': {len(results)} result(s)")
            for lg in results:
                lid, lname = lg.get("id"), lg.get("name") or name
                if not lid:
                    continue
                if any(part in lname.lower() for part in EXCLUDE_LEAGUE_NAME_PARTS):
                    print(f"    skipping '{lname}' (excluded - covered by the club bridge)")
                    continue
                seasons = [s.get("season") for s in (lg.get("seasons") or []) if s.get("season")]
                leagues[lid] = {"name": lname, "seasons": seasons}
        except Exception as e:
            print(f"  ! failed searching leagues for '{name}': {e}")
        time.sleep(REQUEST_PAUSE_SECONDS)

    save_json(DATA_DIR / "leagues.json", [{"id": k, **v} for k, v in leagues.items()])
    print(f"Found {len(leagues)} league(s): {leagues}")

    print("Fetching matches for each league/season...")
    all_matches = []
    for lid, info in leagues.items():
        for season in info["seasons"]:
            offset = 0
            for page in range(MAX_PAGES_PER_LEAGUE_SEASON):
                try:
                    matches, pagination = api_get(
                        "matches", {"leagueId": lid, "season": season, "limit": PAGE_LIMIT, "offset": offset}
                    )
                    if matches:
                        print(f"  league {lid} season {season} offset {offset}: {len(matches)} match(es)")
                    all_matches.extend(matches)
                    if len(matches) < PAGE_LIMIT:
                        break  # no more pages
                    offset += PAGE_LIMIT
                except Exception as e:
                    print(f"  ! failed fetching matches for league {lid} season {season} offset {offset}: {e}")
                    break
                time.sleep(REQUEST_PAUSE_SECONDS)

    save_json(DATA_DIR / "matches.json", all_matches)
    print(f"Total matches saved: {len(all_matches)}")

    # Build the team list straight from the matches we already fetched -
    # no extra API calls needed.
    teams = {}
    for m in all_matches:
        for side in ("homeTeam", "awayTeam"):
            t = m.get(side) or {}
            tid, tname = t.get("id"), t.get("name")
            if tid and tname:
                teams[tid] = tname
    save_json(DATA_DIR / "teams.json", [{"id": k, "name": v} for k, v in teams.items()])
    print(f"Derived {len(teams)} team(s) from matches")

    print("Done.")


if __name__ == "__main__":
    main()
