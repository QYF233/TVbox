#!/usr/bin/env python3
"""Probe TVBox interface URLs from sources.yaml.

判定分层（模拟 TVBoxOSC ApiConfig）：
  - 先用 App 真实 UA `okhttp/3.15`，失败再用浏览器 UA 复测
  - 配置必须能解析成 JSON object
  - sites 必须存在，每个 site 必须含 key/type/api 且 type 为数字
  - 存在 urls 键 → 多仓，无 sites 也算有效
  - spider 非空时必须能下载、是合法 zip、MD5 与 ;md5; 声明一致
  - 返回 m3u/txt 频道表判定为直播源
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import analyze  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "sources.yaml"
OUT = ROOT / "dist" / "probe.json"
WORKERS = int(os.environ.get("PROBE_WORKERS", "8"))
RETRIES = int(os.environ.get("PROBE_RETRIES", "1"))


def load_sources(path: Path) -> list[dict]:
    """极简 YAML 读取（只覆盖本仓库结构，保持零依赖）。"""
    text = path.read_text(encoding="utf-8")
    items: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        if line.startswith("  - id:"):
            if cur:
                items.append(cur)
            cur = {"id": line.split(":", 1)[1].strip().strip('"'), "enabled": True}
            continue
        if cur is None or not line.startswith("    "):
            continue
        stripped = line.strip()
        if stripped.startswith("#") or ":" not in stripped:
            continue
        key, val = stripped.split(":", 1)
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val.startswith('"') and val.endswith('"'):
            val = val[1:-1].replace('\\"', '"')
        if key == "enabled":
            cur[key] = val.lower() == "true"
        else:
            cur[key] = val
    if cur:
        items.append(cur)
    return items


def probe_with_retry(url: str) -> dict:
    last: dict = {}
    for attempt in range(RETRIES + 1):
        result = analyze(url)
        result["attempts"] = attempt + 1
        if result["ok"]:
            return result
        last = result
        if attempt < RETRIES:
            time.sleep(1.5 * (attempt + 1))
    return last


def summarize(result: dict) -> str:
    if not result["ok"]:
        return f"DOWN {result['error'][:40]}"
    bits = [result["kind"]]
    if result["sites_valid"]:
        bits.append(f"sites={result['sites_valid']}")
    if result["multi_count"]:
        bits.append(f"multi={result['multi_count']}")
    if result["jar_status"] != "none":
        bits.append(f"jar={result['jar_status']}")
        if result["jar_md5_match"] is False:
            bits.append("md5=MISMATCH")
    if result["is_live"]:
        bits.append("live")
    return "UP " + " ".join(bits)


def main() -> int:
    sources = [s for s in load_sources(SOURCES) if s.get("enabled", True)]
    if not sources:
        print("no enabled sources in sources.yaml", file=sys.stderr)
        return 1

    print(f"probing {len(sources)} sources with {WORKERS} workers", flush=True)
    results: list[dict] = []
    started = time.time()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(probe_with_retry, s["url"]): s for s in sources}
        done = 0
        for future in as_completed(futures):
            src = futures[future]
            done += 1
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "ok": False, "status": 0, "ms": 0, "kind": "error",
                    "error": f"{type(exc).__name__}: {exc}"[:120],
                    "ua_used": "", "sites_total": 0, "sites_valid": 0,
                    "sites_bad": 0, "types": {}, "jar_status": "none",
                    "jar_url": "", "jar_note": "", "jar_md5_match": None,
                    "jar_size": 0, "multi_count": 0, "is_live": False,
                    "attempts": 0,
                }
            results.append({
                "id": src.get("id"),
                "name": src.get("name", ""),
                "group": src.get("group", ""),
                "url": src["url"],
                "desc": src.get("desc", ""),
                **result,
            })
            print(f"[{done}/{len(sources)}] {src.get('name', '')} -> {summarize(result)}",
                  flush=True)

    rank = {"pref": 0, "back": 1}
    results.sort(key=lambda x: (not x["ok"], rank.get(x.get("group"), 9),
                                x.get("id") or ""))

    up = sum(1 for x in results if x["ok"])
    jar_ok = sum(1 for x in results if x.get("jar_status") == "ok")
    multi = sum(1 for x in results if x.get("multi_count"))

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "homepage": "https://www.tvbox.org/",
        "repo": "https://github.com/TVboxorg/TVbox",
        "probe_version": 2,
        "elapsed_sec": round(time.time() - started, 1),
        "count": len(results),
        "up": up,
        "stats": {"jar_ok": jar_ok, "multi": multi},
        "items": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"\nwrote {OUT} up={up}/{len(results)} jar_ok={jar_ok} multi={multi} "
          f"in {payload['elapsed_sec']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
