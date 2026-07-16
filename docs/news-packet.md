# Work News Packet 仕様(Phase 2a)

このドキュメントは、ChatGPT WorkがGitHub Issueへ登録するニュース事実
パック(Work News Packet)の形式と、Termux側(`scripts/import_work_news.py`)
の取り込み仕様を定める。実装の全体像は `docs/design.md` を参照。

## 目的

ChatGPT WorkがGitHub Issueへ登録したニュース事実パックをTermuxで取得し、
既存の `claude -p` 変換パイプライン(`prompts/translate.md`)へ渡せるように
する。Workデータがない場合やGitHub取得に失敗した場合は、既存のNHK RSS
収集(`scripts/collect.py`)へフォールバックする。

## Issue単位

「Workの収集1回」につき1 Issueを作成する。1記事=1 Issue、1日=1 Issue
ではない。

- タイトル: `[Work News] YYYY-MM-DD HH:MM JST`
- ラベル: `work-news`
- 状態: `open`
- 本文: JSONコードブロック(` ```json ... ``` `)を**1つだけ**含む。
  コードブロック外の文章は、Termux側では一切実行・指示として解釈しない。
  `scripts/import_work_news.py` はコードブロック内のテキストに対して
  `json.loads` 以外の解釈(eval・exec・シェル実行等)を行わない。

## パケット構造(トップレベル)

```json
{
  "packetVersion": 1,
  "collectionRunId": "一意な収集ID",
  "collectedAt": "ISO 8601形式",
  "articles": []
}
```

`articles` は1つのIssue(1パケット)につき最大10件。0件、または11件以上は
不正なパケットとして拒否する(この上限とは別に、1回のfetchで取り込む
新規記事の合計についてはIssue横断の上限があり、後述の「1回のfetchで
取り込む記事数の上限」を参照)。

## articleの必須項目

```json
{
  "eventKey": "同じ出来事を識別するキー",
  "sourceType": "work",
  "category": "法案・選挙・外交・経済など",
  "title": "ニュースタイトル",
  "link": "中心となる元記事URL",
  "summary": "複数情報源を踏まえた中立的な概要",
  "pubDate": "ISO 8601形式またはnull",
  "people": [],
  "organizations": [],
  "confirmedFacts": [],
  "status": "検討・調整・方針・発表・決定・成立・施行・不明など",
  "remainingProcess": [],
  "officialUrls": [],
  "relatedUrls": [],
  "sourceDifferences": [],
  "translationCautions": []
}
```

`eventKey` / `sourceType` / `category` / `title` / `link` / `summary` /
`status` は文字列、`people` 等の配列項目は必ず配列(空配列可)で、かつ
配列の各要素は文字列でなければならない(文字列以外の要素が1つでも
含まれるパケットは拒否する)。`pubDate` は文字列またはnullである必要が
ある。`sourceType` は常に `"work"` を入れる(RSS記事との判別に使う。
RSS側は後述のとおり `"rss"` を使う)。

## RSSとの共通形式(正規化後スキーマ)

Work記事・RSS記事は、`claude -p` 変換・`scripts/validate.py` から見て
同じフィールド構成の記事レコード(`data/raw/*.json`)に正規化される。

| フィールド | Work | RSS |
|---|---|---|
| sourceType | `"work"` | `"rss"` |
| eventKey | パケット内の値をそのまま使用 | linkから決定的に生成(`rss:` + sha256先頭16桁、`scripts/news_schema.py`) |
| link / title / summary / pubDate | パケット内の値 | 現行のRSS取得値 |
| category / status | パケット内の値 | 空文字 |
| people / organizations / confirmedFacts / remainingProcess / officialUrls / relatedUrls / sourceDifferences / translationCautions | パケット内の値 | 空配列 |

RSS記事ではWork固有の項目を常に空配列・空文字・nullにすることで、既存の
RSS入力との後方互換性を維持する(正規化は `scripts/news_schema.py` の
`normalize_rss_article` が担う)。

## 重複管理(処理済み台帳)

`data/state/processed_work_issues.json` に、処理済みIssue番号
(`processed_issues`)と処理済みeventKey(`processed_event_keys`)の
両方を記録する。構造例は `data/state/processed_work_issues.example.json`
を参照。このファイルは端末固有の状態のため `.gitignore` でcommit対象外
とする。

同じニュースが別のWork実行で再収集されても、eventKeyが既に台帳にあれば
再変換しない。

### 台帳更新のタイミング

