"""
kabusignal/momentum.py
=======================
日経225 を 12-1ヶ月モメンタム(直近1ヶ月を除く過去1年のリターン)で並べる。

元の検証(stock/ リポジトリ、2017-2026、資金300万、翌寄り約定・スリッページ0.15%):
  上位10銘柄を等金額で持ち、月1回、順位が15位より下に落ちた銘柄を入れ替える
    → CAGR +31% (S&P500 ETF 買い持ちは +20%)、最大下落 -45%
  ただし損益の46%がフジクラ1銘柄。上位5銘柄を除くと S&P500 に負ける。
"""

from typing import Dict, List, Optional

import pandas as pd

from kabusignal.universe import name_of, sector_of

LOOKBACK = 252
SKIP = 21
TOP_N = 10
EXIT_RANK = 15        # 保有銘柄がこの順位より下に落ちたら売る


def momentum_12_1(panel: pd.DataFrame) -> pd.DataFrame:
    return panel.shift(SKIP) / panel.shift(LOOKBACK) - 1


def ranking(panel: pd.DataFrame, as_of: pd.Timestamp) -> List[str]:
    """as_of 時点の順位(良い順)。スコアが出ない銘柄は入らない。"""
    row = momentum_12_1(panel).loc[as_of].dropna()
    return list(row.sort_values(ascending=False).index)


def month_start(index: pd.DatetimeIndex, months_back: int = 0) -> Optional[pd.Timestamp]:
    """最終日から数えて months_back ヶ月前の、その月の最初の営業日。"""
    months = index.to_period("M")
    target = months[-1] - months_back
    hit = index[months == target]
    return hit[0] if len(hit) else None


def build(prices: Dict[str, pd.Series], budget_per_stock: float) -> dict:
    panel = pd.DataFrame(prices).sort_index().ffill(limit=5)
    as_of = panel.index[-1]
    ranked = ranking(panel, as_of)
    mom = momentum_12_1(panel).loc[as_of]
    high = panel.rolling(LOOKBACK, min_periods=60).max().loc[as_of]

    # 月次の入れ替えは「今月の最初の営業日」の順位で判断する。比較対象は先月の最初の営業日
    this_month = month_start(panel.index, 0)
    last_month = month_start(panel.index, 1)
    rank_now = ranking(panel, this_month) if this_month is not None else ranked
    rank_prev = ranking(panel, last_month) if last_month is not None else []

    rows = []
    for i, t in enumerate(ranked, 1):
        price = float(panel.at[as_of, t])
        rows.append({
            "rank": i, "ticker": t, "code": t.replace(".T", ""), "name": name_of(t),
            "sector": sector_of(t), "mom": float(mom[t]), "price": price,
            "shares": int(budget_per_stock // price), "dd_52w": price / float(high[t]) - 1,
        })
    return {
        "as_of": as_of.strftime("%Y-%m-%d"),
        "rows": rows,
        "budget": budget_per_stock,
        "universe": panel.shape[1],
        "is_month_start": this_month == as_of,
        "month_start": None if this_month is None else this_month.strftime("%Y-%m-%d"),
        "monthly_top": rank_now[:TOP_N],
        "monthly_new": [t for t in rank_now[:TOP_N] if t not in rank_prev[:TOP_N]] if rank_prev else [],
        "monthly_out": [t for t in rank_prev[:TOP_N] if t not in rank_now[:EXIT_RANK]],
    }
