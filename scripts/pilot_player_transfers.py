"""
PILOT / DIAGNOSTIC SCRIPT - not part of the regular data pipeline, not
scheduled to run automatically. Run this manually, once, to answer two
open questions before committing to building a full player-transfer
tracking feature:

  1. Does rugbypy's fetch_player_stats(player_id=X) return a player's
     FULL career history when no date is given, or does it require a
     date per call (which would make full-history fetching far more
     expensive than hoped)?
  2. Does each row include a team/club field we could use to detect a
     transfer (the club changing between two different dates)?

This script does NOT save anything to the repo - it only prints what it
finds to the Action log, so we can inspect real output and decide what
(if anything) to build next. Delete this file once we've learned what we
need from it.

Place this file at: scripts/pilot_player_transfers.py
"""
import glob
import json
import random

from rugbypy.player import fetch_all_players, fetch_player, fetch_player_stats


def df_to_records(df):
    return json.loads(df.to_json(orient="records"))


def main():
    # 1. Pull a few real player IDs out of club team-stats files we
    # already have cached, rather than guessing - each row's "players"
    # field is a list of player IDs who featured in that game.
    files = glob.glob("data/team-stats/*.json")
    print(f"Found {len(files)} cached club team-stats file(s) to sample from.")
    if not files:
        print("No team-stats files found - run update_data.py first. Nothing to sample.")
        return

    random.shuffle(files)
    sample_player_ids = []
    seen = set()
    for path in files:
        try:
            with open(path) as f:
                rows = json.load(f)
        except Exception as e:
            print(f"  ! could not read {path}: {e}")
            continue
        for row in rows:
            for pid in (row.get("players") or []):
                if pid not in seen:
                    seen.add(pid)
                    sample_player_ids.append(pid)
        if len(sample_player_ids) >= 3:
            break
    sample_player_ids = sample_player_ids[:3]
    print(f"Sampling {len(sample_player_ids)} player id(s): {sample_player_ids}")

    # 2. The key test: fetch_player_stats with NO date - full history, or empty/error?
    for pid in sample_player_ids:
        print(f"\n=== Player {pid}: fetch_player_stats(player_id={pid!r}), no date ===")
        try:
            df = fetch_player_stats(player_id=pid)
            records = df_to_records(df)
            print(f"  {len(records)} row(s) returned")
            if records:
                print(f"  columns: {list(records[0].keys())}")
                print(f"  first row: {json.dumps(records[0], default=str)}")
                if len(records) > 1:
                    print(f"  last row:  {json.dumps(records[-1], default=str)}")
        except Exception as e:
            print(f"  ! failed: {e}")

    # 3. The player manifest / search functions - needed for a "search a
    # player by name" feature, and to resolve a player_id to a real name.
    print("\n=== fetch_all_players() ===")
    try:
        df = fetch_all_players()
        records = df_to_records(df)
        print(f"  {len(records)} player(s) in manifest")
        if records:
            print(f"  columns: {list(records[0].keys())}")
            print(f"  sample: {json.dumps(records[0], default=str)}")
    except Exception as e:
        print(f"  ! failed: {e}")

    print("\n=== fetch_player(name='Antoine Dupont') ===")
    try:
        df = fetch_player(name="Antoine Dupont")
        records = df_to_records(df)
        print(f"  {len(records)} result(s)")
        print(f"  {json.dumps(records[:3], default=str)}")
    except Exception as e:
        print(f"  ! failed: {e}")

    print("\nDone. Review the output above before deciding what to build next.")


if __name__ == "__main__":
    main()
