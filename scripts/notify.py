#!/usr/bin/env python3
"""接口状态变更告警。

数据来源：dist/changes.json（由 scripts/history.py 生成）
仅在存在状态翻转时发送；未配置任何通道则静默跳过。

支持的通道（任选其一，可用环境变量配置）：
  ALERT_WEBHOOK        通用 webhook，POST JSON {"text": "..."}
  SERVERCHAN_KEY       Server酱 https://sctapi.ftqq.com/<key>.send
  TELEGRAM_BOT_TOKEN   配合 TELEGRAM_CHAT_ID
  ALERT_ON             changes（默认）| down（只推送掉线）
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGES = ROOT / "dist" / "changes.json"
PROBE = ROOT / "dist" / "probe.json"
TIMEOUT = 15


def post_json(url: str, payload: dict) -> tuple[bool, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8",
                 "User-Agent": "TVbox-probe-notify/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"[:80]


def post_form(url: str, fields: dict) -> tuple[bool, str]:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "TVbox-probe-notify/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"[:80]


def build_message(changes: list[dict], up: int, total: int) -> tuple[str, str]:
    downs = [c for c in changes if c["change"] == "down"]
    ups = [c for c in changes if c["change"] == "up"]
    title = f"TVBox 接口 {len(downs)} 掉线 / {len(ups)} 恢复"
    lines = [f"当前可用 {up}/{total}", ""]
    for c in downs:
        reason = f"  ({c['reason'][:50]})" if c.get("reason") else ""
        lines.append(f"[DOWN] {c['name']}{reason}")
    for c in ups:
        lines.append(f"[UP]   {c['name']} 已恢复")
    return title, "\n".join(lines)


def main() -> int:
    if not CHANGES.is_file():
        print("no changes.json, skip", file=sys.stderr)
        return 0
    data = json.loads(CHANGES.read_text(encoding="utf-8"))
    changes = data.get("items") or []
    if not changes:
        print("no status change, skip notify")
        return 0

    only_down = os.environ.get("ALERT_ON", "changes").lower() == "down"
    if only_down:
        changes = [c for c in changes if c["change"] == "down"]
        if not changes:
            print("no down change, skip notify")
            return 0

    up = total = 0
    if PROBE.is_file():
        probe = json.loads(PROBE.read_text(encoding="utf-8"))
        total = probe.get("count") or 0
        up = probe.get("up") or 0

    title, body = build_message(changes, up, total)
    sent = 0
    failed = 0

    webhook = os.environ.get("ALERT_WEBHOOK", "").strip()
    if webhook:
        ok, msg = post_json(webhook, {"text": f"{title}\n\n{body}"})
        print(f"webhook: {msg}")
        sent += 1 if ok else 0
        failed += 0 if ok else 1

    serverchan = os.environ.get("SERVERCHAN_KEY", "").strip()
    if serverchan:
        url = f"https://sctapi.ftqq.com/{serverchan}.send"
        ok, msg = post_form(url, {"title": title, "desp": body})
        print(f"serverchan: {msg}")
        sent += 1 if ok else 0
        failed += 0 if ok else 1

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if tg_token and tg_chat:
        url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
        ok, msg = post_json(url, {"chat_id": tg_chat,
                                  "text": f"{title}\n\n{body}",
                                  "disable_web_page_preview": True})
        print(f"telegram: {msg}")
        sent += 1 if ok else 0
        failed += 0 if ok else 1

    if sent == 0 and failed == 0:
        print("no alert channel configured, skip")
        return 0
    print(f"notified: {sent} ok, {failed} failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
