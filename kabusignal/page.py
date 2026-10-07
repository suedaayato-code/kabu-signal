"""
kabusignal/page.py
===================
スマホで見るための 1 枚の HTML(+ ホーム画面用の manifest)。

公開ページなので:
  - 外部のスクリプト・フォント・画像を一切読まない(CSP で禁止)
  - 銘柄名などの文字列は必ずエスケープし、ページ内の JSON は </script> を作れないようにする
  - 保有銘柄はページに載せない。利用者が入力した保有はその端末のブラウザ(localStorage)にだけ残る
"""

import json
from datetime import datetime, timedelta, timezone
from html import escape
from typing import List, Optional

from kabusignal.indicators import SIGNAL_BY_KEY

JST = timezone(timedelta(hours=9))

CSP = ("default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
       "img-src 'self' data:; manifest-src 'self'; base-uri 'none'; form-action 'none'")

CSS = """
:root{--bg:#f6f6f3;--card:#fff;--ink:#1c1c1a;--muted:#6b6a65;--line:#e5e4df;--up:#16794a;--down:#c0392b;
--warn:#a86200;--warnbg:#fff3dd;--accent:#2f5bd3;--chip:#edf0fa;--ma:#9a9993}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1f1f1d;--ink:#eceae4;--muted:#9c9a93;--line:#33322e;
--up:#4cc38a;--down:#ff6b5b;--warn:#f0a840;--warnbg:#3a2b10;--accent:#86a2ff;--chip:#262f4f;--ma:#77766f}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 -apple-system,"Hiragino Sans","Segoe UI",sans-serif}
main{max-width:760px;margin:0 auto;padding:16px 16px calc(48px + env(safe-area-inset-bottom))}
header{padding-top:env(safe-area-inset-top)}
h1{font-size:22px;margin:8px 0 0}h2{font-size:18px;margin:28px 0 10px}
.sub{color:var(--muted);font-size:13px}
nav{display:flex;gap:8px;overflow-x:auto;margin:12px -16px 0;padding:0 16px 4px;scrollbar-width:none}
nav a{flex:none;font-size:14px;padding:6px 12px;border-radius:99px;background:var(--card);border:1px solid var(--line);color:var(--ink);text-decoration:none}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:12px;min-width:0}
.todo li{margin:6px 0}.todo{margin:0;padding-left:20px}
.card h3{margin:0;font-size:16px}.tk{color:var(--muted);font-size:12px}
.row{display:flex;justify-content:space-between;align-items:baseline;gap:12px}
.price{font-size:26px;font-weight:650;font-variant-numeric:tabular-nums}
.up{color:var(--up)}.down{color:var(--down)}.dim{color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.chip{font-size:12px;padding:2px 9px;border-radius:99px;background:var(--chip)}
.chip.alert{background:var(--warnbg);color:var(--warn);font-weight:650}
.kv{display:grid;grid-template-columns:1fr auto;gap:2px 12px;font-size:14px;font-variant-numeric:tabular-nums}
.kv span:nth-child(odd){color:var(--muted)}.kv span:nth-child(even){text-align:right}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:13px}
th,td{padding:6px 4px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}
th:first-child,td:first-child{text-align:left}th{color:var(--muted);font-weight:500;font-size:12px}
td .nm{font-weight:600}td .cd{color:var(--muted);font-size:12px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
details{margin-top:10px}summary{cursor:pointer;color:var(--accent);font-size:14px;padding:4px 0}
svg{display:block;width:100%;height:auto;margin:6px 0 2px}.legend{font-size:11px;color:var(--muted)}
.note{border-left:4px solid var(--accent)}.note p{margin:6px 0;font-size:14px}
.warnbox{border-left:4px solid var(--warn)}
input{font:inherit;width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink)}
button{font:inherit;margin-top:8px;padding:8px 16px;border:0;border-radius:10px;background:var(--accent);color:#fff}
.status-keep{color:var(--up);font-weight:600}.status-sell{color:var(--down);font-weight:600}.status-none{color:var(--warn);font-weight:600}
footer{margin-top:32px;font-size:12px;color:var(--muted)}
"""

