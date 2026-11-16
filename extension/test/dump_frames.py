"""Decode a clip into small RGBA frames for the JavaScript parity test (Python side of the test)."""
import sys, json, struct
import cv2, numpy as np
path, out = sys.argv[1], sys.argv[2]
cap = cv2.VideoCapture(path)
fps = cap.get(cv2.CAP_PROP_FPS) or 30
W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
aw = min(160, W); ah = max(1, round(H * aw / W))
frames = []
while True:
    ok, f = cap.read()
    if not ok: break
    small = cv2.resize(f, (aw, ah), interpolation=cv2.INTER_AREA)      # resized in sRGB, like a browser canvas
    rgba = cv2.cvtColor(small, cv2.COLOR_BGR2RGBA)
    frames.append(rgba.tobytes())
with open(out, 'wb') as fh:
    fh.write(struct.pack('<IIIf', aw, ah, len(frames), fps))
    for fr in frames: fh.write(fr)
