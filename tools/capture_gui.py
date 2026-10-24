"""報告のページ用に、GUI の画面を撮る（静止画と、操作の流れの動画）。GUI のサーバーが動いているときに使う。MOPF・描画は起動しない（見るだけ）。

  uv run --group gui-test python tools/capture_gui.py <出力の場所> [--run office_gate_ev] [--url http://localhost:8770]

ブラウザは playwright の Firefox（`uv run --group gui-test playwright install firefox`）。トークンは config.TOKEN_FILE から読み、表示しない。
出力（日本語 ja・英語 en の 2 組）: gui_{settings,results,pred,links,mopf}_<言語>.jpg と、操作の流れの gui_tour_<言語>.mp4・.gif。
"""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from twinsim import config

W, H = 1440, 900


def tour(browser, a, out, token, lang):
    """1 つの言語で画面をひととおり見て、静止画（gui_<名前>_<言語>.jpg）と動画（gui_tour_<言語>）を残す。"""
    tmp = Path(tempfile.mkdtemp())
    ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(tmp), record_video_size={"width": W, "height": H})
    page = ctx.new_page()
    page.goto(f"{a.url}/?token={token}")
    page.wait_for_timeout(2500)
    page.select_option("#lang", lang)
    page.select_option("#template", a.run if page.locator(f"#template option[value='{a.run}']").count() else "office_gate_ev")
    page.wait_for_timeout(2000)
    shot = lambda name: page.screenshot(path=out / f"gui_{name}_{lang}.jpg", type="jpeg", quality=85)
    shot("settings")
    page.click("button[data-tab=results]")
    page.wait_for_timeout(1000)
    page.click(f"#runs li[data-id='{a.run}']")
    page.wait_for_timeout(3000)
    shot("results")
    v = page.locator("#pred-video")
    v.scroll_into_view_if_needed()
    page.evaluate("([el, t]) => { el.currentTime = t; el.play(); }", [v.element_handle(), a.pred_start_s])
    page.wait_for_timeout(8000)
    shot("pred")
    page.mouse.wheel(0, 700)
    page.wait_for_timeout(1500)
    shot("links")
    page.click("button[data-tab=mopf]")
    page.wait_for_timeout(3000)
    shot("mopf")
    page.select_option("#lang", "ja")  # 次に開く人のために戻す（言語はブラウザに残る）
    video = page.video.path()
    ctx.close()
    webm = Path(video)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(webm), "-vf", "scale=1200:-2", "-c:v", "libx264", "-crf", "30",
                    "-preset", "slow", "-pix_fmt", "yuv420p", str(out / f"gui_tour_{lang}.mp4")], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(webm), "-vf",
                    "fps=4,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];"
                    "[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle", str(out / f"gui_tour_{lang}.gif")], check=True)
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--run", default="office_gate_ev")
    ap.add_argument("--url", default="http://localhost:8770")
    ap.add_argument("--pred-start-s", type=float, default=174.0, help="予測の動画を見せ始める秒")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    token = Path(config.TOKEN_FILE).read_text().strip()
    with sync_playwright() as p:
        browser = p.firefox.launch()
        for lang in ("ja", "en"):
            tour(browser, a, out, token, lang)
        browser.close()
    for f in sorted(out.glob("gui_*")):
        print(f.name, f.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
