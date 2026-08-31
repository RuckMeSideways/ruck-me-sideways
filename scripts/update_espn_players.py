"""
Ruck Me Sideways - ESPN player stats bridge
Runs inside GitHub Actions, after update_espn.py has already run at least
once. Reads the athlete list straight out of the match-stats files
update_espn.py already saved (data/espn/match-stats/{eventId}_{teamId}.json
each contain a splits.categories[].athletes[] list with links to that
player's identity and per-match statistics) - no need to re-fetch ESPN to
rediscover who played.

Cost control:
- A player's IDENTITY (name, position) is cached once in players.json and
  reused across every match they appear in - re-fetching a name we already
  know would be wasted calls, since the same national players show up in
  many different Tests.
- A player's STATISTICS are always match-specific and must be fetched per
  match, but only for matches not already processed.
- MAX_NEW_PLAYER_STATS_PER_RUN caps how many new player-match statistics
  get fetched in one run, so this can run daily and gradually catch up
  rather than trying to backfill everything (thousands of calls) at once.

Place this file at: scripts/update_espn_players.py
No secret/API key required. Requires update_espn.py to have already
populated data/espn/match-stats/ and data/espn/events.json.
"""
import json
import time
from pathlib import Path

import requests

DATA_DIR = Path("data/espn")
MATCH_STATS_DIR = DATA_DIR / "match-stats"
PLAYER_STATS_DIR = DATA_DIR / "player-stats"
PLAYERS_FILE = DATA_DIR / "players.json"
EVENTS_FILE = DATA_DIR / "events.json"

MAX_NEW_PLAYER_STATS_PER_RUN = 300
REQUEST_PAUSE_SECONDS = 0.3
HEADERS = {"User-Agent": "Mozilla/5.0 (RuckMeSideways data bridge)"}


def get_json(url):
    r = requests.get(url.split("?")[0], headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":"))


def load_json(path: Path, default):
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return default
    return default


def flatten_stats(stats_json):
    """Same approach as team stats: pull every numeric stat out of
    splits.categories[].stats[] into a plain {name: value} dict."""
    out = {}
    cats = ((stats_json or {}).get("splits") or {}).get("categories") or []
    for cat in cats:
        for s in cat.get("stats") or []:
            if isinstance(s.get("value"), (int, float)):
                out[s["name"]] = s["value"]
    return out


def athlete_id_from_ref(ref_url):
    return ref_url.rstrip("/").split("/")[-1].split("?")[0]


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not MATCH_STATS_DIR.exists():
        print("No data/espn/match-stats/ directory found - run update_espn.py first. Nothing to do.")
        return

    events = load_json(EVENTS_FILE, [])
    events_by_id = {e["event_id"]: e for e in events}
    players_cache = load_json(PLAYERS_FILE, {})  # athlete_id -> {name, position}

    new_stats_fetched = 0
    match_stats_files = sorted(MATCH_STATS_DIR.glob("*.json"))
    print(f"Found {len(match_stats_files)} team match-stats file(s) to check.")

    # Group files by event so we can build one combined player-stats file
    # per match (home + away together), same shape the app expects.
    by_event = {}
    for f in match_stats_files:
        stem = f.stem  # "{eventId}_{teamId}"
        if "_" not in stem:
            continue
        event_id, team_id = stem.split("_", 1)
        by_event.setdefault(event_id, []).append((team_id, f))

    for event_id, team_files in by_event.items():
        out_path = PLAYER_STATS_DIR / f"{event_id}.json"
        result = load_json(out_path, {"home": None, "away": None})
        event = events_by_id.get(event_id, {})
        home_id, away_id = event.get("home_team_id"), event.get("away_team_id")

        changed = False
        for team_id, file_path in team_files:
            side = "home" if team_id == home_id else "away" if team_id == away_id else None
            if side is None:
                continue
            if result.get(side) is not None:
                continue  # this side already fully processed in a previous run
            if new_stats_fetched >= MAX_NEW_PLAYER_STATS_PER_RUN:
                continue  # budget hit for this run - picks up next run

            team_stats = load_json(file_path, {})
            cats = ((team_stats or {}).get("splits") or {}).get("categories") or []
            athlete_refs = {}
            for cat in cats:
                for a in cat.get("athletes") or []:
                    aref = (a.get("athlete") or {}).get("$ref")
                    sref = (a.get("statistics") or {}).get("$ref")
                    if aref and sref:
                        athlete_refs[athlete_id_from_ref(aref)] = (aref, sref)

            side_players = []
            for pid, (aref, sref) in athlete_refs.items():
                if new_stats_fetched >= MAX_NEW_PLAYER_STATS_PER_RUN:
                    break
                try:
                    if pid not in players_cache:
                        identity = get_json(aref)
                        players_cache[pid] = {
                            "name": identity.get("displayName") or identity.get("fullName"),
                            "position": ((identity.get("position") or {}).get("abbreviation")
                                         or (identity.get("position") or {}).get("name")),
                        }
                        time.sleep(REQUEST_PAUSE_SECONDS)
                    stats = flatten_stats(get_json(sref))
                    side_players.append({
                        "id": pid,
                        "name": players_cache[pid]["name"],
                        "position": players_cache[pid]["position"],
                        "stats": stats,
                    })
                    new_stats_fetched += 1
                    time.sleep(REQUEST_PAUSE_SECONDS)
                except Exception as e:
                    print(f"  ! failed fetching player {pid} for event {event_id}: {e}")

            if len(side_players) == len(athlete_refs):
                # every player for this side was fetched successfully -
                # safe to mark this side done so we never redo it
                result[side] = side_players
                changed = True
            elif side_players:
                # partial - save what we got but don't mark as done, so
                # the rest get picked up next run
                result[side] = side_players

        if changed or result.get("home") or result.get("away"):
            save_json(out_path, result)

        if new_stats_fetched >= MAX_NEW_PLAYER_STATS_PER_RUN:
            break

    save_json(PLAYERS_FILE, players_cache)
    print(f"Done. {new_stats_fetched} new player-match statistic(s) fetched this run. {len(players_cache)} unique player(s) known.")


if __name__ == "__main__":
    main()