SCRIPT = """
(function(){
  var KEY='kabusignal.holdings';
  var data=JSON.parse(document.getElementById('rank-data').textContent);
  var byCode={};data.rows.forEach(function(r){byCode[r.code]=r;});
  var input=document.getElementById('holdings');
  var out=document.getElementById('holdings-result');
  function load(){try{return localStorage.getItem(KEY)||'';}catch(e){return '';}}
  function save(v){try{localStorage.setItem(KEY,v);}catch(e){}}
  function cell(tr,text,cls){var td=document.createElement('td');td.textContent=text;if(cls)td.className=cls;tr.appendChild(td);}
  function render(){
    var codes=input.value.split(/[\\s,、]+/).map(function(s){return s.replace(/\\.T$/i,'').trim();})
      .filter(function(s){return /^[0-9A-Z]{4}$/i.test(s);});
    out.textContent='';
    if(!codes.length){out.textContent='証券コードを入力すると、モメンタム順位と「持ち続けるか」の目安を表示します。';return;}
    var t=document.createElement('table');var h=document.createElement('tr');
    ['銘柄','順位','目安'].forEach(function(x){var th=document.createElement('th');th.textContent=x;h.appendChild(th);});
    t.appendChild(h);
    codes.forEach(function(c){
      var r=byCode[c.toUpperCase()];var tr=document.createElement('tr');
      if(!r){cell(tr,c);cell(tr,'—');cell(tr,'日経225の順位対象外','status-none');}
      else{cell(tr,r.code+' '+r.name);cell(tr,r.rank+'位');
        if(r.rank<=data.exit_rank)cell(tr,'持ち続ける(15位以内)','status-keep');
        else cell(tr,'月初に売り候補(15位圏外)','status-sell');}
      t.appendChild(tr);
    });
    out.appendChild(t);
  }
  input.value=load();render();
  document.getElementById('holdings-save').addEventListener('click',function(){save(input.value);render();});
  input.addEventListener('input',render);
})();
"""


def pct(v: Optional[float], digits: int = 1, sign: bool = True) -> str:
    if v is None:
        return "—"
    return f"{v * 100:+.{digits}f}%" if sign else f"{v * 100:.{digits}f}%"


def cls(v: Optional[float]) -> str:
    if v is None:
        return ""
    return "up" if v > 0 else "down" if v < 0 else ""


def yen(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:,.0f}"


def sparkline(closes: List[float], ma: List[Optional[float]], w: int = 320, h: int = 80) -> str:
    vals = [v for v in closes + ma if v is not None]
    if len(closes) < 2 or not vals:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0

    def segs(series):
        out, cur = [], []
        for i, v in enumerate(series):
            if v is None:
                if cur:
                    out.append(cur)
                cur = []
                continue
            cur.append(f"{i / (len(series) - 1) * w:.1f},{h - 3 - (v - lo) / span * (h - 6):.1f}")
        if cur:
            out.append(cur)
        return out

    body = "".join(f'<polyline points="{" ".join(s)}" fill="none" stroke="var(--ma)" stroke-width="1.2" '
                   f'stroke-dasharray="3 3"/>' for s in segs(ma))
    body += "".join(f'<polyline points="{" ".join(s)}" fill="none" stroke="currentColor" stroke-width="1.6"/>'
                    for s in segs(closes))
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="直近1年の終値と200日線">{body}</svg>'
            f'<div class="legend">直近1年 実線: 終値 / 点線: 200日線</div>')


