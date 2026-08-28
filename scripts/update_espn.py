"""
Ruck Me Sideways - ESPN data bridge
Runs inside GitHub Actions. Pulls international rugby (Rugby Championship,
Six Nations, Rugby World Cup, British & Irish Lions Tour) from ESPN's
undocumented public JSON endpoints, which are Opta-sourced and include a
full team box score plus links to per-player stats - something neither
the rugbypy bridge (club-only) nor the Highlightly bridge (scores only,
no stats) provide for internationals.

IMPORTANT: these are UNOFFICIAL, undocumented ESPN endpoints. No API key,
no published rate limit, no guarantee they keep working - ESPN could
change or block them without notice. This script is written defensively
(every fetch wrapped in try/except, script continues past failures) and
incrementally (only fetches match details/stats it hasn't already cached)
so a single bad run can't wipe out previously-collected data, and re-runs
stay cheap once the initial backfill is done.

Place this file at: scripts/update_espn.py
No secret/API key required.
"""
import json
import time
from pathlib import Path

import requests

CORE_BASE = "https://sports.core.api.espn.com/v2/sports/rugby"
DATA_DIR = Path("data/espn")
MATCH_STATS_DIR = DATA_DIR / "match-stats"

# Only these competitions - deliberately excludes junior/women/sevens
# variants for now to keep call volume bounded. Matched by substring
# against the real league names ESPN returns, not hardcoded IDs, so it
# self-corrects if ESPN renames something.
LEAGUE_NAME_INCLUDES = ["rugby championship", "six nations", "rugby world cup", "british and irish lions", "nations championship", "tour"]
LEAGUE_NAME_EXCLUDES = ["u20", "women", "sevens", "summer series", "united rugby"]

MAX_NEW_EVENTS_PER_RUN = 150  # caps how many new matches get fully processed in one run
REQUEST_PAUSE_SECONDS = 0.3
HEADERS = {"User-Agent": "Mozilla/5.0 (RuckMeSideways data bridge)"}


def get_json(url, params=None):
    r = requests.get(url, headers=HEADERS, params=params or {}, timeout=30)
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


def discover_leagues():
    """Find target league IDs by name, not hardcoded IDs.
    NOTE: the numeric id in the URL path (e.g. .../leagues/244293) is what
    every other endpoint needs - it is NOT the same as the "id" field
    inside the response body (e.g. "8328"), which is ESPN's internal db
    id and doesn't work for further queries. Always use the URL-path id.
    """
    first_page = get_json(f"{CORE_BASE}/leagues", {"limit": 100})
    page_count = first_page.get("pageCount", 1)
    total_count = first_page.get("count", len(first_page.get("items", [])))
    print(f"  /leagues reports {total_count} total league(s) across {page_count} page(s)")
    all_refs = list(first_page.get("items", []))
    for page in range(2, page_count + 1):
        more = get_json(f"{CORE_BASE}/leagues", {"limit": 100, "page": page})
        all_refs.extend(more.get("items", []))
        time.sleep(REQUEST_PAUSE_SECONDS)

    leagues = []
    for ref in all_refs:
        url = ref.get("$ref", "").split("?")[0]
        if not url:
            continue
        url_id = url.rstrip("/").split("/")[-1]
        try:
            detail = get_json(url)
        except Exception as e:
            print(f"  ! failed fetching league {url}: {e}")
            continue
        name = (detail.get("name") or "").lower()
        if any(inc in name for inc in LEAGUE_NAME_INCLUDES) and not any(exc in name for exc in LEAGUE_NAME_EXCLUDES):
            season = detail.get("season") or {}
            leagues.append({
                "id": url_id,
                "internal_id": detail.get("id"),
                "name": detail.get("name"),
                "season_start": season.get("startDate"),
                "season_end": season.get("endDate"),
            })
            print(f"  matched league: {detail.get('name')} (id {url_id})")
        time.sleep(REQUEST_PAUSE_SECONDS)
    return leagues


EVENT_SEARCH_YEARS = [2022, 2023, 2024, 2025, 2026, 2027]


