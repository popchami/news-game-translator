# 引き継ぎメモ(HANDOFF)

このファイルは、セッションをまたいだ作業の引き継ぎ用に、直近の状況を
「完了/次/保留」の形で常に上書き更新する。詳細な設計は各ドキュメントを
参照すること(このファイル自体は要約のみを保持する)。

最終更新: 2026-07-20(ChatGPT漫画生成ルート実装完了・diff提示待ち、
Gemini API自動化ルートは調査完了・方針承認待ち)

---

## 完了

### Phase 1: 異世界ニホン5コマ構成マンガ化パイプライン(NGT側)

X投稿用に、ニュースを5コマ構成(起承転結4コマ+解説コマ)のマンガとして
半自動生成するパイプラインの、NGT(Termux)側の全工程をPhase 1として実装した。
ブランチ`manga-pipeline-phase1`でcommit `e6a6620`〜`b214ab9`(全9commit)、
main へマージ済み。

- **設計書**: docs/manga-pipeline.md。システム全体構成、役割分担
  (ChatGPT Work=収集のみ/Termux=司令塔/RunPod+ComfyUI=画像化のみ)、
  Manga News Packetの内容、通信方式(Termux上のローカルHTTPサーバー、
  確定済み)、Phase 2方針(CMS側SDXLプロファイル新規追加)を規定
- **5コマ構成への確定**: docs/worldbook.mdの「漫画化の制作方針」に
  「X用5コマ構成」を新設。1話=起承転結4コマ(画像生成対象、panels)+
  解説コマ(第5コマ、scribe_note表示)
- **Manga News Packetスキーマ**: scripts/manga_schema.py。
  packet_version・created_at(ISO 8601検証つき)・source・isekai_text・
  scribe_note・characters(manga/characters.mdの5人のみ、最大3人)・
  panels(必ず4要素、表情タグはハルト・ナツキ表情セットの実ファイル体系
  〔00-neutral、01〜27=9感情×weak/medium/strong、28〜30=speaking専用の
  small/normal/forceful〕に確定)・cautionsを検証
- **脚本生成プロンプト**: prompts/manga_script.md。4コマの型は
  2026-07-20に改訂済み(詳細は下記「ChatGPT漫画生成ルート」参照)
- **検証スクリプト**: scripts/validate_manga.py。manga_schema.pyの構造
  検証+scripts/banned_terms.pyの禁止語検証
- **受信アプリ(NGT側)**: app/isekai_inbox.html。ニュース受信箱→内容確認
  の2画面。「マンガ生成」ボタンは準備中のダミー表示、RunPod接続は未実装
- **ローカルHTTPサーバー**: scripts/serve_inbox.py。Python標準ライブラリ
  (http.server)のみ、127.0.0.1:8787で待ち受け
- **Codexレビュー**: 各ステップのcommit後に実施(計4回)。Critical/Minor
  指摘はいずれも修正済み

### Phase 4(参考、既にmain統合済み): 緊急ニュース処理モード

`bash run.sh --urgent --issue N`で、指定したWork News Issue 1件を通常の
日次下書きとは独立に処理できる。GitHubは読み取り専用、RSSフォールバック
なし、通常/緊急モード同時実行時の台帳競合はflockで排他制御。

### ChatGPT漫画生成ルート(2026-07-20、実装完了・mainへは未マージ)

RunPod+ComfyUIの自動生成ルート(Phase 2以降)とは別に、ChatGPTのチャット
画面へ人間が構成案・参照画像を渡して5コマ漫画を1枚絵として生成する運用を
正式ルートとして整備した。ブランチ`feature/chatgpt-manga-route`
(mainから分岐、8commit)で実装。**mainへのマージは未実施、チャミの
diff確認・承認待ち(Step9)。**

- **決定事項(チャミ)**: 4コマの型を刷新。panels(第1〜4コマ)はハルト・
  ナツキ専任とし、書記官はscribe_note(第5コマ)専任へ一本化(旧型は
  4コマ目を「書記官の解説」としてpanelsに書記官を含めていた)。
  `reference_image`(単数)は既存Packetとの後方互換のため維持しつつ、
  1コマに複数キャラが映る新仕様向けに`reference_images`(複数形、
  キャラ名→ファイル名の辞書)を追加。両方式は排他(同時指定はエラー)。
  スキーマの`characters`は5人からの自由選択を維持し、ChatGPTルート固有の
  制約(panels1-4はハルト・ナツキのみ、charactersは
  {ハルト,ナツキ,書記官}のみ)は`scripts/validate_manga.py`の
  `validate_chatgpt_route()`という別レイヤーの追加検証として実装(既存の
  `manga_schema.py`は汎用のまま、RunPodルート等での再利用を想定)
- **スキーマ拡張**(`scripts/manga_schema.py`): `reference_images`
  複数形、`panels[].role`(任意、コマの役割)、
  `source.decided`/`not_decided`/`next_step`(任意)を追加。いずれも
  既存Packetとの後方互換を維持(未指定なら従来通り合格)
- **`scripts/validate_manga.py`**: 新規`validate_chatgpt_route()`。
  panels1-4のreference_imagesキーが{ハルト,ナツキ}のみ、トップレベル
  charactersが{ハルト,ナツキ,書記官}のみであることを検証
- **`prompts/manga_script.md`・`docs/worldbook.md`**: 新4コマの型
  (①導入②ハルトの疑問③ナツキの整理④現在地の確認、書記官はscribe_note
  専任)へ全面改訂
