"""GitHub の Releases に載せる本文を、リリースノート（docs/release-X.Y.md）から作る。
文書の中の相対リンク（docs/ からの場所）を、タグの場所の URL に直す（Releases の本文では相対リンクが開けないため）。

  uv run python tools/release_notes.py 1.1.0 > /tmp/notes.md
  gh release create v1.1.0 --title "twinsim 1.1.0" --notes-file /tmp/notes.md
"""

import re
import sys
from pathlib import Path

REPO = "https://github.com/fujisawa-yoshihiko/twinsim"
DOCS = Path(__file__).resolve().parents[1] / "docs"


def body(version, lang=""):
    major_minor = ".".join(version.split(".")[:2])
    src = DOCS / f"release-{major_minor}{'.en' if lang == 'en' else ''}.md"
    text = src.read_text(encoding="utf-8")
    tag = f"v{version}"

    def fix(m):
        label, target = m.group(1), m.group(2)
        if re.match(r"^(https?:|#|mailto:)", target):
            return m.group(0)
        path, _, anchor = target.partition("#")
        url = f"{REPO}/blob/{tag}/" + str(Path("docs", path)).replace("\\", "/")
        url = re.sub(r"/docs/\.\./", "/", url)
        return f"[{label}]({url}{'#' + anchor if anchor else ''})"

    return re.sub(r"\[([^\]]*)\]\(([^)\s]+)\)", fix, text)


if __name__ == "__main__":
    print(body(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""))
