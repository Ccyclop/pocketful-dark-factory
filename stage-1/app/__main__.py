"""Entry point: `python -m app` listens on 0.0.0.0:$PORT (default 8080)."""
from __future__ import annotations

import uvicorn

from .config import load_settings
from .main import create_app


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        workers=1,
        loop="uvloop",
        http="httptools",
        access_log=False,
        backlog=1024,
    )


if __name__ == "__main__":
    main()
