"""
kabusignal/data.py
===================
Yahoo Finance(yfinance)からの日足取得と、既知のデータ破損の修復。

yfinance の価格には実際に次の破損がある(どちらも修復しないと指標が壊れる):
  - 数日だけ価格が10倍/10分の1になる(1306 の 2026-03-30、1655 の 2022-02-08)
  - 分割が未調整のまま段差が残る(1306 の 2015-01-05 に1日で -90%)
修復した内容は必ずログに残し、黙って書き換えない。
"""

import logging
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# 1日でこれ以上動いたら、未調整の分割・併合とみなす。東証の値幅制限では
# 1営業日に半値以下・2.5倍以上にはならない
SPLIT_DOWN, SPLIT_UP = 0.4, 2.5
# ユニバースの検査で、これを超える1日の値動きがある銘柄はデータ破損として外す
MAX_DAILY_MOVE = 0.60


def repair_scale_glitches(close: pd.Series, window: int = 21,
                          tolerance: float = 0.25) -> Tuple[pd.Series, List[str]]:
    """周辺の中央値と比べて、比率がちょうど10倍/10分の1の日だけを戻す。"""
    c = close.copy()
    ratio = c / c.rolling(window, center=True, min_periods=5).median()
    notes = []
    for factor, fix in ((10.0, 0.1), (0.1, 10.0)):
        mask = ((ratio - factor).abs() < factor * tolerance).fillna(False)
        for d in c.index[mask]:
            before = float(c.loc[d])
            c.loc[d] = before * fix
            notes.append(f"{d.date()}: {before:,.2f} → {c.loc[d]:,.2f} (桁ずれを修復)")
    return c, notes


def repair_split_jumps(close: pd.Series) -> Tuple[pd.Series, List[str]]:
    """分割調整漏れの段差より前の価格を、段差の比率で割り戻す。"""
    c = close.copy()
    notes = []
    ratio = c / c.shift(1)
    for d in ratio[(ratio < SPLIT_DOWN) | (ratio > SPLIT_UP)].index[::-1]:
        r = float(c.loc[d] / c.shift(1).loc[d])
        c.loc[c.index < d] *= r
        notes.append(f"{d.date()}: 前日比 x{r:.3f} の段差を分割とみなし、それ以前の価格を補正")
    return c, notes


def _close_of(df: Optional[pd.DataFrame]) -> Optional[pd.Series]:
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    if "Close" not in df.columns:
        return None
    c = pd.to_numeric(df["Close"], errors="coerce").dropna()
    c = c[c > 0]
    return c.astype(float) if not c.empty else None


def fetch_close(ticker: str, period: str = "max") -> Optional[pd.Series]:
    """1銘柄の終値(修復済み)。取得できなければ None。"""
    import yfinance as yf
    try:
        c = _close_of(yf.download(ticker, period=period, progress=False, auto_adjust=True))
    except Exception as e:
        logger.error(f"{ticker}: 取得に失敗 ({e})")
        return None
    if c is None:
        logger.error(f"{ticker}: データが空")
        return None
    c, n1 = repair_scale_glitches(c)
    c, n2 = repair_split_jumps(c)
    for n in n1 + n2:
        logger.warning(f"  {ticker} {n}")
    return c


def fetch_universe(tickers: List[str], period: str = "2y", chunk: int = 40) -> Dict[str, pd.Series]:
    """
    複数銘柄の終値を一括取得する。1日で60%超動いた日がある銘柄は、修復後も
    破損とみなして外す(件数はログに出す)。
    """
    import yfinance as yf
    out: Dict[str, pd.Series] = {}
    dropped = []
    for i in range(0, len(tickers), chunk):
        batch = tickers[i:i + chunk]
        try:
            raw = yf.download(batch, period=period, progress=False, auto_adjust=True,
                              group_by="ticker", threads=True)
        except Exception as e:
            logger.warning(f"一括取得に失敗 ({batch[0]}〜): {e}")
            raw = None
        for t in batch:
            c = None
            if raw is not None and not raw.empty and isinstance(raw.columns, pd.MultiIndex) \
                    and t in raw.columns.get_level_values(0):
                c = _close_of(raw[t])
            if c is None:
                dropped.append(t)
                continue
            c, _ = repair_scale_glitches(c)
            if len(c) < 260 or (c.pct_change().abs() > MAX_DAILY_MOVE).any():
                dropped.append(t)
                continue
            out[t] = c
    if dropped:
        logger.warning(f"{len(dropped)}銘柄を除外(取得失敗・履歴不足・データ破損): {', '.join(dropped[:10])}")
    return out
