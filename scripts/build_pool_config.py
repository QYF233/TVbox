#!/usr/bin/env python3
"""把验证过的 CMS 站点池编译成可直接填入 TVBox 的 official.json。

不依赖 probe/merge，只需 cms_pool.json。用于在 OpenWrt 等机器上单独出配置。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "cms_pool.json"
OUT = ROOT / "dist" / "official.json"

NETDISK = re.compile(
    r"网盘|云盘|夸克|天翼|115|alist|小雅|迅雷|uc网盘|百度网盘"
    r"|4k|原盘|盘库|盘搜|emby|webdav", re.I)
FIELDS = ("key", "name", "type", "api", "searchable", "quickSearch", "filterable")


def slug(text: str, fallback: str) -> str:
    key = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", text or "").strip("_")[:40]
    return f"cms_{key}" if key else fallback


def main() -> int:
    if not POOL.is_file():
        print(f"missing {POOL}", file=sys.stderr)
        return 1
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    sites = [s for s in (pool.get("sites") or []) if isinstance(s, dict)]

    picked: list[tuple[int, dict]] = []
    seen_api: set[str] = set()
    skipped_netdisk = 0
    skipped_empty = 0
    for item in sites:
        api = str(item.get("api") or "")
        if not api.startswith(("http://", "https://")):
            continue
        name = str(item.get("name") or "")
        if NETDISK.search(name):
            skipped_netdisk += 1
            continue
        # 分类齐全但电视剧和电影都空 → 空壳站，点进去什么都没有
        drama = int(item.get("_drama") or 0)
        movie = int(item.get("_movie") or 0)
        if drama == 0 and movie == 0:
            skipped_empty += 1
            continue
        sig = api.split("?")[0].rstrip("/").lower()
        if sig in seen_api:
            continue
        seen_api.add(sig)
        site = {f: item[f] for f in FIELDS if item.get(f) is not None}
        site["type"] = 1
        site.setdefault("searchable", 1)
        site.setdefault("quickSearch", 1)
        site.setdefault("filterable", 1)
        site["key"] = slug(str(item.get("key") or name), "cms_site")
        site["name"] = name or site["key"]
        score = int(item.get("_score") or 0)
        if score <= 0:
            videos = item.get("_videos") or 0
            score = 30 + int(min(videos / 30.0, 1.0) * 10)
        picked.append((score, site))

    picked.sort(key=lambda x: (-x[0], x[1]["name"]))
    final = [s for _, s in picked]

    config = {
        "wallpaper": "",
        "sites": final,
        "parses": [],
        "lives": [],
        "warning": "本地验证生成；仅含实测可用的 CMS 接口，无网盘、无加密 jar。",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_pool": str(POOL.name),
        "pool_playable": sum(1 for s in sites if s.get("_playable")),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    playable = sum(1 for _, s in picked if True)
    print(f"wrote {OUT}")
    print(f"  池内 {len(sites)} → 输出 {len(final)} 站点"
          f"（剔除网盘 {skipped_netdisk}，剔除空壳站 {skipped_empty}）")
    for score, site in picked[:10]:
        print(f"    {score:3d}  {site['name'][:28]:30s} {site['api'][:46]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
