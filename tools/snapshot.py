"""
Save a grid of STILL frames from part of a video, so you can see what's in a
flagged section without playing it. Still images don't flash.

Usage:
    python tools/snapshot.py VIDEO START_SEC END_SEC [--frames 12] [--out snapshot.png]

Example:
    python tools/snapshot.py my_videos/reel.mov 3.1 5.0
"""

import argparse

import cv2
import numpy as np


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video")
    p.add_argument("start", type=float)
    p.add_argument("end", type=float)
    p.add_argument("--frames", type=int, default=12)
    p.add_argument("--out", default="snapshot.png")
    a = p.parse_args()

    cap = cv2.VideoCapture(a.video)
    if not cap.isOpened():
        raise SystemExit(f"Could not open {a.video}")

    tiles = []
    for t in np.linspace(a.start, a.end, a.frames):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        frame = cv2.resize(frame, (240, int(240 * h / w)))
        cv2.putText(frame, f"{t:.2f}s", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3)
        cv2.putText(frame, f"{t:.2f}s", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        tiles.append(frame)
    cap.release()
    if not tiles:
        raise SystemExit("No frames read in that time range.")

    cols = 4
    th, tw = tiles[0].shape[:2]
    while len(tiles) % cols:
        tiles.append(np.zeros((th, tw, 3), np.uint8))
    rows = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    cv2.imwrite(a.out, np.vstack(rows))
    print(f"Saved {a.out}")


if __name__ == "__main__":
    main()
