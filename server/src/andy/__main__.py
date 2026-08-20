from __future__ import annotations

import uvicorn

from .http import WireGuardHTTPProtocol


def main() -> None:
    uvicorn.run(
        "andy.app:app",
        host="0.0.0.0",
        port=8900,
        http=WireGuardHTTPProtocol,
    )


if __name__ == "__main__":
    main()
