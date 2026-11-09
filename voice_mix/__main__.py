"""python -m voice_mix 启动本地服务。"""

from __future__ import annotations

import sys


def main() -> int:
    import uvicorn
    port = 8777
    for i, a in enumerate(sys.argv):
        if a == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
    print(f"\n  voice-mix 已启动 → http://127.0.0.1:{port}\n")
    uvicorn.run("voice_mix.server:app", host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
