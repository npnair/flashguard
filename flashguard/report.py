"""Write results as CSV, JSON and a self-contained HTML report (no external libraries)."""

from __future__ import annotations

import csv
import html
import json
import os

import numpy as np

from .detector import AnalysisResult, MAX_TRANSITIONS, CAUTION_TRANSITIONS


def fmt_time(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m)}:{s:05.2f}"


def write_csv(result: AnalysisResult, path: str):
    status = result.frame_status()
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame", "time_sec", "avg_luminance", "general_flashes_per_sec",
                    "red_flashes_per_sec", "peak_flash_area", "status"])
        for i in range(result.frame_count):
            w.writerow([i, round(float(result.times[i]), 3), round(float(result.avg_luminance[i]), 4),
                        result.general_tps[i] / 2, result.red_tps[i] / 2,
                        round(float(result.peak_area[i]), 3), status[i]])


def summary(result: AnalysisResult, source: str) -> dict:
    return {
        "file": os.path.basename(source),
        "verdict": result.verdict,
        "duration_sec": round(result.duration, 2),
        "fps": round(result.fps, 2),
        "resolution": f"{result.width}x{result.height}",
        "peak_general_flashes_per_sec": float(result.general_tps.max()) / 2,
        "peak_red_flashes_per_sec": float(result.red_tps.max()) / 2,
        "incidents": [
            {"type": i.kind, "start": i.start_time, "end": i.end_time,
             "peak_flashes_per_sec": i.peak_flashes_per_sec}
            for i in result.incidents
        ],
    }


def write_json(result: AnalysisResult, source: str, path: str):
    with open(path, "w") as f:
        json.dump(summary(result, source), f, indent=2)