def _card(item: dict) -> str:
    s = item["snapshot"]
    chips = "".join(
        f'<span class="chip{" alert" if SIGNAL_BY_KEY[k].notify else ""}">{escape(SIGNAL_BY_KEY[k].name)}</span>'
        for k in item["active"]) or '<span class="chip">シグナルなし</span>'
    kv = [("前日比", pct(s["chg_1d"]), cls(s["chg_1d"])), ("1ヶ月", pct(s["chg_1m"]), cls(s["chg_1m"])),
          ("52週高値から", pct(s["dd_52w"]), cls(s["dd_52w"])), ("25日線乖離", pct(s["ma25_dev"]), cls(s["ma25_dev"])),
          ("200日線乖離", pct(s["ma200_dev"]), cls(s["ma200_dev"])),
          ("RSI14", "—" if s["rsi14"] is None else f'{s["rsi14"]:.0f}', "")]
    kv_html = "".join(f'<span>{k}</span><span class="{c}">{v}</span>' for k, v, c in kv)
    stats = "".join(
        f'<tr><td>{escape(r.label)}</td><td>{r.episodes if i else "—"}</td>'
        f'<td class="{cls(r.mean_1y)}">{pct(r.mean_1y)}</td><td>{pct(r.win_1y, 0, False)}</td></tr>'
        for i, r in enumerate(item["stats"]))
    dips = "".join(
        f'<tr><td>{escape(d.signal)}まで待つ</td><td>{pct(d.wait_won, 0, False)}</td>'
        f'<td class="{cls(d.median_diff)}">{pct(d.median_diff)}</td></tr>' for d in item["dipwait"])
    dip_html = (f'<p class="sub">毎月同額を入金し、押し目待ちは点灯まで現金で貯めて一括投入(10年ずつ比較)。</p>'
                f'<div class="scroll"><table><tr><th>やり方</th><th>毎月積立に勝った割合</th><th>差(中央値)</th></tr>'
                f'{dips}</table></div>') if dips else '<p class="sub">履歴が10年余りに満たないため、積立比較はありません。</p>'
    return f"""
<div class="card">
  <h3>{escape(item["name"])}</h3><div class="tk">{escape(item["ticker"])} ・ {s["date"]} 終値 ・ 履歴 {item["years"]:.0f}年</div>
  <div class="row"><div class="price">{yen(s["close"])}</div></div>
  <div class="chips">{chips}</div>
  {sparkline(item["spark_close"], item["spark_ma200"])}
  <div class="kv">{kv_html}</div>
  <details><summary>このシグナルで買ったら、過去はどうだったか</summary>
    <p class="sub">各条件の日に買った場合の1年後リターン(全履歴・配当なし・サンプルは重複あり)。
    「いつ買っても」より良くなければ、その条件を待つ意味はありません。</p>
    <div class="scroll"><table><tr><th>条件</th><th>回数</th><th>1年後平均</th><th>プラス率</th></tr>{stats}</table></div>
    {dip_html}
  </details>
</div>"""


def _rank_rows(rows: List[dict]) -> str:
    return "".join(
        f'<tr><td>{r["rank"]}. <span class="nm">{escape(r["name"])}</span><br>'
        f'<span class="cd">{escape(r["code"])} ・ {escape(r["sector"])}</span></td>'
        f'<td class="{cls(r["mom"])}">{pct(r["mom"], 0)}</td><td>{yen(r["price"])}</td>'
        f'<td>{r["shares"]:,}株</td><td class="{cls(r["dd_52w"])}">{pct(r["dd_52w"], 0)}</td></tr>'
        for r in rows)


