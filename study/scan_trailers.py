"""
Step 2 of the Steam trailer study: scan each trailer with FlashGuard.

For each trailer in study/data/trailers.csv:
    1. download it to a temporary file (low resolution, video only, never played)
    2. scan it with FlashGuard
    3. delete the video
    4. append the results to study/data/scans.csv and study/data/incidents.csv

It's resumable: trailers already in scans.csv are skipped, so you can stop it
(Ctrl+C) and run it again later.

Usage:
    python study/scan_trailers.py              # main trailer of every game
    python study/scan_trailers.py --limit 5    # quick test
    python study/scan_trailers.py --all        # every trailer, not just the main one
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from flashguard import analyze_video  # noqa: E402
from flashguard.detector import MAX_TRANSITIONS  # noqa: E402

DATA = os.path.join(HERE, "data")

SCAN_FIELDS = ["movie_id", "appid", "status", "error", "verdict", "duration_sec", "fps",
               "width", "height", "peak_general_fps", "peak_red_fps", "n_incidents",
               "n_general_incidents", "n_red_incidents", "first_incident_sec",
               "failing_seconds", "share_frames_failing", "scanned_at"]
INCIDENT_FIELDS = ["movie_id", "appid", "kind", "start_sec", "end_sec", "duration_sec",
                   "peak_flashes_per_sec"]


def download(url: str, out_dir: str) -> str:
    """Local file paths are used as-is (handy for testing). URLs go through yt-dlp."""
    if os.path.exists(url):
        return url
    import yt_dlp

    opts = {
        "outtmpl": os.path.join(out_dir, "trailer.%(ext)s"),
        # low resolution video only: we downscale to 160px wide anyway, and no audio needed
        "format": "bv*[height<=480]/bv*/b[height<=480]/b/worst",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
    if not os.path.exists(path):                      # extension can change after download
        files = [os.path.join(out_dir, f) for f in os.listdir(out_dir)]
        if not files:
            raise RuntimeError("download produced no file")
        path = max(files, key=os.path.getsize)
    return path


def summarize(result, movie_id, appid) -> tuple[dict, list[dict]]:
    worst = [max(g, r) for g, r in zip(result.general_tps, result.red_tps)]
    failing = sum(1 for w in worst if w > MAX_TRANSITIONS)
    incs = result.incidents
    row = {
        "movie_id": movie_id, "appid": appid, "status": "ok", "error": "",
        "verdict": result.verdict,
        "duration_sec": round(result.duration, 2),
        "fps": round(result.fps, 2),
        "width": result.width, "height": result.height,
        "peak_general_fps": float(result.general_tps.max()) / 2,
        "peak_red_fps": float(result.red_tps.max()) / 2,
        "n_incidents": len(incs),
        "n_general_incidents": sum(i.kind == "general" for i in incs),
        "n_red_incidents": sum(i.kind == "red" for i in incs),
        "first_incident_sec": min((i.start_time for i in incs), default=""),
        "failing_seconds": round(sum(i.end_time - i.start_time for i in incs), 2),
        "share_frames_failing": round(failing / max(1, result.frame_count), 4),
        "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    inc_rows = [{
        "movie_id": movie_id, "appid": appid, "kind": i.kind,
        "start_sec": i.start_time, "end_sec": i.end_time,
        "duration_sec": round(i.end_time - i.start_time, 2),
        "peak_flashes_per_sec": i.peak_flashes_per_sec,
    } for i in incs]
    return row, inc_rows


def append(path, fields, rows):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerows(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--all", action="store_true", help="scan every trailer, not just each game's main one")
    p.add_argument("--limit", type=int, default=0, help="stop after this many trailers (0 = no limit)")
    p.add_argument("--trailers", default=os.path.join(DATA, "trailers.csv"))
    args = p.parse_args()

    if not os.path.exists(args.trailers):
        sys.exit(f"{args.trailers} not found. Run study/collect_games.py first.")

    with open(args.trailers, newline="", encoding="utf-8") as f:
        trailers = list(csv.DictReader(f))
    if not args.all:
        trailers = [t for t in trailers if t["is_main"] in ("True", "true", "1")]

    scans_path = os.path.join(DATA, "scans.csv")
    inc_path = os.path.join(DATA, "incidents.csv")
    done = set()
    if os.path.exists(scans_path):
        with open(scans_path, newline="", encoding="utf-8") as f:
            done = {r["movie_id"] for r in csv.DictReader(f) if r["status"] == "ok"}

    todo = [t for t in trailers if t["movie_id"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(trailers)} trailers, {len(done)} already scanned, {len(todo)} to go")

    counts = {"PASS": 0, "CAUTION": 0, "FAIL": 0, "error": 0}
    start = time.time()
    for n, t in enumerate(todo, 1):
        tmp = tempfile.mkdtemp(prefix="fg_")
        try:
            path = download(t["url"], tmp)
            result = analyze_video(path)
            row, incs = summarize(result, t["movie_id"], t["appid"])
            append(scans_path, SCAN_FIELDS, [row])
            if incs:
                append(inc_path, INCIDENT_FIELDS, incs)
            counts[row["verdict"]] += 1
            label = row["verdict"]
        except KeyboardInterrupt:
            print("\nStopped. Run the script again to pick up where it left off.")
            break
        except Exception as e:                        # record the failure and keep going
            err = {k: "" for k in SCAN_FIELDS}
            err.update(movie_id=t["movie_id"], appid=t["appid"], status="error",
                       error=str(e)[:300], scanned_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            append(scans_path, SCAN_FIELDS, [err])
            counts["error"] += 1
            label = "ERROR"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)    # the video never stays on disk

        rate = (time.time() - start) / n
        print(f"[{n}/{len(todo)}] {label:7s} appid {t['appid']}  "
              f"(~{rate * (len(todo) - n) / 60:.0f} min left)")

    print("Done:", ", ".join(f"{k} {v}" for k, v in counts.items()))
    print(f"Results in {scans_path}")


if __name__ == "__main__":
    main()
