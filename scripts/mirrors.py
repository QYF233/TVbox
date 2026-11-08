#!/usr/bin/env python3
"""生成订阅地址的镜像清单，并逐个实测可用性。

输出 dist/mirrors.json，供可视化页面展示「哪个地址现在能打开」。
仓库标识取 GITHUB_REPOSITORY，本地运行则回退到 git remote。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import http_get  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist" / "mirrors.json"

FILES = ["official.json", "tvbox.json", "list.json"]


def detect_repo() -> str:
    env = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if env and "/" in env:
        return env
    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        match = re.search(r"[:/]([\w.\-]+)/([\w.\-]+?)(?:\.git)?$", url)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
    except Exception:
        pass
    return "TVboxorg/TVbox"


def channels(repo: str, filename: str) -> list[dict]:
    raw = f"https://raw.githubusercontent.com/{repo}/main/dist/{filename}"
    return [
        {
            "name": "raw",
            "label": "GitHub Raw（国内多不可达）",
            "url": raw,
        },
        {
            "name": "jsdelivr-fastly",
            "label": "jsDelivr Fastly（国内通常可用）",
            "url": f"https://fastly.jsdelivr.net/gh/{repo}@main/dist/{filename}",
        },
        {
            "name": "jsdelivr",
            "label": "jsDelivr（国内常被墙）",
            "url": f"https://cdn.jsdelivr.net/gh/{repo}@main/dist/{filename}",
        },
        {
            "name": "gh-proxy",
            "label": "gh-proxy 代理",
            "url": f"https://gh-proxy.com/{raw}",
        },
        {
            "name": "ghproxy-net",
            "label": "ghproxy.net 代理",
            "url": f"https://ghproxy.net/{raw}",
        },
    ]


def main() -> int:
    repo = detect_repo()
    print(f"repo: {repo}")

    result: dict = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": repo,
        "files": {},
    }

    for filename in FILES:
        rows = []
        for ch in channels(repo, filename):
            started = time.time()
            ok, status, body, err = http_get(ch["url"], timeout=20)
            rows.append({
                **ch,
                "ok": bool(ok),
                "status": status,
                "size": len(body) if ok else 0,
                "ms": int((time.time() - started) * 1000),
                "error": err[:80] if err else "",
            })
            flag = "OK " if ok else "BAD"
            print(f"  [{flag}] {filename:14s} {ch['name']:16s} "
                  f"{status} {len(body) if ok else 0}B")
        result["files"][filename] = rows

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    reachable = sum(1 for rows in result["files"].values() for r in rows if r["ok"])
    total = sum(len(rows) for rows in result["files"].values())
    print(f"wrote {OUT} reachable={reachable}/{total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
