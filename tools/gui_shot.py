"""GUI の確かめ（画面を撮る）。サーバー（python -m twinsim serve）を起動してから:
  uv run --no-project --with playwright python tools/gui_shot.py [出力の場所]
（初回は uv run --no-project --with playwright python -m playwright install firefox）
設定・結果のタブを撮り、カメラのドラッグが設定に反映されるか・ブラウザのエラーがないかを確かめる。
"""

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright


async def main(out):
    out.mkdir(parents=True, exist_ok=True)
    token = (Path.home() / ".config/twinsim/token").read_text().strip()
    async with async_playwright() as p:
        b = await p.firefox.launch()
        pg = await b.new_page(viewport={"width": 1600, "height": 1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(f"http://localhost:8770/?token={token}")
        await pg.wait_for_function("document.querySelector('#template').options.length > 0", timeout=20000)
        await pg.wait_for_timeout(2000)
        await pg.screenshot(path=str(out / "gui_settings.png"))
        moved = None
        if await pg.evaluate("S.spec.cameras.length"):
            pos = await pg.evaluate("""() => { const c = resolveCam(S.spec.cameras[0]); const p = W2C(c.eye[0], c.eye[1]);
                const r = canvas.getBoundingClientRect(); return [r.left + p[0] * r.width / canvas.width, r.top + p[1] * r.height / canvas.height, c.eye]; }""")
            await pg.mouse.move(pos[0], pos[1])
            await pg.mouse.down()
            await pg.mouse.move(pos[0] + 40, pos[1] + 20, steps=4)
            await pg.mouse.up()
            spec = json.loads(await pg.input_value("#spec-json"))
            moved = (pos[2], spec["cameras"][0].get("eye"))
        await pg.click("button[data-tab=results]")
        await pg.wait_for_timeout(1500)
        if await pg.query_selector("#runs li"):
            await pg.click("#runs li")
            await pg.wait_for_timeout(2500)
        await pg.screenshot(path=str(out / "gui_results.png"), full_page=True)
        await b.close()
    print(json.dumps({"camera_drag": moved, "page_errors": errs, "out": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "dt-data/twinsim/screens")))