- **`docs/manga-pipeline.md`**: 前提条件の古い記載(「ハルトのみ完成」)
  を修正。comfyui-mobile-system側で2026-07-20時点、ハルト・ナツキとも
  表情31種・4方向立ち絵まで完成済み(ナツキはさらに装備・紋2種も完成済み、
  GitHub Release資産として実URL取得検証済み)という実際の状態を反映
- **新形式サンプル**: `data/state/manga_packet.chatgpt_route.example.json`
  を新規追加。既存の`manga_packet.example.json`(旧形式)はそのまま残す
- **`scripts/collect_manga_reference_images.py`**(新規): Manga News
  Packetが参照するハルト・ナツキの正本画像一式を、comfyui-mobile-system
  側のローカルチェックアウトから直接コピーする(ネットワークアクセスなし、
  新規pip依存なし)。パス未存在・fetch未実行時は明確なエラーで停止。
  `--packet`/`--logical-id`/`--default-turnaround`(4方向立ち絵8枚の
  最小セット)の3モード。実データ(comfyui-mobile-system実チェックアウト)
  で動作確認済み
- **`app/isekai_inbox.html`**: 内容確認画面に「ChatGPT用プロンプトを
  コピー」ボタンを追加(`navigator.clipboard.writeText()`、標準API)。
  Node.js上で実データを使い動作確認済み(成功・非対応・失敗の3パターン)。
  各コマの参照キャラクター表示も追加
- **テスト**: 298件全て合格(`python3 -m unittest discover -s tests`)。
  既存Packetとの後方互換、新スキーマフィールド、ChatGPTルート追加検証、
  参照画像収集(パストラバーサル拒否・部分失敗時の非コピー含む)、
  新形式サンプルの両検証合格などを個別カバー
- **Codexレビューについて**: Step8でCodexレビューを依頼したが、
  Codex側のusage limit到達(`task-mrt3vhuv-az8mc5`、次回利用可能は
  2026-07-25以降)によりレビュー自体が実行できなかった(指摘ゼロで
  合格したのではなく、レビューが一度も走っていない)。チャミの判断により
  今回はCodexレビューをスキップし、代わりに自己レビューを実施。
  自己レビューで2点発見・修正済み(`--packet`指定時の生の例外露出を
  明確なエラーメッセージへ統一、エラーメッセージ内の紛らわしい表記を修正。
  コミット`776a00c`)。**mainへのマージ前に、Codex利用再開後の正式レビュー
  実施を検討の余地あり**

### Gemini API自動化ルート(2026-07-20、調査のみ完了・実装未着手)

ChatGPTルートとは別に、Gemini APIを直接呼び出して人手を介さず5コマ画像を
自動生成するルートを調査した。**リポジトリ変更・ブランチ作成・依存追加は
一切行っていない。**

- REST直叩き(標準ライブラリのみ、新規pip依存ゼロ)を推奨。公式SDK
  (`google-genai`)は新規依存追加としてチャミの承認が必要
- Termuxからのgenerativelanguage.googleapis.comへのHTTPS到達性を実機
  確認済み(TLS/DNSとも正常)
- APIキーはOS環境変数での管理を推奨(`.env`ファイル・追加パースライブラリ
  とも不要)
- `feature/chatgpt-manga-route`への依存度が高い(`reference_images`
  スキーマ・`validate_chatgpt_route()`・`collect_manga_reference_images.py`
  をそのまま再利用想定)。そのため**ブランチ戦略(chatgpt-manga-route
  マージ後に着手 or 直接スタックするか)はチャミの判断待ち**
- 概算コスト・ブランチ名案(`feature/gemini-api-manga-route`)・実装計画
  たたき台は提示済み。次のアクションはチャミの承認(SDK/REST方式・
  ブランチ戦略の確定)

---

## 次

1. **チャミへdiff一式を提示し、`feature/chatgpt-manga-route`のmainマージ
   承認を得る**(Step9、直近の作業)。承認後、Codex利用再開(2026/7/25以降)
   を待ってから正式レビューを行うか、このまま自己レビュー結果でマージする
   かもあわせて確認する
2. **Gemini API自動化ルート**: 調査結果(ブランチ戦略・SDK/REST方式・
   APIキー管理方針)についてチャミの承認を得てから、
   `feature/gemini-api-manga-route`で実装着手
3. **comfyui-mobile-system側の対応**(Phase 2、従来から継続): SDXL+
   IPAdapterのマンガ用ComfyUI Workflow構築。ハルト・ナツキの参照画像は
   2026-07-20時点で完成済み(表情・4方向立ち絵、ナツキはさらに装備・紋も)
4. **組版後処理の調査**(RunPodルート向け、従来から継続): 吹き出し配置・
   キャラ配置構図の制御・4コマへの結合処理・日本語描画方式

---

## 保留

- **アキラ・フユミ・書記官の設定画**: manga/characters.mdの必要な設定画
  一覧に沿って、ChatGPTでの生成を担当(チャミ側作業)。ハルト・ナツキは
  2026-07-20時点で完成済み(旧記載「ハルトのみ完成」は誤りだったため
  docs/manga-pipeline.mdを修正済み)
- **書記官の解説カットストック**(RunPodルート向け): 5〜10枚。設定画と
  同様にChatGPTで生成予定
- **LoRA検討メモ**: LoRAを作ること自体は未確定。docs/manga-pipeline.mdの
  「LoRA検討メモ」に記録済み
