"""
kabusignal/indicators.py
=========================
手動売買の判断材料になる指標と、その指標が過去にどう効いたかの実測。

「買いシグナル」を出すだけでは、そのシグナルに意味があるかが分からない。
そこで各シグナルについて、同じ銘柄の全履歴で
  - シグナルが出ていた日に買った場合の 1年後リターン(平均・中央値・プラスだった割合)
  - 毎月積立と「シグナルが出るまで現金で待ってから入れる積立」の10年比較
を毎回計算し直して、指標と並べて表示する。数字は固定値として埋め込まない
(データが伸びれば結果も変わるため)。

2026-10 時点の実測(1970〜): 日経平均では「高値から-20%」で買った1年後リターンは
全日平均より悪く、押し目待ち積立は10年窓の6割強で毎月積立に負けた。
S&P500 では深い下落後のリターンは高かったが、押し目待ち積立は9割近い窓で負けた。
つまりこれらは「待つための合図」ではなく、余裕資金を追加で入れるかの参考に留まる。
"""

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

TRADING_DAYS = 252
MONTH = 21


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder の RSI。"""
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def indicator_frame(close: pd.Series) -> pd.DataFrame:
    """日次の指標。行=日付。"""
    return pd.DataFrame({
        "close": close,
        "chg_1d": close.pct_change(),
        "chg_1m": close.pct_change(MONTH),
        "dd_52w": close / close.rolling(TRADING_DAYS, min_periods=60).max() - 1,
        "ma25_dev": close / close.rolling(25).mean() - 1,
        "ma200_dev": close / close.rolling(200).mean() - 1,
        "rsi14": rsi(close),
        "mom_12_1": close.shift(MONTH) / close.shift(TRADING_DAYS) - 1,
    })


@dataclass(frozen=True)
class Signal:
    key: str
    name: str
    rule: Callable[[pd.DataFrame], pd.Series]
    notify: bool          # 点灯したら通知するか


SIGNALS: List[Signal] = [
    Signal("panic", "急落: 25日線から-10%以下", lambda f: f["ma25_dev"] <= -0.10, True),
    Signal("oversold", "売られ過ぎ: RSI14 < 30", lambda f: f["rsi14"] < 30, True),
    Signal("dd20", "高値から-20%以上", lambda f: f["dd_52w"] <= -0.20, True),
    Signal("dd10", "高値から-10%以上", lambda f: f["dd_52w"] <= -0.10, False),
    Signal("below200", "200日線より下", lambda f: f["ma200_dev"] < 0, False),
    Signal("overbought", "過熱: RSI14 > 70", lambda f: f["rsi14"] > 70, False),
]
SIGNAL_BY_KEY: Dict[str, Signal] = {s.key: s for s in SIGNALS}


def active_signals(frame: pd.DataFrame, days_ago: int = 0) -> List[str]:
    """最終日(days_ago=1 なら前営業日)に点灯しているシグナルのキー。"""
    last = frame.iloc[[-1 - days_ago]]
    return [s.key for s in SIGNALS if bool(s.rule(last).fillna(False).iloc[0])]


def snapshot(frame: pd.DataFrame) -> dict:
    row = frame.iloc[-1]
    out = {k: (None if pd.isna(v) else float(v)) for k, v in row.items()}
    out["date"] = frame.index[-1].strftime("%Y-%m-%d")
    return out


# ══════════════════════════════════════════════════════════
#  過去実績
# ══════════════════════════════════════════════════════════

@dataclass
class ForwardStats:
    label: str
    share_of_days: float      # 全日数のうちシグナルが出ていた割合
    episodes: int             # 点灯の回数(連続点灯は1回)
    n: int                    # 1年後が観測できた日数
    mean_1y: Optional[float]
    median_1y: Optional[float]
    win_1y: Optional[float]   # 1年後プラスだった割合


def _stats(label: str, mask: pd.Series, fwd: pd.Series) -> ForwardStats:
    mask = mask.fillna(False).astype(bool)
    r = fwd[mask].dropna()
    episodes = int((mask & ~mask.shift(1, fill_value=False)).sum())
    if r.empty:
        return ForwardStats(label, float(mask.mean()), episodes, 0, None, None, None)
    return ForwardStats(label, float(mask.mean()), episodes, len(r),
                        float(r.mean()), float(r.median()), float((r > 0).mean()))


def forward_stats(frame: pd.DataFrame, horizon: int = TRADING_DAYS) -> List[ForwardStats]:
    """全日(基準)と各シグナルの、horizon 営業日後リターン。サンプルは重なっている点に注意。"""
    c = frame["close"]
    fwd = c.shift(-horizon) / c - 1
    rows = [_stats("全日(いつ買っても)", pd.Series(True, index=frame.index), fwd)]
    rows += [_stats(s.name, s.rule(frame), fwd) for s in SIGNALS]
    return rows


@dataclass
class DipWaitResult:
    signal: str
    windows: int
    wait_won: float           # 押し目待ちが毎月積立を上回った窓の割合
    median_diff: float        # 最終資産の差(待ち / 毎月 - 1)の中央値


def dip_wait_vs_monthly(frame: pd.DataFrame, signal_key: str,
                        years: int = 10, step: int = MONTH) -> Optional[DipWaitResult]:
    """
    毎月同額を入金する2つのやり方を、years 年のローリング窓で比べる。
      毎月積立 : 入金日にそのまま買う
      押し目待ち: 入金は現金で貯め、シグナルが点灯した日に貯めた現金を全額入れる
                  (窓の終わりまで点灯しなければ現金のまま)
    """
    c = frame["close"].to_numpy(dtype=float)
    sig = SIGNAL_BY_KEY[signal_key].rule(frame).fillna(False).to_numpy(dtype=bool)
    n, w = len(c), TRADING_DAYS * years
    if n < w + step:
        return None
    # next_true[i] = i 以降で最初にシグナルが点灯した日(無ければ n)
    next_true = np.full(n + 1, n)
    for i in range(n - 1, -1, -1):
        next_true[i] = i if sig[i] else next_true[i + 1]
    diffs = []
    for start in range(0, n - w + 1, step):
        end = start + w
        dep = np.arange(start, end, MONTH)
        final = c[end - 1]
        monthly = final * np.sum(1.0 / c[dep])
        nxt = next_true[dep]
        hit = nxt < end
        waited = final * np.sum(1.0 / c[nxt[hit]]) + np.count_nonzero(~hit)
        diffs.append(waited / monthly - 1)
    d = np.array(diffs)
    return DipWaitResult(SIGNAL_BY_KEY[signal_key].name, len(d),
                         float(np.mean(d > 0)), float(np.median(d)))
