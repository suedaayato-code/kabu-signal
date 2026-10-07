"""
build.py
=========
ダッシュボード(site/)を作り、必要なときだけ Discord に通知する。発注はしない。

    python build.py                  # site/ を生成。新しいシグナルがあれば通知
    python build.py --no-notify      # 通知しない(手元での確認用)
    python build.py --test-notify    # 通知の疎通確認だけ(Webhook の設定確認用)
    python build.py --defer-notify notify.json   # 通知内容をファイルに書くだけ(公開後に送る)
    python build.py --send notify.json           # 書いておいた通知を送る

GitHub Actions では、ページの公開が終わってから通知を送る(通知を開いたら古いページ、を避ける)。

通知するのは次のときだけ(同じ内容を毎日は送らない):
  - 監視銘柄で「急落」「売られ過ぎ」「高値から-20%」が今日新しく点灯した
  - 月の最初の営業日(モメンタム順位の見直し日)
前回の状態はファイルに残さず、前営業日のデータから再計算して比べる(クラウド実行でも状態を持たない)。
最終データが今日の日付でない日(祝日など)は通知しない。
"""

import argparse
import io
import json
import logging
import os
import sys
from datetime import datetime
from typing import List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import yaml

from kabusignal import discord, icon, momentum, page
from kabusignal.data import fetch_close, fetch_universe
from kabusignal.indicators import (
    SIGNAL_BY_KEY, active_signals, dip_wait_vs_monthly, forward_stats, indicator_frame, snapshot,
)
from kabusignal.universe import NIKKEI225, name_of

ROOT = os.path.dirname(os.path.abspath(__file__))
logger = logging.getLogger("kabusignal")


def build_item(entry: dict) -> Optional[dict]:
    close = fetch_close(entry["ticker"])
    if close is None or len(close) < 260:
        logger.error(f"{entry['ticker']}: データが取得できないか短すぎます")
        return None
    frame = indicator_frame(close)
    tail = frame.tail(252)
    return {
        "ticker": entry["ticker"],
        "name": entry.get("name", entry["ticker"]),
        "years": len(frame) / 252,
        "snapshot": snapshot(frame),
        "active": active_signals(frame),
        "active_prev": active_signals(frame, days_ago=1),
        "stats": forward_stats(frame),
        "dipwait": [r for r in (dip_wait_vs_monthly(frame, k) for k in ("dd10", "dd20", "oversold")) if r],
        "spark_close": [float(v) for v in tail["close"]],
        "spark_ma200": [None if v != v else float(v) for v in tail["close"] / (1 + tail["ma200_dev"])],
    }


def new_alerts(items: List[dict]) -> List[str]:
    lines = []
    for i in items:
        new = [k for k in i["active"] if k not in i["active_prev"] and SIGNAL_BY_KEY[k].notify]
        if new:
            lines.append(f"{i['name']}: " + " / ".join(SIGNAL_BY_KEY[k].name for k in new))
    return lines


def monthly_lines(m: dict) -> List[str]:
    lines = ["上位10: " + "、".join(f"{name_of(t)}({t[:-2]})" for t in m["monthly_top"])]
    if m["monthly_new"]:
        lines.append("先月から新しく入った: " + "、".join(name_of(t) for t in m["monthly_new"]))
    if m["monthly_out"]:
        lines.append("15位圏外に落ちた(持っていれば売り候補): " + "、".join(name_of(t) for t in m["monthly_out"]))
    return lines


def todo_list(items: List[dict], m: Optional[dict]) -> List[str]:
    todo = []
    for i in items:
        hot = [SIGNAL_BY_KEY[k].name for k in i["active"] if SIGNAL_BY_KEY[k].notify]
        if hot:
            todo.append(f"{i['name']}: {' / '.join(hot)}。積立はそのまま続け、余裕資金があれば追加を検討")
    if m and m["is_month_start"]:
        todo.append("今日は月初の見直し日です。個別株は下のモメンタム順位で入れ替えを確認")
        todo += monthly_lines(m)
    elif m and m["month_start"]:
        todo.append(f"個別株の入れ替えは月1回(今月は {m['month_start']} に実施済み)。次は来月最初の営業日")
    if not todo or all(t.startswith("個別株の入れ替えは") for t in todo):
        todo.insert(0, "新しくやることはありません。eMAXIS Slim の毎月積立を続けるだけで大丈夫です")
    return todo


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "site"))
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--test-notify", action="store_true")
    ap.add_argument("--no-momentum", action="store_true")
    ap.add_argument("--defer-notify", metavar="FILE", help="通知を送らず、内容を FILE に書く")
    ap.add_argument("--send", metavar="FILE", help="--defer-notify で書いた通知を送る")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    with io.open(os.path.join(ROOT, "config.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    title = cfg.get("site_title", "買い時チェック")
    site_url = cfg.get("site_url")

    if args.send:
        if not os.path.exists(args.send):
            print("送る通知はありません")
            return 0
        with io.open(args.send, encoding="utf-8") as f:
            msg = json.load(f)
        return 0 if discord.send(msg["title"], msg["lines"], msg.get("link")) else 1

    if args.test_notify:
        ok = discord.send(f"{title}: 通知テスト", ["この通知が届いていれば設定は完了です。"], site_url)
        print("通知テスト: " + ("送信しました" if ok else "失敗(ログを確認)"))
        return 0 if ok else 1

    items = [i for i in (build_item(e) for e in cfg.get("watchlist", [])) if i]
    m = None
    mcfg = cfg.get("momentum") or {}
    if mcfg.get("enabled", True) and not args.no_momentum:
        prices = fetch_universe(list(NIKKEI225))
        if len(prices) >= 150:
            m = momentum.build(prices, float(mcfg.get("budget_per_stock", 300000)))
        else:
            logger.error(f"日経225のデータが {len(prices)} 銘柄しか取れなかったため、順位を出しません")

    os.makedirs(args.out, exist_ok=True)
    with io.open(os.path.join(args.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(page.render(items, m, todo_list(items, m), title))
    with io.open(os.path.join(args.out, "manifest.webmanifest"), "w", encoding="utf-8") as f:
        f.write(page.manifest(title))
    for size in (180, 512):
        with open(os.path.join(args.out, f"icon-{size}.png"), "wb") as f:
            f.write(icon.png(size))
    print(f"生成: {os.path.join(args.out, 'index.html')}")

    if not items:
        return 1

    # 通知
    today = datetime.now(page.JST).strftime("%Y-%m-%d")
    last = items[0]["snapshot"]["date"]
    alerts = new_alerts(items)
    sections = []
    if alerts:
        sections += ["**新しいシグナル**(積立は続け、余裕資金の追加を検討)"] + alerts
    if m and m["is_month_start"]:
        sections += ["**月初の見直し日です**(個別株モメンタム・eMAXIS Slim の積立確認)"] + monthly_lines(m)
    for s in sections:
        print("  " + s)
    if last != today:
        print(f"最終データが {last} で今日({today})ではないため、通知しません(休場日など)")
    elif not sections:
        print("通知する新しい内容はありません")
    elif args.defer_notify:
        with io.open(args.defer_notify, "w", encoding="utf-8") as f:
            json.dump({"title": title, "lines": sections, "link": site_url}, f, ensure_ascii=False)
        print(f"通知内容を {args.defer_notify} に書きました(公開後に --send で送る)")
    elif not args.no_notify:
        discord.send(title, sections, site_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
