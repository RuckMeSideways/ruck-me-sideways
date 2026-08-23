"""
Ruck Me Sideways - data bridge
Runs inside GitHub Actions. Pulls the rugbypy registries + per-team stats
into static JSON files under data/, so the (static, GitHub Pages) app can
fetch real data for every team without running Python in the browser.

Place this file at: scripts/update_data.py
"""
import json
import time
from pathlib import Path

from rugbypy.team import fetch_all_teams, fetch_team_stats
from rugbypy.match import fetch_all_matches, fetch_match_details
from rugbypy.competition import fetch_all_competitions

DATA_DIR = Path("data")
MATCH_DETAILS_DIR = DATA_DIR / "match-details"
TEAM_STATS_DIR = DATA_DIR / "team-stats"

# Match-details are fetched one-by-one and there are 6000+ of them, so we
# only fetch NEW ids each run and cap how many per run. Any leftover ids
# just get picked up on the next scheduled run - the cache only grows.
MAX_NEW_MATCH_DETAILS_PER_RUN = 500
REQUEST_PAUSE_SECONDS = 0.2


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":"), default=str)


def df_to_records(df):
    # Round-tripping through pandas' own json encoder handles NaN/NaT/
    # numpy types correctly (plain json.dumps chokes on them).
    return json.loads(df.to_json(orient="records"))


def main():
    DATA_DIR.mkdir(exist_ok=True)

    print("Fetching team registry...")
    teams = df_to_records(fetch_all_teams())
    save_json(DATA_DIR / "teams.json", teams)
    print(f"  {len(teams)} teams")

    print("Fetching competition registry...")
    comps = df_to_records(fetch_all_competitions())
    save_json(DATA_DIR / "competitions.json", comps)
    print(f"  {len(comps)} competitions")

    print("Fetching full match index...")
    matches = df_to_records(fetch_all_matches())
    save_json(DATA_DIR / "matches.json", matches)
    print(f"  {len(matches)} matches")

    print("Fetching per-team stats (full history for every team)...")
    for i, team in enumerate(teams, start=1):
        team_id = team.get("team_id")
        if not team_id:
            continue
        try:
            records = df_to_records(fetch_team_stats(team_id=team_id))
            save_json(TEAM_STATS_DIR / f"{team_id}.json", records)
        except Exception as e:
            print(f"  ! failed for {team.get('team_name')} ({team_id}): {e}")
        if i % 25 == 0 or i == len(teams):
            print(f"  {i}/{len(teams)} teams done")
        time.sleep(REQUEST_PAUSE_SECONDS)

    print("Fetching new match details (incremental)...")
    existing_ids = set()
    if MATCH_DETAILS_DIR.exists():
        existing_ids = {p.stem for p in MATCH_DETAILS_DIR.glob("*.json")}
    all_ids = [m["match_id"] for m in matches if m.get("match_id")]
    pending_ids = [mid for mid in all_ids if mid not in existing_ids]
    new_ids = pending_ids[:MAX_NEW_MATCH_DETAILS_PER_RUN]
    print(f"  {len(pending_ids)} pending, fetching {len(new_ids)} this run")

    for mid in new_ids:
        try:
            records = df_to_records(fetch_match_details(match_id=mid))
            save_json(MATCH_DETAILS_DIR / f"{mid}.json", records[0] if records else {})
        except Exception as e:
            print(f"  ! failed for match {mid}: {e}")
        time.sleep(REQUEST_PAUSE_SECONDS)

    print("Done.")


if __name__ == "__main__":
    main()
