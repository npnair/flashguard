"""Command line: python -m flashguard VIDEO [VIDEO ...] [--out reports]"""

import argparse
import sys

from .detector import analyze_video
from .report import write_all, fmt_time


def main(argv=None):
    p = argparse.ArgumentParser(prog="flashguard",
                                description="Scan videos for flashing that can trigger photosensitive seizures.")
    p.add_argument("videos", nargs="+", help="video file(s) to scan")
    p.add_argument("--out", default="reports", help="folder for the reports (default: reports)")
    args = p.parse_args(argv)

    worst = 0
    for video in args.videos:
        def progress(done, total):
            if total:
                print(f"\r  {video}: {100 * done // total}%", end="", file=sys.stderr)

        try:
            result = analyze_video(video, progress)
        except ValueError as e:
            print(f"\n{e}", file=sys.stderr)
            worst = max(worst, 2)
            continue
        print("\r" + " " * 70 + "\r", end="", file=sys.stderr)
        paths = write_all(result, video, args.out)
        print(f"{result.verdict:8s} {video}")
        for inc in result.incidents:
            kind = "red flash" if inc.kind == "red" else "flash"
            print(f"         {fmt_time(inc.start_time)} to {fmt_time(inc.end_time)}  "
                  f"{kind}, up to {inc.peak_flashes_per_sec:g}/sec")
        print(f"         report: {paths['html']}")
        if result.verdict == "FAIL":
            worst = max(worst, 1)
    return worst


if __name__ == "__main__":
    sys.exit(main())
