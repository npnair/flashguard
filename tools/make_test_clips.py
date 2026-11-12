"""
Generate synthetic test clips with known answers.

WARNING: files starting with UNSAFE_ contain real flashing. Do not watch them
if you are photosensitive. They exist only so the detector can be tested
without anyone having to look at them.

Usage: python tools/make_test_clips.py [output_dir]
"""

import os
import sys

import cv2
import numpy as np

W, H, FPS, SECONDS = 320, 240, 30, 4
N = FPS * SECONDS

GRAY_EQUAL_TO_RED = 127  # sRGB gray with about the same luminance as pure red


def write(path, frame_fn):
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for i in range(N):
        vw.write(frame_fn(i))
    vw.release()


def solid(bgr):
    f = np.zeros((H, W, 3), np.uint8)
    f[:] = bgr
    return f


def toggling(period_frames):
    """True/False switching every `period_frames` frames."""
    return lambda i: (i // period_frames) % 2 == 0


# expected verdict for each clip -> used by the tests
CLIPS = {}

# clips the detector is known to get wrong for now (tests mark them as expected failures)
KNOWN_LIMITS = {
    "UNSAFE_checkerboard_5hz.mp4": "pattern reversal: average brightness never changes, so it "
                                   "looks the same as motion. Needs a separate pattern check.",
}


def clip(name, expected):
    def deco(fn):
        CLIPS[name] = (fn, expected)
        return fn
    return deco


@clip("safe_slow_fade.mp4", "PASS")
def _(i):
    v = int(255 * (0.5 - 0.5 * np.cos(2 * np.pi * i / N)))  # one slow cycle over 4s
    return solid((v, v, v))


@clip("safe_dim_flicker.mp4", "PASS")
def _(i):
    # fast flicker, but the luminance change is too small to count (< 0.1)
    on = toggling(3)(i)
    return solid((60, 60, 60) if on else (20, 20, 20))


@clip("safe_small_flash.mp4", "PASS")
def _(i):
    # fast full-contrast flash, but only in a tiny square (too small an area)
    f = solid((40, 40, 40))
    if toggling(3)(i):
        f[110:130, 150:170] = 255
    return f


@clip("caution_3_flashes_per_sec.mp4", "CAUTION")
def _(i):
    # exactly 3 flashes per second: at the limit, not over it
    return solid((255, 255, 255) if toggling(5)(i) else (0, 0, 0))


@clip("UNSAFE_fullscreen_5hz.mp4", "FAIL")
def _(i):
    return solid((255, 255, 255) if toggling(3)(i) else (0, 0, 0))


@clip("UNSAFE_checkerboard_5hz.mp4", "FAIL")
def _(i):
    # average brightness never changes, but every pixel flashes
    yy, xx = np.mgrid[0:H, 0:W]
    board = (((yy // 20) + (xx // 20)) % 2).astype(bool)
    if not toggling(3)(i):
        board = ~board
    f = np.zeros((H, W, 3), np.uint8)
    f[board] = 255
    return f


# ---- motion: lots of pixel changes, but nothing actually flashing --------
_rng = np.random.default_rng(0)
_TEXTURE = cv2.GaussianBlur(
    cv2.resize((_rng.random((H // 8, W * 3 // 8)) * 255).astype(np.uint8), (W * 3, H),
               interpolation=cv2.INTER_NEAREST), (5, 5), 0)


def _pan(x):
    return cv2.cvtColor(_TEXTURE[:, x:x + W], cv2.COLOR_GRAY2BGR)


@clip("safe_fast_camera_pan.mp4", "PASS")
def _(i):
    return _pan((i * 8) % (W * 2))


@clip("safe_handheld_shake.mp4", "PASS")
def _(i):
    x = W + int(12 * np.sin(i * 0.9) + 6 * np.sin(i * 2.3))   # jittery back and forth
    return _pan(x)


@clip("safe_fast_moving_ball.mp4", "PASS")
def _(i):
    # bright ball crossing the whole screen in under a second, bouncing off the edges.
    # (A huge object darting in and out of the same spot several times a second
    # really IS flicker for that area, so that's deliberately not what this tests.)
    f = np.zeros((H, W, 3), np.uint8)
    span = W - 60
    pos = (i * 12) % (2 * span)
    cx = 30 + (pos if pos < span else 2 * span - pos)
    cv2.circle(f, (int(cx), H // 2), 25, (255, 255, 255), -1)
    return f


@clip("UNSAFE_flash_during_camera_pan.mp4", "FAIL")
def _(i):
    f = _pan((i * 8) % (W * 2))
    if toggling(3)(i):
        f = np.full_like(f, 255)
    return f


@clip("UNSAFE_red_flash_4hz.mp4", "FAIL")
def _(i):
    # red vs a gray of equal brightness: passes the luminance test, fails the red test
    return solid((0, 0, 255) if toggling(4)(i) else (GRAY_EQUAL_TO_RED,) * 3)


@clip("UNSAFE_flash_burst_mid_clip.mp4", "FAIL")
def _(i):
    # calm gray, then a 1.5 second burst of flashing from 1.5s to 3s
    if 45 <= i < 90:
        return solid((255, 255, 255) if toggling(3)(i) else (0, 0, 0))
    return solid((90, 90, 90))


def make_demo(path, seconds=20):
    """A longer, more realistic clip for demos: a moving scene with a white
    strobe burst at 6-8s and a red strobe burst at 13-15s."""
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    yy, xx = np.mgrid[0:H, 0:W]
    for i in range(FPS * seconds):
        t = i / FPS
        f = np.zeros((H, W, 3), np.uint8)
        f[..., 0] = (80 + 60 * np.sin(xx / 40 + t)).astype(np.uint8)      # drifting blue gradient
        f[..., 1] = (60 + 40 * np.sin(yy / 30 - t * 0.7)).astype(np.uint8)
        f[..., 2] = 50
        cx = int(W / 2 + 100 * np.sin(t * 0.8))
        cv2.circle(f, (cx, H // 2), 30, (200, 220, 240), -1)              # moving ball
        if 6 <= t < 8 and (i // 3) % 2 == 0:
            f[:] = 255
        if 13 <= t < 15:
            f[:] = (0, 0, 255) if (i // 4) % 2 == 0 else (GRAY_EQUAL_TO_RED,) * 3
        vw.write(f)
    vw.release()


def main(out_dir="test_clips"):
    os.makedirs(out_dir, exist_ok=True)
    for name, (fn, expected) in CLIPS.items():
        write(os.path.join(out_dir, name), fn)
        print(f"{expected:8s} {name}")
    make_demo(os.path.join(out_dir, "UNSAFE_demo_20s.mp4"))
    print(f"{'FAIL':8s} UNSAFE_demo_20s.mp4")


if __name__ == "__main__":
    main(*sys.argv[1:])
