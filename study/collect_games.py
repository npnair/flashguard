"""
Step 1 of the Steam trailer study: build the list of games and trailers.

1. Ask SteamSpy for the games in each genre.
2. Randomly sample N games per genre (fixed seed, so the sample is repeatable).
3. Ask the Steam store API for each game's details and trailer links.

Writes:
    study/data/games.csv     one row per game (genres, price, release date, ...)
    study/data/trailers.csv  one row per trailer (stream URL, is it the main trailer, ...)

Nothing is downloaded or played here. Only metadata.

Usage:
    python study/collect_games.py --per-genre 40
    python study/collect_games.py --per-genre 3 --genres Action Indie     # quick test
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import re
import sys
import time

import requests

STEAMSPY = "https://steamspy.com/api.php"
APPDETAILS = "https://store.steampowered.com/api/appdetails"
TRAILER_BASE = "https://video.fastly.steamstatic.com/store_trailers/"

DEFAULT_GENRES = ["Action", "Adventure", "RPG", "Strategy", "Simulation",
                  "Racing", "Sports", "Casual", "Indie"]

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
HEADERS = {"User-Agent": "flashguard-study/0.1 (accessibility research)"}


def owners_mid(owners: str) -> int:
    """SteamSpy gives owners as a range like '1,000,000 .. 2,000,000'. Use the midpoint."""
    nums = [int(n.replace(",", "")) for n in re.findall(r"[\d,]+", owners or "") if n.strip(",")]
    return sum(nums) // len(nums) if nums else 0


def _steamspy(params: dict) -> dict:
    try:
        r = requests.get(STEAMSPY, params=params, headers=HEADERS, timeout=180)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"    SteamSpy request failed: {e}")
        return {}


def get_genre(genre: str) -> dict:
    """SteamSpy sometimes returns nothing for big genres (timeouts / rate limits).
    Retry, then fall back to the tag with the same name."""
    for attempt in range(3):
        apps = _steamspy({"request": "genre", "genre": genre})
        if apps:
            return apps
        print(f"    empty response for genre '{genre}', retrying in 65s ({attempt + 1}/3)")
        time.sleep(65)
    print(f"    falling back to the '{genre}' tag")
    return _steamspy({"request": "tag", "tag": genre})


def get_appdetails(appid: int) -> dict | None:
    for attempt in range(4):
        r = requests.get(APPDETAILS, params={"appids": appid, "cc": "us", "l": "en"},
                         headers=HEADERS, timeout=30)
        if r.status_code == 429:                      # rate limited: back off and retry
            wait = 60 * (attempt + 1)
            print(f"    rate limited, waiting {wait}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        body = r.json() or {}
        entry = body.get(str(appid)) or {}
        return entry.get("data") if entry.get("success") else None
    return None


def full_url(u: str | None) -> str:
    if not u:
        return ""
    if u.startswith("http"):
        return u
    return TRAILER_BASE + u.lstrip("/")


def trailer_url(movie: dict) -> str:
    """Prefer the HLS H.264 stream. Fall back to old-style MP4 links if a game still has them."""
    if movie.get("hls_h264"):
        return full_url(movie["hls_h264"])
    if movie.get("dash_h264"):
        return full_url(movie["dash_h264"])
    mp4 = movie.get("mp4")
    if isinstance(mp4, dict):
        return mp4.get("480") or mp4.get("max") or ""
    return mp4 or ""


def parse_game(appid: int, d: dict, sampled_genre: str, spy: dict) -> tuple[dict, list[dict]]:
    price = d.get("price_overview") or {}
    game = {
        "appid": appid,
        "name": d.get("name", ""),
        "sampled_genre": sampled_genre,
        "genres": "|".join(g.get("description", "") for g in d.get("genres") or []),
        "is_free": bool(d.get("is_free")),
        "price_usd": round(price.get("initial", 0) / 100, 2) if price else (0.0 if d.get("is_free") else None),
        "release_date": (d.get("release_date") or {}).get("date", ""),
        "coming_soon": (d.get("release_date") or {}).get("coming_soon", False),
        "developers": "|".join(d.get("developers") or []),
        "publishers": "|".join(d.get("publishers") or []),
        "metacritic": (d.get("metacritic") or {}).get("score"),
        "required_age": d.get("required_age", 0),
        "owners_estimate": owners_mid(spy.get("owners", "")),
        "positive_reviews": spy.get("positive"),
        "negative_reviews": spy.get("negative"),
        "n_trailers": len(d.get("movies") or []),
    }
    trailers = []
    movies = [m for m in d.get("movies") or [] if trailer_url(m)]
    # main trailer = the one Steam marks as the highlight, otherwise the first one listed
    main_idx = next((i for i, m in enumerate(movies) if m.get("highlight") or m.get("is_highlight")), 0)
    for i, m in enumerate(movies):
        url = trailer_url(m)
        trailers.append({
            "movie_id": m.get("id"),
            "appid": appid,
            "trailer_name": m.get("name", ""),
            "position": i,
            "is_main": i == main_idx,
            "url": url,
        })
    return game, trailers


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--per-genre", type=int, default=40, help="games to sample per genre")
    p.add_argument("--genres", nargs="+", default=DEFAULT_GENRES)
    p.add_argument("--min-owners", type=int, default=20000,
                   help="skip games with fewer estimated owners (filters out abandoned shovelware)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--append", action="store_true",
                   help="add to the existing games.csv / trailers.csv instead of overwriting "
                        "(use this to fill in genres that came back empty)")
    args = p.parse_args()

    os.makedirs(DATA, exist_ok=True)
    rng = random.Random(args.seed)
    seen: set[int] = set()
    if args.append and os.path.exists(os.path.join(DATA, "games.csv")):
        with open(os.path.join(DATA, "games.csv"), newline="", encoding="utf-8") as f:
            seen = {int(r["appid"]) for r in csv.DictReader(f)}
        print(f"Appending: {len(seen)} games already collected will be skipped")
    picks: list[tuple[str, list]] = []

    for gi, genre in enumerate(args.genres):
        if gi:
            print("  (SteamSpy allows about one genre request per minute, waiting...)")
            time.sleep(61)
        print(f"Fetching {genre} games from SteamSpy...")
        try:
            apps = get_genre(genre)
        except Exception as e:
            print(f"  failed: {e}")
            continue
        pool = [(int(k), v) for k, v in apps.items()
                if owners_mid(v.get("owners", "")) >= args.min_owners and int(k) not in seen]
        rng.shuffle(pool)
        # take a few extra, since some games have no trailer or aren't available in the US store
        chosen = pool[: int(args.per_genre * 1.5) + 2]
        print(f"  {len(apps)} games, {len(pool)} above owner threshold, checking {len(chosen)}")
        picks.append((genre, chosen))

    games, trailers = [], []
    for genre, chosen in picks:
        kept = 0
        for appid, spy in chosen:
            if kept >= args.per_genre:
                break
            if appid in seen:
                continue
            time.sleep(1.6)                           # stay under ~200 requests / 5 min
            try:
                d = get_appdetails(appid)
            except Exception as e:
                print(f"  {appid}: error {e}")
                continue
            if not d or d.get("type") != "game" or not d.get("movies"):
                continue
            game, trs = parse_game(appid, d, genre, spy)
            if not trs:
                continue
            seen.add(appid)
            games.append(game)
            trailers.extend(trs)
            kept += 1
            print(f"  [{genre}] {game['name']} ({len(trs)} trailers)")

    def write(name, rows):
        if not rows:
            return
        path = os.path.join(DATA, name)
        adding = args.append and os.path.exists(path)
        with open(path, "a" if adding else "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            if not adding:
                w.writeheader()
            w.writerows(rows)
        print(f"{'Added' if adding else 'Wrote'} {len(rows)} rows to {path}")

    write("games.csv", games)
    write("trailers.csv", trailers)
    if not games:
        print("No games collected. Check your internet connection and try again.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
