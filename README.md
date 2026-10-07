# 買い時チェック (kabu-signal)

楽天証券で自分で売買するための判断材料を、平日の夕方に自動で作って iPhone で見られるようにする。
**発注はしない。投資助言ではない。**

- 画面: GitHub Pages の 1 ページ。iPhone の Safari で開き「共有 → ホーム画面に追加」でアプリのように使える
- 通知: Discord。新しいシグナルが点灯した日と、月初の見直し日だけ送る
- 計算: GitHub Actions(平日 17:00 JST)。PC の電源は不要
- 売買: 楽天証券のアプリ(iSPEED)で自分で行う。個別株は「かぶミニ」で 1 株から買える

## 何が表示されるか

| 欄 | 内容 |
|:--|:--|
| 今日やること | その日に気にすべきことだけ。何も無ければ「積立を続けるだけ」 |
| 保有チェック | 持っている個別株のコードを入れると、順位と「持ち続ける / 月初に売り候補」の目安。入力は**その端末のブラウザにだけ**保存され、どこにも送信されない |
| 監視銘柄 | 日経平均(eMAXIS Slim の代わり)・TOPIX ETF・S&P500。指標と、**各シグナルで過去に買っていたらどうだったか**(全履歴で毎回計算) |
| モメンタム順位 | 日経225 を 12-1ヶ月モメンタムで並べた順位、1株の価格、予算で買える株数 |

### 先に知っておくこと

元になった検証(非公開の stock/ リポジトリ)とこのページの実測では:
- 押し目まで現金で待つ積立は、日経平均・TOPIX・S&P500 のどれでも**大半の10年間で毎月積立に負けた**
- 「高値から-20%」で買っても、1年後リターンは平均並みか以下。急落直後(25日線から-10%)だけは平均を上回ったが、回数が少ない
- 日経225 の上位10銘柄を月1回入れ替える運用は S&P500 を上回った(年率 +31% 対 +20%)が、利益の約半分が1銘柄、最大下落 -45%

投信は毎月の積立が基本で、シグナルは「余裕資金を追加で入れるか」の参考。

## セットアップ(1回だけ)

1. **Discord の Webhook を作る**: 通知を受けたいサーバーのチャンネル → 設定 → 連携サービス → ウェブフック → 新しいウェブフック → URL をコピー
2. **GitHub に Secret として登録する**(URL はこのリポジトリのファイルには絶対に書かない):
   リポジトリの Settings → Secrets and variables → Actions → New repository secret
   名前 `DISCORD_WEBHOOK_URL`、値にコピーした URL
3. **Pages を有効にする**: Settings → Pages → Source を「GitHub Actions」
4. **動作確認**: Actions → daily → Run workflow で「Discord に通知テストを送る」にチェックして実行
5. iPhone の Safari で `https://suedaayato-code.github.io/kabu-signal/` を開き、共有 → ホーム画面に追加

## 設定を変える

[`config.yaml`](config.yaml) を編集して push する。公開リポジトリなので、保有銘柄や金額などの個人情報は書かない。

```yaml
watchlist:
  - ticker: "7203.T"       # 東証の銘柄は「証券コード.T」
    name: "トヨタ自動車"
```

## 手元で動かす

```bash
pip install -r requirements.txt
python -m pytest
python build.py --no-notify      # site/index.html を生成
```

## セキュリティ

- Webhook URL は GitHub の Secret にだけ置き、通知を送るステップにだけ渡す。Discord 以外のドメインには送らない
- ワークフローの権限は最小限。外部アクションは GitHub 公式のものだけをコミット SHA で固定
- ページは外部のスクリプト・フォント・画像を読まない(Content-Security-Policy で禁止)、検索エンジンには載せない(noindex)
- 依存パッケージはバージョンを固定(`requirements.txt`)

## データの注意

価格は Yahoo Finance(yfinance)から取得。遅延・欠損・誤りがありうる。実際に観測した破損(数日だけ10倍、
分割の未調整)は `kabusignal/data.py` で修復し、修復内容は Actions のログに残る。
