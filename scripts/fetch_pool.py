#!/usr/bin/env python3
"""从 GitHub 拉取最新的 CMS 站点池（走 gh-proxy 镜像，国内可直连）。"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

MIRRORS = [
    "https://gh-proxy.com/https://raw.githubusercontent.com/QYF233/TVbox/main/cms_pool.json",
    "https://ghproxy.net/https://raw.githubusercontent.com/QYF233/TVbox/main/cms_pool.json",
]
OUT = Path(__file__).resolve().parents[1] / "cms_pool.json"


def main() -> int:
    for url in MIRRORS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "okhttp/3.15"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                body = resp.read()
            data = json.loads(body.decode("utf-8"))
            sites = data.get("sites") or []
            if not sites:
                print(f"empty pool from {url[:40]}", file=sys.stderr)
                continue
            OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
            print(f"fetched {len(sites)} sites ({len(body)} bytes) from {url.split('//')[1][:24]}")
            return 0
        except Exception as exc:
            print(f"fail {type(exc).__name__}: {str(exc)[:60]}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
