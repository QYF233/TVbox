#!/usr/bin/env python3
"""从一批 TVBox 接口地址中发现可用的 CMS 站点，汇成站点池。

用法：
    python3 scripts/discover_cms.py --urls urls.json --out cms_pool.json

流程：
  1. 并发请求每个地址，解析成配置
  2. 提取 type=0/1/4 且 api 为 http(s) 的站点（纯 maccms 接口，不依赖 jar）
  3. 按 api 去重
  4. 逐个请求 ?ac=videolist&pg=1，能返回影片列表的才算可用
  5. 输出站点池，供 merge.py 并入 official.json

这是离线发现工具，不在 CI 里跑。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import check_cms_api, http_get, parse_config  # noqa: E402

FETCH_WORKERS = 24
CHECK_WORKERS = 16
SITE_FIELDS = ("key", "name", "type", "api", "searchable", "quickSearch",
               "filterable", "ext")


def extract_from_config(url: str) -> list[dict]:
    """请求一个地址，返回其中的 CMS 站点列表。"""
    ok, status, body, err = http_get(url, timeout=12)
    if not ok or not body:
        return []
    obj, parse_error = parse_config(body)
    if not obj:
        return []

    sites = None
    video = obj.get("video")
    if isinstance(video, dict) and isinstance(video.get("sites"), list):
        sites = video["sites"]
    if sites is None and isinstance(obj.get("sites"), list):
        sites = obj["sites"]
    if not sites:
        return []

    found: list[dict] = []
    for site in sites:
        if not isinstance(site, dict):
            continue
        if site.get("type") not in (0, 1, 4):
            continue
        api = str(site.get("api") or "").strip()
        if not api.startswith(("http://", "https://")):
            continue
        if "ac=videolist" in api or "/provide/vod" in api or "api.php" in api:
            pass  # 常见 maccms 形态，下面统一实测
        item = {field: site.get(field) for field in SITE_FIELDS if field in site}
        item["api"] = api
        item.setdefault("type", 1)
        item.setdefault("searchable", 1)
        item.setdefault("quickSearch", 1)
        item.setdefault("filterable", 1)
        item["_from"] = url
        found.append(item)
    return found


def normalize_api(api: str) -> str:
    """去掉查询串与末尾斜杠，用于去重。"""
    base = api.split("?")[0].rstrip("/")
    return base.lower()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--urls", default="urls.json", help="URL 列表文件")
    parser.add_argument("--out", default="cms_pool.json", help="输出站点池")
    parser.add_argument("--fetch-workers", type=int, default=FETCH_WORKERS)
    parser.add_argument("--check-workers", type=int, default=CHECK_WORKERS)
    args = parser.parse_args()

    urls_path = Path(args.urls)
    if not urls_path.is_file():
        print(f"missing {urls_path}", file=sys.stderr)
        return 1
    raw = json.loads(urls_path.read_text(encoding="utf-8"))
    urls = [x["url"] if isinstance(x, dict) else str(x) for x in raw]
    urls = list(dict.fromkeys(urls))
    print(f"扫描 {len(urls)} 个地址 ...", flush=True)

    started = time.time()
    configs_ok = 0
    collected: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.fetch_workers) as pool:
        futures = {pool.submit(extract_from_config, u): u for u in urls}
        done = 0
        for future in as_completed(futures):
            done += 1
            try:
                sites = future.result()
            except Exception:
                sites = []
            if sites:
                configs_ok += 1
                collected.extend(sites)
            if done % 100 == 0:
                print(f"  {done}/{len(urls)}  配置命中 {configs_ok}  "
                      f"站点 {len(collected)}", flush=True)

    print(f"抓取完成：{configs_ok} 份配置含 CMS 站点，共 {len(collected)} 条", flush=True)

    # 按 api 去重，保留首个（key/name 更完整的优先）
    unique: dict[str, dict] = {}
    for item in collected:
        key = normalize_api(item["api"])
        if not key:
            continue
        if key in unique:
            continue
        unique[key] = item
    print(f"去重后 {len(unique)} 个不同接口", flush=True)

    # 逐个实测
    print(f"实测 {len(unique)} 个接口 ...", flush=True)
    alive: list[dict] = []
    dead: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.check_workers) as pool:
        futures = {pool.submit(check_cms_api, item["api"]): item
                   for item in unique.values()}
        done = 0
        for future in as_completed(futures):
            item = futures[future]
            done += 1
            try:
                ok, videos, reason = future.result()
            except Exception as exc:
                ok, videos, reason = False, 0, str(exc)[:40]
            if ok:
                item["_videos"] = videos
                alive.append(item)
            else:
                item["_reason"] = reason
                dead.append(item)
            if done % 50 == 0:
                print(f"  {done}/{len(unique)}  可用 {len(alive)}", flush=True)

    alive.sort(key=lambda x: -(x.get("_videos") or 0))

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": str(urls_path),
        "scanned": len(urls),
        "configs_with_cms": configs_ok,
        "found": len(collected),
        "unique": len(unique),
        "alive": len(alive),
        "elapsed_sec": round(time.time() - started, 1),
        "sites": alive,
        "dead": [
            {"api": d["api"], "name": d.get("name"), "reason": d.get("_reason", "")}
            for d in dead
        ],
    }
    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n写入 {args.out}")
    print(f"  扫描 {len(urls)} / 含 CMS 配置 {configs_ok} / 去重后 {len(unique)} "
          f"/ 实测可用 {len(alive)}")
    for item in alive[:15]:
        print(f"    {item.get('name', '')[:24]:26s} {item['_videos']:3d} 条  "
              f"{item['api'][:52]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
