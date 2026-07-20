"""`python -m web` — serve the live front-end (regenerates preview.html too).

    .venv/bin/python -m web            # http://127.0.0.1:8080
    .venv/bin/python -m web --preview  # only (re)write web/preview.html
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the artisan repo root importable (keel, registry, eval, ... live there).
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from web.pages import build_preview  # noqa: E402


def main() -> None:
    preview_path = build_preview(REPO_ROOT / "web" / "preview.html")
    if "--preview" in sys.argv:
        print(f"wrote {preview_path}")
        return

    import uvicorn

    from web.app import app

    port = int(os.environ.get("PORT", 8080))
    print(f"EuEarth · ARTISAN  ->  http://127.0.0.1:{port}   (preview: {preview_path})")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
