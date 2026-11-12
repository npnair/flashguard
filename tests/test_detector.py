import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from flashguard import analyze_video  # noqa: E402
import make_test_clips  # noqa: E402


@pytest.fixture(scope="session")
def clip_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("clips")
    make_test_clips.main(str(d))
    return d


@pytest.mark.parametrize("name", [
    pytest.param(n, marks=pytest.mark.xfail(reason=make_test_clips.KNOWN_LIMITS[n], strict=True))
    if n in make_test_clips.KNOWN_LIMITS else n
    for n in make_test_clips.CLIPS
])
def test_verdict(clip_dir, name):
    expected = make_test_clips.CLIPS[name][1]
    result = analyze_video(str(clip_dir / name))
    assert result.verdict == expected, (
        f"{name}: got {result.verdict}, general peak {result.general_tps.max()}, "
        f"red peak {result.red_tps.max()}"
    )


def test_red_flash_is_reported_as_red(clip_dir):
    result = analyze_video(str(clip_dir / "UNSAFE_red_flash_4hz.mp4"))
    kinds = {i.kind for i in result.incidents}
    assert kinds == {"red"}


def test_burst_is_located_in_time(clip_dir):
    result = analyze_video(str(clip_dir / "UNSAFE_flash_burst_mid_clip.mp4"))
    assert len(result.incidents) == 1
    inc = result.incidents[0]
    # burst runs 1.5s to 3.0s
    assert 1.2 <= inc.start_time <= 2.0
    assert 2.7 <= inc.end_time <= 3.6