def _chart_svg(result: AnalysisResult) -> str:
    W, H = 900, 260
    L, R, T, B = 48, 16, 16, 34
    pw, ph = W - L - R, H - T - B
    dur = max(result.duration, 1e-6)
    g = result.general_tps / 2
    r = result.red_tps / 2
    ymax = max(5.0, float(max(g.max(initial=0), r.max(initial=0))) + 1)

    def x(t):
        return L + pw * t / dur

    def y(v):
        return T + ph * (1 - v / ymax)

    # downsample to at most ~1 point per pixel, keeping the max in each bucket
    def path(vals):
        n = len(vals)
        step = max(1, n // pw)
        pts = []
        for i in range(0, n, step):
            v = float(vals[i:i + step].max())
            pts.append(f"{x(result.times[i]):.1f},{y(v):.1f}")
        return "M" + " L".join(pts)

    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Flashes per second over time">']
    for inc in result.incidents:
        parts.append(f'<rect x="{x(inc.start_time):.1f}" y="{T}" width="{max(2, x(inc.end_time) - x(inc.start_time)):.1f}" '
                     f'height="{ph}" class="band"/>')
    for v in range(0, int(ymax) + 1):
        parts.append(f'<line x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                     f'<text x="{L - 8}" y="{y(v) + 4:.1f}" class="lab" text-anchor="end">{v}</text>')
    lim = MAX_TRANSITIONS / 2
    parts.append(f'<line x1="{L}" x2="{W - R}" y1="{y(lim):.1f}" y2="{y(lim):.1f}" class="limit"/>'
                 f'<text x="{W - R}" y="{y(lim) - 6:.1f}" class="lab" text-anchor="end">limit: 3 flashes/sec</text>')
    ticks = 8
    for k in range(ticks + 1):
        t = dur * k / ticks
        anchor = "start" if k == 0 else "end" if k == ticks else "middle"
        parts.append(f'<text x="{x(t):.1f}" y="{H - 10}" class="lab" text-anchor="{anchor}">{fmt_time(t)}</text>')
    parts.append(f'<path d="{path(g)}" class="lg"/>')
    if r.max(initial=0) > 0:
        parts.append(f'<path d="{path(r)}" class="lr"/>')
    parts.append("</svg>")
    return "".join(parts)


def write_html(result: AnalysisResult, source: str, path: str):
    s = summary(result, source)
    verdict = s["verdict"]
    blurb = {
        "PASS": "No flashing above the WCAG limits was found.",
        "CAUTION": "Flashing comes close to the limit (2.5 to 3 flashes per second) but doesn't go over.",
        "FAIL": "This video has flashing above the WCAG limits that could trigger photosensitive seizures.",
    }[verdict]

    if result.incidents:
        rows = "".join(
            f"<tr><td>{fmt_time(i.start_time)} to {fmt_time(i.end_time)}</td>"
            f"<td>{'Red flash' if i.kind == 'red' else 'General flash'}</td>"
            f"<td>{i.peak_flashes_per_sec:g}</td></tr>"
            for i in result.incidents)
        table = ("<table><thead><tr><th>When</th><th>Type</th><th>Peak flashes/sec</th></tr></thead>"
                 f"<tbody>{rows}</tbody></table>")
    else:
        table = "<p class='muted'>No incidents.</p>"

    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FlashGuard report: {html.escape(s['file'])}</title>
<style>
:root {{ --bg:#fafaf9; --fg:#1c1917; --muted:#78716c; --line:#e7e5e4; --card:#fff;
        --pass:#15803d; --caution:#b45309; --fail:#b91c1c; --blue:#2563eb; --red:#dc2626; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#1c1917; --fg:#f5f5f4; --muted:#a8a29e; --line:#44403c; --card:#292524;
          --pass:#4ade80; --caution:#fbbf24; --fail:#f87171; --blue:#60a5fa; --red:#f87171; }} }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui, sans-serif; }}
main {{ max-width:960px; margin:0 auto; padding:32px 20px; }}
h1 {{ font-size:22px; margin:0 0 4px; }}
.muted {{ color:var(--muted); }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:20px; margin-top:16px; }}
.verdict {{ font-weight:700; font-size:28px; }}
.PASS {{ color:var(--pass); }} .CAUTION {{ color:var(--caution); }} .FAIL {{ color:var(--fail); }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-top:12px; }}
.stat b {{ display:block; font-size:20px; }}
svg .grid {{ stroke:var(--line); }} svg .lab {{ fill:var(--muted); font-size:11px; }}
svg .limit {{ stroke:var(--fail); stroke-dasharray:5 4; }}
svg .band {{ fill:var(--fail); opacity:.12; }}
svg .lg {{ fill:none; stroke:var(--blue); stroke-width:1.8; }}
svg .lr {{ fill:none; stroke:var(--red); stroke-width:1.8; }}
.legend span {{ margin-right:16px; }} .sw {{ display:inline-block; width:12px; height:3px; vertical-align:middle; margin-right:6px; }}
table {{ width:100%; border-collapse:collapse; }} th,td {{ text-align:left; padding:8px; border-bottom:1px solid var(--line); }}
</style></head><body><main>
<h1>FlashGuard report</h1>
<div class="muted">{html.escape(s['file'])} · {s['resolution']} · {s['fps']} fps · {fmt_time(s['duration_sec'])}</div>

<div class="card">
  <div class="verdict {verdict}">{verdict}</div>
  <div>{blurb}</div>
  <div class="stats">
    <div class="stat"><span class="muted">Peak general flashes/sec</span><b>{s['peak_general_flashes_per_sec']:g}</b></div>
    <div class="stat"><span class="muted">Peak red flashes/sec</span><b>{s['peak_red_flashes_per_sec']:g}</b></div>
    <div class="stat"><span class="muted">Incidents</span><b>{len(result.incidents)}</b></div>
  </div>
</div>

<div class="card">
  <strong>Flashes per second over time</strong>
  <div class="legend muted"><span><i class="sw" style="background:var(--blue)"></i>General (brightness)</span>
  <span><i class="sw" style="background:var(--red)"></i>Red</span>
  <span><i class="sw" style="background:var(--fail);opacity:.3;height:10px"></i>Failing section</span></div>
  {_chart_svg(result)}
</div>

<div class="card"><strong>Incidents</strong>{table}</div>

<p class="muted">Screening tool based on the WCAG 2.x three flashes threshold (general and red flash, 25% of a 10 degree
field of view). It is not a certified Harding test and not medical advice.</p>
</main></body></html>"""
    with open(path, "w") as f:
        f.write(doc)


def write_all(result: AnalysisResult, source: str, out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(source))[0]
    paths = {
        "html": os.path.join(out_dir, f"{stem}_report.html"),
        "csv": os.path.join(out_dir, f"{stem}_frames.csv"),
        "json": os.path.join(out_dir, f"{stem}_summary.json"),
    }
    write_html(result, source, paths["html"])
    write_csv(result, paths["csv"])
    write_json(result, source, paths["json"])
    return paths
