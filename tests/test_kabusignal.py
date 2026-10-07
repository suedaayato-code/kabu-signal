"""
指標・データ修復・モメンタム順位・通知・ページ生成の検証。ネットワークには触れない。
"""

import json
import os
import re

import numpy as np
import pandas as pd

from build import new_alerts, todo_list
from kabusignal import discord, icon, momentum, page
from kabusignal.data import repair_scale_glitches, repair_split_jumps
from kabusignal.indicators import (
    active_signals, dip_wait_vs_monthly, forward_stats, indicator_frame, rsi,
)


def series(values, start="2000-01-03"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


# ── 指標 ────────────────────────────────────────────

def test_rsi_extremes():
    assert rsi(series(np.linspace(100, 200, 60))).iloc[-1] > 99
    assert rsi(series(np.linspace(200, 100, 60))).iloc[-1] < 1


def test_crash_lights_panic_today_but_not_a_year_earlier():
    c = series(list(np.linspace(100, 150, 300)) + list(np.linspace(150, 100, 20)))
    f = indicator_frame(c)
    assert {"panic", "oversold", "dd20"} <= set(active_signals(f))
    assert "panic" not in active_signals(f, days_ago=25)


def test_forward_stats_baseline_is_positive_in_an_uptrend():
    rows = forward_stats(indicator_frame(series(100 * np.exp(np.linspace(0, 1, 800)))))
    assert rows[0].mean_1y > 0 and rows[0].win_1y == 1.0


def test_waiting_for_a_dip_that_never_comes_loses():
    r = dip_wait_vs_monthly(indicator_frame(series(100 * np.exp(np.linspace(0, 2, 252 * 12)))), "dd10")
    assert r is not None and r.wait_won == 0.0 and r.median_diff < -0.3


# ── データ修復 ──────────────────────────────────────

def test_split_jump_is_scaled_out_but_real_moves_are_kept():
    fixed, notes = repair_split_jumps(series([1000.0] * 5 + [100.0] * 5))
    assert len(notes) == 1 and np.allclose(fixed, 100.0)
    real = series([100, 80, 70, 90, 120])
    same, notes = repair_split_jumps(real)
    assert notes == [] and same.equals(real)


def test_few_day_scale_glitch_is_restored():
    v = [100.0 + i * 0.1 for i in range(40)]
    v[20] /= 10
    fixed, notes = repair_scale_glitches(series(v))
    assert len(notes) == 1 and abs(fixed.iloc[20] - v[19]) < 1


# ── モメンタム ─────────────────────────────────────

def test_momentum_ranks_trend_first_and_reports_month_changes():
    idx = pd.bdate_range("2024-01-01", periods=420)
    up = pd.Series(100 * np.exp(np.linspace(0, 1, 420)), index=idx)
    flat = pd.Series(100.0, index=idx)
    prices = {"7203.T": up, "6758.T": flat * 1.0, "9984.T": up[::-1].set_axis(idx)}
    m = momentum.build(prices, budget_per_stock=300000)
    assert m["rows"][0]["ticker"] == "7203.T"
    assert m["rows"][0]["shares"] == int(300000 // m["rows"][0]["price"])
    assert m["rows"][0]["code"] == "7203"


# ── 通知 ───────────────────────────────────────────

def test_only_newly_lit_notifiable_signals_are_alerted():
    items = [{"name": "A", "active": ["dd10", "dd20"], "active_prev": ["dd10"]},
             {"name": "B", "active": ["dd10"], "active_prev": []},          # dd10 は通知対象外
             {"name": "C", "active": ["panic"], "active_prev": ["panic"]}]  # 昨日から点灯中
    assert new_alerts(items) == ["A: 高値から-20%以上"]


def test_quiet_day_says_keep_saving():
    todo = todo_list([{"name": "A", "active": []}], None)
    assert "積立を続ける" in todo[0]


def test_webhook_url_must_be_discord():
    assert discord.is_valid_webhook("https://discord.com/api/webhooks/123/abc-DEF_9")
    for bad in ("", "http://discord.com/api/webhooks/1/a", "https://evil.example/api/webhooks/1/a",
                "https://discord.com.evil.example/api/webhooks/1/a", "https://discord.com/api/webhooks/1/a?x=1"):
        assert not discord.is_valid_webhook(bad)


def test_webhook_payload_disables_mentions(monkeypatch):
    p = discord.payload("t", ["@everyone"])
    assert p["allowed_mentions"] == {"parse": []}
    monkeypatch.delenv(discord.ENV, raising=False)
    assert discord.send("t", ["x"]) is False       # 未設定なら送らない


# ── ページ ─────────────────────────────────────────

def test_page_escapes_names_and_cannot_break_out_of_the_json_script():
    m = {"as_of": "2026-10-01", "universe": 1, "budget": 300000, "is_month_start": False,
         "month_start": "2026-10-01", "monthly_top": [], "monthly_new": [], "monthly_out": [],
         "rows": [{"rank": 1, "ticker": "1.T", "code": "1", "name": "</script><img src=x>", "sector": "<b>",
                   "mom": 0.1, "price": 100.0, "shares": 3000, "dd_52w": -0.1}]}
    html = page.render([], m, ["<i>todo</i>"], "t")
    assert "<img src=x>" not in html and "<i>todo</i>" not in html
    assert "&lt;/script&gt;&lt;img src=x&gt;" in html and "&lt;b&gt;" in html
    data = re.search(r'<script type="application/json" id="rank-data">(.*?)</script>', html, re.S).group(1)
    assert json.loads(data)["rows"][0]["name"] == "</script><img src=x>"
    assert "Content-Security-Policy" in html and "default-src 'none'" in html


def test_icon_is_a_valid_png():
    b = icon.png(32)
    assert b.startswith(b"\x89PNG\r\n\x1a\n") and b"IEND" in b