def discover_events(league):
    """Get all event IDs for a league, one year at a time.
    NOTE: ESPN's "dates" range parameter has an undocumented maximum span -
    a single multi-year range (e.g. 2022-2027) gets rejected outright with
    HTTP 400, not silently truncated. Querying year-by-year avoids that
    limit and also avoids trusting the league's own season_start/season_end
    metadata, which has been found to be too narrow for restructured
    competitions (e.g. Nations Championship in 2026)."""
    seen_ids = set()
    ids = []
    for year in EVENT_SEARCH_YEARS:
        params = {"limit": 200, "dates": f"{year}0101-{year}1231"}
        try:
            page = get_json(f"{CORE_BASE}/leagues/{league['id']}/events", params)
        except Exception as e:
            print(f"  ! failed fetching {year} events for league {league['id']}: {e}")
            continue
        items = list(page.get("items", []))
        page_count = page.get("pageCount", 1)
        for p in range(2, page_count + 1):
            try:
                more = get_json(f"{CORE_BASE}/leagues/{league['id']}/events", {**params, "page": p})
                items.extend(more.get("items", []))
            except Exception as e:
                print(f"  ! failed fetching {year} events page {p} for league {league['id']}: {e}")
            time.sleep(REQUEST_PAUSE_SECONDS)
        for ref in items:
            url = ref.get("$ref", "")
            eid = url.rstrip("/").split("/")[-1].split("?")[0]
            if eid and eid not in seen_ids:
                seen_ids.add(eid)
                ids.append(eid)
        time.sleep(REQUEST_PAUSE_SECONDS)
    if not ids:
        # Fall back to no date filter at all, in case the range format
        # isn't being interpreted the way we expect - better to get
        # "whatever ESPN defaults to" than nothing.
        print(f"  0 events across all years, retrying without a date filter...")
        try:
            items = get_json(f"{CORE_BASE}/leagues/{league['id']}/events", {"limit": 200}).get("items", [])
            for ref in items:
                url = ref.get("$ref", "")
                eid = url.rstrip("/").split("/")[-1].split("?")[0]
                if eid:
                    ids.append(eid)
        except Exception as e:
            print(f"  ! fallback fetch also failed for league {league['id']}: {e}")
    return ids


def resolve_score(ref_url):
    try:
        data = get_json(ref_url.split("?")[0])
        return data.get("value")
    except Exception:
        return None


def resolve_team_name(team_cache, ref_url):
    key = ref_url.split("?")[0]
    if key in team_cache:
        return team_cache[key]["name"]
    try:
        data = get_json(key)
        name = data.get("displayName") or data.get("name")
        team_id = data.get("id")
        team_cache[key] = {"id": team_id, "name": name}
        return name
    except Exception:
        return None


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    events_index = load_json(DATA_DIR / "events.json", [])
    events_by_id = {e["event_id"]: e for e in events_index}
    team_cache = load_json(DATA_DIR / "teams.json", {})
    # team_cache saved as a dict keyed by team ref URL -> {id, name}
    processed_new = 0

    print("Discovering target leagues by name...")
    leagues = discover_leagues()
    save_json(DATA_DIR / "leagues.json", leagues)
    print(f"Found {len(leagues)} target league(s).")

    for league in leagues:
        print(f"Discovering events for {league['name']} (id {league['id']})...")
        event_ids = discover_events(league)
        print(f"  {len(event_ids)} event(s) found")

        for eid in event_ids:
            if eid in events_by_id and events_by_id[eid].get("stats_fetched"):
                continue  # already fully processed in a previous run
            if processed_new >= MAX_NEW_EVENTS_PER_RUN:
                continue  # budget hit for this run; will pick up next run

            try:
                detail = get_json(f"{CORE_BASE}/leagues/{league['id']}/events/{eid}")
                comp = (detail.get("competitions") or [{}])[0]
                competitors = comp.get("competitors", [])
                if len(competitors) != 2:
                    continue

                entry = {
                    "event_id": eid,
                    "league_id": league["id"],
                    "league_name": league["name"],
                    "date": detail.get("date"),
                    "name": detail.get("name"),
                    "stats_fetched": False,
                }

                for c in competitors:
                    home_away = c.get("homeAway")
                    team_ref = (c.get("team") or {}).get("$ref", "")
                    score_ref = (c.get("score") or {}).get("$ref", "")
                    stats_ref = (c.get("statistics") or {}).get("$ref", "")
                    team_id = team_ref.rstrip("/").split("/")[-1].split("?")[0]
                    team_name = resolve_team_name(team_cache, team_ref) if team_ref else None
                    score = resolve_score(score_ref) if score_ref else None
                    time.sleep(REQUEST_PAUSE_SECONDS)

                    entry[f"{home_away}_team_id"] = team_id
                    entry[f"{home_away}_team_name"] = team_name
                    entry[f"{home_away}_score"] = score

                    if stats_ref:
                        try:
                            stats = get_json(stats_ref.split("?")[0])
                            save_json(MATCH_STATS_DIR / f"{eid}_{team_id}.json", stats)
                        except Exception as e:
                            print(f"  ! failed fetching stats for event {eid} team {team_id}: {e}")
                        time.sleep(REQUEST_PAUSE_SECONDS)

                entry["stats_fetched"] = True
                events_by_id[eid] = entry
                processed_new += 1
                if processed_new % 10 == 0:
                    print(f"  ...{processed_new} new events processed this run")
            except Exception as e:
                print(f"  ! failed processing event {eid}: {e}")
            time.sleep(REQUEST_PAUSE_SECONDS)

    save_json(DATA_DIR / "events.json", list(events_by_id.values()))
    save_json(DATA_DIR / "teams.json", team_cache)
    print(f"Done. {processed_new} new event(s) processed this run. {len(events_by_id)} total cached.")


if __name__ == "__main__":
    main()
