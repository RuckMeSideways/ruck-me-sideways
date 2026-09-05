"""
Ruck Me Sideways - player transfer/history bridge
Fetches each player's FULL career history in one call (rugbypy's
fetch_player_stats returns every game when no date is given - confirmed
via a pilot script), then reduces it to a list of "stints" - continuous
spells at one club - so the app can show a player's current club and
transfer history without needing to ship every single game row.

Incremental and capped, same pattern as every other bridge here: only
processes new player IDs each run, skips ones already done, and skips
ones already confirmed invalid so we don't keep retrying bad IDs forever
(some player IDs found embedded in match data turn out not to exist in
rugbypy's own system - confirmed during the pilot).

Place this file at: scripts/update_players.py
No secret/API key required. Reads data/team-stats/*.json (from
update_data.py) to find real player IDs to look up.
"""
import glob
import json
import time
from pathlib import Path

from rugbypy.player import fetch_all_players, fetch_player_stats

DATA_DIR = Path("data/players")
INDEX_FILE = DATA_DIR / "index.json"
INVALID_FILE = DATA_DIR / "invalid.json"
MAX_NEW_PLAYERS_PER_RUN = 200
REQUEST_PAUSE_SECONDS = 0.2


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


def df_to_records(df):
    return json.loads(df.to_json(orient="records"))


def collect_candidate_player_ids():
    """Every player ID that appears in any cached club match, deduped -
    reusing IDs we already have on disk rather than needing extra calls
    to discover who exists."""
    ids = set()
    for path in glob.glob("data/team-stats/*.json"):
        try:
            with open(path) as f:
                rows = json.load(f)
        except Exception:
            continue
        for row in rows:
            for pid in (row.get("players") or []):
                ids.add(pid)
    return ids


def build_stints(records):
    """Collapse a player's full game-by-game history into a list of
    continuous spells at one club, sorted oldest to newest. A new stint
    starts whenever team_id changes from the previous game."""
    rows = sorted(records, key=lambda r: str(r.get("game_date") or ""))
    stints = []
    for r in rows:
        team_id = r.get("team_id")
        team_name = r.get("team")
        date = r.get("game_date")
        if not team_id or not date:
            continue
        if stints and stints[-1]["team_id"] == team_id:
            stints[-1]["end_date"] = date
            stints[-1]["games"] += 1
        else:
            stints.append({
                "team_id": team_id, "team_name": team_name,
                "start_date": date, "end_date": date, "games": 1,
            })
    return stints


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching full player name manifest...")
    try:
        manifest = df_to_records(fetch_all_players())
        save_json(INDEX_FILE, manifest)
        print(f"  {len(manifest)} player(s) in manifest")
    except Exception as e:
        print(f"  ! failed fetching player manifest: {e}")

    invalid_ids = set(load_json(INVALID_FILE, []))
    candidate_ids = collect_candidate_player_ids()
    print(f"Found {len(candidate_ids)} candidate player id(s) from cached club matches.")

    processed_new = 0
    for pid in candidate_ids:
        if processed_new >= MAX_NEW_PLAYERS_PER_RUN:
            break
        if pid in invalid_ids:
            continue
        out_path = DATA_DIR / f"{pid}.json"
        if out_path.exists():
            continue  # already processed in a previous run

        try:
            records = df_to_records(fetch_player_stats(player_id=pid))
        except Exception as e:
            print(f"  ! failed fetching player {pid}: {e}")
            invalid_ids.add(pid)
            processed_new += 1
            time.sleep(REQUEST_PAUSE_SECONDS)
            continue

        if not records:
            invalid_ids.add(pid)
            processed_new += 1
            time.sleep(REQUEST_PAUSE_SECONDS)
            continue

        stints = build_stints(records)
        name = records[0].get("name") or records[0].get("player_name")
        position = records[-1].get("position")  # most recent game's position
        current = stints[-1] if stints else None
        save_json(out_path, {
            "id": pid,
            "name": name,
            "position": position,
            "current_team_id": current["team_id"] if current else None,
            "current_team_name": current["team_name"] if current else None,
            "stints": stints,
        })
        processed_new += 1
        if processed_new % 25 == 0:
            print(f"  ...{processed_new} new player(s) processed this run")
        time.sleep(REQUEST_PAUSE_SECONDS)

    save_json(INVALID_FILE, sorted(invalid_ids))
    print(f"Done. {processed_new} new player(s) processed this run.")


if __name__ == "__main__":
    main()