台帳の更新(`scripts/import_work_news.py commit-pending`)は、次の手順が
すべて成功した後にのみ行う: 1) Issue取得、2) JSON構造検証、
3) `data/raw` の一時ファイル作成、4) `claude -p` 変換、5) `validate.py`
全件合格、6) `drafts/YYYY-MM-DD.md` への正式移動。
`scripts/import_work_news.py fetch` は台帳を一切書き換えない。取得した
Issue番号・eventKeyは一時ファイル `data/state/.pending_*.json` へ書き
出し(pending状態)、run.sh がパイプライン全体の成功を確認した後にだけ
`commit-pending` サブコマンドで確定台帳へ原子的(一時ファイル→
`os.replace`)にマージする。途中で失敗した場合、pendingファイルは無視
され、次回同じIssue・eventKeyを再処理できる。

## GitHub Issue取得(Termuxは読み取り専用)

`gh issue list --repo <repo> --label work-news --state open --json
number,title,body,createdAt` でIssue一覧を取得する。対象リポジトリは
`popchami/news-game-translator`(private)。

Termux側からGitHubへの書き込みは一切行わない。禁止:

- Issueのclose
- コメント追加
- ラベルの追加・変更・削除
- Issue本文の変更
- Issueタイトルの変更
- Issue削除

処理済みになったIssueもGitHub上ではopenのまま残る。重複取り込みの防止
は、後述の端末内処理済み台帳(`data/state/processed_work_issues.json`)
だけで行う。closeやIssueの整理(90日後削除など)は本仕様の対象外
(将来、別工程で扱う)。

## 重複記事だけのIssue

Issue自体は未処理だが、含まれる全eventKeyが既に処理済みの場合は、
ニュースを再変換しない。JSON構造が正常で、全eventKeyが処理済みである
ことを確認できた場合のみ、そのIssue番号を処理済みとして端末内台帳へ
記録する(`fetch_new_work_articles()` が返す `status: "duplicate_only"`)。
Issue自体はGitHub上でopenのまま残るが、台帳に記録済みのため次回以降
再取得・再検査されない。

JSON不正・必須項目欠落・packetVersion不正のIssueは処理済みにしない
(次回以降、Issue内容が修正されるまで毎回再検査される)。

## 1回のfetchで取り込む記事数の上限

1回の `fetch` で取り込む新規記事は、Issueごとではなく**全Issue合計**で
最大10件(`MAX_ARTICLES`)までとする。

- 候補Issue(未処理のもの)は `createdAt` の昇順(oldest-first)で
  決定的に処理する(同時刻の場合はIssue番号順)
- 1つのIssueを跨いで記事を分割することはしない(そのIssueの記事は
  丸ごと含めるか、丸ごと次回に持ち越すかのいずれか)
- あるIssueを丸ごと加えると合計が10件を超える場合、そのIssueと
  それ以降(createdAtがより新しい)の候補Issueは今回処理せず、次回の
  `fetch` に残す
- 今回実際に選択されたIssue番号とeventKeyだけがpendingファイルへ記録
  され、台帳commit対象になる。選ばれなかった(次回へ持ち越した)Issueは
  処理済みにならない

例: 6記事入りIssue A(古い)・6記事入りIssue B(新しい)が候補にある
場合、Aの6件を採用した時点で合計6件、Bを丸ごと加えると12件になり
上限超過のため、今回はAだけを処理しBは次回に残す。

## run.shの分岐

`scripts/import_work_news.py fetch` の終了コードで3方向に分岐する。

1. **exit 0**(有効な新規Work記事あり) → Work記事だけを使用して変換
   パイプラインを実行し、`validate.py` 全件合格後に `commit-pending`
   で台帳更新を行う
2. **exit 2**(`duplicate_only`: 有効なIssueだが全記事が処理済み) →
   その場で `commit-pending` を呼び、台帳更新だけ済ませる(変換は
   行わない)。その後、下書き生成は既存RSS収集(`scripts/collect.py`)
   を使う
3. **それ以外**(新規Issueなし・gh未認証/通信失敗・Issueのみ不正) →
   警告をstderrへ出し、既存RSS収集(`scripts/collect.py`)を使う。
   Issueのcommitは行わない

いずれの場合も、同一実行内でWork記事とRSS記事を混在させない
(下書き生成に使うのはWork/RSSのどちらか一方のみ)。

## translate.mdでの扱い

`prompts/translate.md` を参照。sourceTypeが `work` の記事は
confirmedFacts→status→remainingProcess→sourceDifferences→
translationCautions→summaryの優先順位で事実を使う。RSS記事は従来どおり
title/summaryを使う。各下書きのメモに「収集経路: Work」または
「収集経路: RSS」を必須出力する。

## validate.pyでの追加検査

- 入力記事の `sourceType` が `work` または `rss` であること
- 下書きメモの収集経路が入力記事の `sourceType` と一致すること
- 入力記事の `link` が下書きに厳密に1回使われること(Phase 1の
  一対一対応検査を維持。sourceTypeによらず全リンク共通の検査)
