"""
Spot-check the study: are the FAILs real flashes or false alarms?

Picks a random sample of failing trailers, re-downloads each one (never played),
and re-runs the detector on the flagged section to find exactly WHICH part of
the screen it counted as flashing. Then it saves a grid of still frames
covering the whole flagged second:

  * a yellow box marks the part of the screen (the 10 degree window) that was flagged
  * each tile shows the brightness of that box (or its red level for red flashes)
  * tiles where the detector counted a transition get a colored border:
      green = got brighter, magenta = got darker

Still images don't flash, so the grids are safe to look at.

Usage:
    python study/spot_check.py                      # 6 random FAILs
    python study/spot_check.py --n 10 --seed 3      # a different 10
    python study/spot_check.py --movie-id 2028378   # one specific trailer

Writes study/spot_checks/<appid>_<movie_id>.png and deletes each video right after.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import random
import shutil
import sys
import tempfile

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from scan_trailers import download  # noqa: E402
from flashguard import detector as fg  # noqa: E402

DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "spot_checks")
MAX_TILES = 48
TILE_W = 200


def read_csv(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def analyze_segment(video, start, end):
    """Re-run the detector's steps on [start-1s, end] and record, for every
    region, the frames where it counted a transition (and which direction)."""
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    aw = min(fg.ANALYSIS_WIDTH, width)
    ah = max(1, round(height * aw / width))
    regions = fg._regions(ah, aw)

    warm = max(0.0, start - 1.0)               # let the trackers settle first
    cap.set(cv2.CAP_PROP_POS_MSEC, warm * 1000)
    lum_t = fg._TransitionTracker((ah, aw))
    red_t = fg._TransitionTracker((ah, aw))
    last = {"general": np.zeros(len(regions), np.int8), "red": np.zeros(len(regions), np.int8)}

    frames = []          # (time, bgr frame) inside [start, end]
    trans = {"general": [[] for _ in regions], "red": [[] for _ in regions]}   # per region: [(time, sign)]
    region_vals = {"general": [], "red": []}   # per frame inside window: array of region means
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
        if t > end + 0.05:
            break
        lin = cv2.resize(fg._SRGB_TO_LINEAR[frame], (aw, ah), interpolation=cv2.INTER_AREA)
        b, g, r = lin[..., 0], lin[..., 1], lin[..., 2]
        lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
        tot = r + g + b
        sat = (r / np.maximum(tot, 1e-6) >= fg.RED_SAT) & (tot > 1e-4)
        redv = np.maximum(r - g - b, 0) * 320.0
        ev = {"general": lum_t.update(lum, fg._lum_qualifies),
              "red": red_t.update(redv, fg._red_qualifies, sat)}
        for kind in ("general", "red"):
            pos = (ev[kind] > 0).astype(np.float32)
            neg = (ev[kind] < 0).astype(np.float32)
            for i, (ys, xs) in enumerate(regions):
                net = float(pos[ys, xs].mean()) - float(neg[ys, xs].mean())
                if abs(net) >= fg.AREA_FRAC:
                    s = 1 if net > 0 else -1
                    if s != last[kind][i]:
                        last[kind][i] = s
                        if t >= start - 1e-3:
                            trans[kind][i].append((t, s))
        if t >= start - 1e-3:
            frames.append((t, frame))
            region_vals["general"].append(np.array([lum[ys, xs].mean() for ys, xs in regions]))
            region_vals["red"].append(np.array([redv[ys, xs].mean() for ys, xs in regions]))
    cap.release()
    return frames, regions, (aw, ah), trans, region_vals, fps


def build_grid(frames, box, label_vals, marks, kind, cols=8):
    stride = max(1, math.ceil(len(frames) / MAX_TILES))
    tiles = []
    # each tile shows the LAST frame of its group, and is marked if a transition happened in the group
    for idx in range(stride - 1, len(frames), stride):
        t, frame = frames[idx]
        h, w = frame.shape[:2]
        th = int(TILE_W * h / w)
        tile = cv2.resize(frame, (TILE_W, th))
        x0, y0, x1, y1 = box
        cv2.rectangle(tile, (int(x0 * TILE_W), int(y0 * th)), (int(x1 * TILE_W), int(y1 * th)), (0, 255, 255), 2)
        # a transition anywhere in the frames this tile stands for
        sign = 0
        for j in range(idx - stride + 1, idx + 1):
            sign = marks.get(j, sign)
        if sign:
            color = (0, 220, 0) if sign > 0 else (255, 0, 255)
            cv2.rectangle(tile, (0, 0), (TILE_W - 1, th - 1), color, 6)
        v = label_vals[idx]
        text = f"{t:.2f}s  L={v:.2f}" if kind == "general" else f"{t:.2f}s  red={v:.0f}"
        bar = np.zeros((18, TILE_W, 3), np.uint8)          # label sits above the picture, not on it
        cv2.putText(bar, text, (4, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1)
        tiles.append(np.vstack([bar, tile]))
    th, tw = tiles[0].shape[:2]
    while len(tiles) % cols:
        tiles.append(np.zeros((th, tw, 3), np.uint8))
    return np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]), stride


def check(video, start, end, kind_hint):
    frames, regions, (aw, ah), trans, rvals, fps = analyze_segment(video, start, end)
    if not frames:
        return None, "no frames read"
    # the region (and kind) with the most transitions packed into any 1 second
    best = (0, "general", 0)
    for kind in ("general", "red"):
        for i, tr in enumerate(trans[kind]):
            times = [t for t, _ in tr]
            peak = max((sum(1 for u in times if s <= u < s + 1.0) for s in times), default=0)
            if (peak, kind == kind_hint) > (best[0], best[1] == kind_hint):
                best = (peak, kind, i)
    peak, kind, ri = best
    ys, xs = regions[ri]
    box = (xs.start / aw, ys.start / ah, xs.stop / aw, ys.stop / ah)
    time_to_idx = {round(t, 4): k for k, (t, _) in enumerate(frames)}
    marks = {}
    for t, s in trans[kind][ri]:
        k = time_to_idx.get(round(t, 4))
        if k is not None:
            marks[k] = s
    vals = [v[ri] for v in rvals[kind]]
    img, stride = build_grid(frames, box, vals, marks, kind)
    lo, hi = min(vals), max(vals)
    note = (f"{kind} flash, {peak} transitions in the busiest second "
            f"({peak / 2:g} flashes/sec) in the boxed area; its "
            f"{'brightness' if kind == 'general' else 'red level'} ranged {lo:.2f} to {hi:.2f}"
            f"{'' if stride == 1 else f'; showing 1 of every {stride} frames'}")
    return img, note


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n", type=int, default=6)
    p.add_argument("--verdict", default="FAIL")
    p.add_argument("--movie-id")
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()

    scans = {r["movie_id"]: r for r in read_csv("scans.csv") if r["status"] == "ok"}
    trailers = {r["movie_id"]: r for r in read_csv("trailers.csv")}
    games = {r["appid"]: r for r in read_csv("games.csv")}
    first_inc = {}
    for r in read_csv("incidents.csv"):
        mid = r["movie_id"]
        if mid not in first_inc or float(r["start_sec"]) < float(first_inc[mid]["start_sec"]):
            first_inc[mid] = r

    if args.movie_id:
        picks = [args.movie_id]
    else:
        pool = sorted(m for m, s in scans.items() if s["verdict"] == args.verdict and m in trailers)
        random.Random(args.seed).shuffle(pool)
        picks = pool[: args.n]
    if not picks:
        sys.exit("No matching trailers found.")

    os.makedirs(OUT, exist_ok=True)
    for mid in picks:
        t = trailers[mid]
        g = games.get(t["appid"], {})
        inc = first_inc.get(mid)
        if inc:
            # the flagged second: from the incident start to 1.2s later (or the incident end if shorter)
            start = float(inc["start_sec"])
            end = min(float(inc["end_sec"]) + 0.2, start + 1.3)
            kind_hint = inc["kind"]
        else:
            start, end, kind_hint = 0.0, 1.3, "general"
        tmp = tempfile.mkdtemp(prefix="fg_")
        try:
            path = download(t["url"], tmp)
            img, note = check(path, start, end, kind_hint)
            if img is None:
                print(f"{mid}: {note}")
                continue
            out = os.path.join(OUT, f"{t['appid']}_{mid}.png")
            cv2.imwrite(out, img)
            print(f"{g.get('name', t['appid'])} [{g.get('sampled_genre', '')}] at {start:.2f}s:\n    {note}\n    -> {out}")
        except Exception as e:
            print(f"{mid}: error {e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