def _momentum(m: Optional[dict]) -> str:
    if not m:
        return '<div class="card warnbox"><p>今回は日経225のデータを取得できなかったため、順位を表示していません。</p></div>'
    head = (f'<tr><th>銘柄</th><th>12-1</th><th>1株</th><th>{yen(m["budget"])}円で</th><th>高値から</th></tr>')
    top, rest = m["rows"][:20], m["rows"][20:]
    return f"""
<div class="card note">
  <p>直近1ヶ月を除く過去1年の上昇率の順位です({m["as_of"]}・{m["universe"]}銘柄)。元の10年検証では、
  <b>上位10銘柄を等金額で持ち、月初に1回だけ見直し、15位より下に落ちたら売る</b>運用が S&P500 を上回りました
  (年率 +31% 対 +20%)。ただし利益の約半分は1銘柄によるもので、最大の下落は -45% でした。</p>
  <p>楽天証券の「かぶミニ」なら1株から買えます。「{yen(m["budget"])}円で」は1銘柄の予算で買える株数です。</p>
</div>
<div class="card scroll"><table>{head}{_rank_rows(top)}</table>
<details><summary>21位以下も表示</summary><div class="scroll"><table>{head}{_rank_rows(rest)}</table></div></details></div>"""


def render(items: List[dict], momentum: Optional[dict], todo: List[str], site_title: str) -> str:
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    rank_json = json.dumps({
        "exit_rank": 15,
        "rows": [{"code": r["code"], "name": r["name"], "rank": r["rank"]} for r in (momentum or {}).get("rows", [])],
    }, ensure_ascii=False).replace("<", "\\u003c")
    todo_html = "".join(f"<li>{escape(t)}</li>" for t in todo)
    cards = "".join(_card(i) for i in items)
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<meta name="referrer" content="no-referrer">
<meta name="robots" content="noindex,nofollow">
<meta name="theme-color" content="#2f5bd3">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="{escape(site_title)}">
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="icon-180.png">
<link rel="icon" href="icon-180.png">
<title>{escape(site_title)}</title>
<style>{CSS}</style></head><body><main>
<header><h1>{escape(site_title)}</h1><div class="sub">更新 {now}(日本時間)・平日の夕方に自動更新</div>
<nav><a href="#todo">今日やること</a><a href="#holdings-sec">保有チェック</a><a href="#watch">監視銘柄</a><a href="#rank">モメンタム順位</a></nav></header>

<h2 id="todo">今日やること</h2>
<div class="card"><ul class="todo">{todo_html}</ul></div>

<h2 id="holdings-sec">保有チェック</h2>
<div class="card">
  <p class="sub">持っている個別株の証券コードを入力(例: 5803, 6981)。入力内容はこの端末のブラウザにだけ保存され、どこにも送信されません。</p>
  <input id="holdings" inputmode="numeric" autocomplete="off" placeholder="5803, 6981">
  <button id="holdings-save" type="button">この端末に保存</button>
  <div id="holdings-result" class="scroll" style="margin-top:10px"></div>
</div>

<h2 id="watch">監視銘柄</h2>
{cards}

<h2 id="rank">個別株: モメンタム順位</h2>
{_momentum(momentum)}

<div class="card note"><p><b>このページについて:</b> 過去の実績では、相場の上げ下げで「買い時」を当てる方法に根拠は出ていません。
押し目まで現金で待つ積立は、日経平均・TOPIX・S&P500 のどれでも大半の10年間で毎月積立に負けました。
投信は毎月の積立を続け、シグナルは「余裕資金を追加で入れるか」の参考にしてください。</p></div>
<footer>データ: Yahoo Finance(遅延・誤りの可能性あり)。投資助言ではありません。売買は自己判断で、楽天証券のアプリから行ってください。</footer>
</main>
<script type="application/json" id="rank-data">{rank_json}</script>
<script>{SCRIPT}</script>
</body></html>"""


def manifest(site_title: str) -> str:
    return json.dumps({
        "name": site_title, "short_name": site_title[:12], "start_url": "./", "scope": "./",
        "display": "standalone", "background_color": "#f6f6f3", "theme_color": "#2f5bd3",
        "icons": [{"src": "icon-180.png", "sizes": "180x180", "type": "image/png"},
                  {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"}],
    }, ensure_ascii=False, indent=2)
