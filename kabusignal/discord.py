"""
kabusignal/discord.py
======================
Discord の Webhook へ通知する。

Webhook URL は「知っている人なら誰でもそのチャンネルに投稿できる」鍵なので:
  - コードにもリポジトリにも書かない。環境変数 DISCORD_WEBHOOK_URL(GitHub の Secret)からだけ読む
  - ログやエラーメッセージに URL を出さない
  - Discord の公式ドメイン以外には送らない(設定ミスで別のサーバーへ送るのを防ぐ)
  - @everyone などのメンションは無効化する
"""

import logging
import os
import re
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

ENV = "DISCORD_WEBHOOK_URL"
_ALLOWED = re.compile(r"^https://(discord\.com|discordapp\.com|ptb\.discord\.com|canary\.discord\.com)"
                      r"/api/webhooks/\d+/[\w-]+$")


def is_valid_webhook(url: str) -> bool:
    return bool(_ALLOWED.match(url or ""))


def payload(title: str, lines: List[str], link: Optional[str] = None) -> dict:
    embed = {"title": title[:256], "description": "\n".join(lines)[:4000], "color": 0x2F5BD3}
    if link:
        embed["url"] = link
    return {"embeds": [embed], "allowed_mentions": {"parse": []}}


def send(title: str, lines: List[str], link: Optional[str] = None, timeout: float = 10.0) -> bool:
    url = os.getenv(ENV, "").strip()
    if not url:
        logger.info("DISCORD_WEBHOOK_URL が未設定のため、通知は送りません")
        return False
    if not is_valid_webhook(url):
        logger.error("DISCORD_WEBHOOK_URL が Discord の Webhook URL の形式ではありません(送信しません)")
        return False
    try:
        r = requests.post(url, json=payload(title, lines, link), timeout=timeout)
    except requests.RequestException as e:
        logger.error(f"Discord への通知に失敗: {type(e).__name__}")   # 例外文字列には URL が含まれうる
        return False
    if r.status_code >= 300:
        logger.error(f"Discord への通知に失敗: HTTP {r.status_code}")
        return False
    return True
