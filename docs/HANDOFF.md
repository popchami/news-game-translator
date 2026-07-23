# 引き継ぎメモ(HANDOFF)

このファイルは、セッションをまたいだ作業の引き継ぎ用に、直近の状況を
「完了/次/保留」の形で常に上書き更新する。詳細な設計は各ドキュメントを
参照すること(このファイル自体は要約のみを保持する)。

最終更新: 2026-07-24(Manga News Packet v2への全面移行・正本テンプレート
仕様確定。実装ブランチ`manga-packet-v2`・実装commit`6adc935d00d8155f30f0c2602c623e994725aa09`・
PR #15(https://github.com/popchami/news-game-translator/pull/15)。
分割CodexレビューA/B/D完了、レビュー時点でBlocker/Critical/Major/Minor
残件0、レビュー時点で350件全合格、comfyui-mobile-system側との接続契約
18項目すべてMATCH確認済み。**最新のマージ状態はGitHub PR #15と
git履歴を正とする**

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

### ChatGPT漫画生成ルート(2026-07-20実装、コミット`1d4d42e`でmain統合済み)

RunPod+ComfyUIの自動生成ルート(Phase 2以降)とは別に、ChatGPTのチャット
画面へ人間が構成案・参照画像を渡して5コマ漫画を1枚絵として生成する運用を
正式ルートとして整備した。ブランチ`feature/chatgpt-manga-route`
(mainから分岐、8commit)で実装。**mainへsquash-merge済み(コミット
`1d4d42e`)。旧記載「mainへのマージは未実施」は本ファイルの更新漏れであり
誤り(2026-07-23に本ファイルを確認して修正)。ブランチ自体は削除せず残存**
(なお、この節で導入した`reference_images`複数形・`validate_chatgpt_route()`
は、下記「Manga News Packet v2」により汎用スキーマへ統合され廃止済み)。

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

### Manga News Packet v2への全面移行(2026-07-23〜24、実装ブランチ`manga-packet-v2`・PR #15)

チャミが提示した正本の5コマテンプレート仕様(1080×1920px、5コマの座標・
枠線6px・コマ間隔19px。comfyui-mobile-system側に数値正本を配置)確定に
伴い、Manga News PacketをPACKET_VERSION 2へ全面移行した。

- **実装ブランチ**: `manga-packet-v2`(mainから分岐)
- **実装commit**: `6adc935d00d8155f30f0c2602c623e994725aa09`
- **PR**: #15(https://github.com/popchami/news-game-translator/pull/15)
- **最新のマージ状態はGitHub PR #15とgit履歴を正とする**(このファイルの
  記載は実装時点のスナップショットであり、マージ・Release状況を都度
  上書きする運用はしない)

- **分割Codexレビュー完了**(2026-07-24): 差分を4分割してレビュー
  (A: Packet v2中核スキーマ/検証、B: NGT連携・UI・文書、C: comfyui-
  mobile-system側テンプレート仕様、D: 2リポジトリ間の接続契約18項目)。
  各分割ともBlocker/Critical/Major/Minor**残件0**まで指摘を修正済み
  (発見した指摘は全て妥当と確認の上で採用、誤検出での不採用はなし)
- **テスト結果**: news-game-translator **350件全合格**、
  comfyui-mobile-system **125件全合格**(いずれも
  `python3 -m unittest discover -s tests`)
- **接続契約(分割レビューD)**: packet_version・panels構造・
  camera_angle/framing/position/bubble_positionの各enum・31表情タグ・
  `CHARACTER_REFERENCE_ID`・reference_image論理ID形式・書記局章ID・
  テンプレート座標など**18項目すべてMATCH**(不一致0件)

- **移行判断**: `drafts/manga_packets/`(実運用中データの置き場)は
  `.gitkeep`のみで空、`data/state/`にも実運用中のv1 Packetは存在しない
  ことを確認した上で、後方互換コードを持たない一括移行を選択(チャミの
  指示どおり)
- **決定事項(チャミ)**:
  1. panels(第1〜4コマ)は1コマ1人・単一`dialogue`文字列という制約を廃止し、
     1コマ最大2人(`performers`)・複数吹き出し(`dialogues`、最大2個)を
     持てる構造へ変更
  2. `role`を自由記述から`setup`/`development`/`turn`/`resolution`の
     固定4値へ変更し、`panel_no`との対応を必須化
  3. 第1〜4コマの登場人物を「ハルト・ナツキ専任」から「ハルト・ナツキ・
     アキラ・フユミの4人から2〜3人を選択」へ拡張(アキラ・フユミの参照
     画像完成に伴う変更)。書記官は第1〜4コマに一切登場させない方針は継続
  4. 第5コマに`scribe_panel`(`layout`/`expression`/`reference_image`/
     `emblem_reference`)を新設。書記官の正本画像(表情31+書記局章1、
     comfyui-mobile-system側で完成・Release公開済み)を初めて参照可能にした
  5. 旧`validate_chatgpt_route`(panelsをハルト・ナツキに固定する別レイヤー
     検証)は、v2の`manga_schema.validate_packet`自体が同等以上の制約
     (物語側2〜3人+書記官、書記官はpanels対象外)を一般スキーマとして
     持つため廃止
- **`scripts/manga_schema.py`**: 全面書き換え。`PACKET_VERSION=2`、
  `STORY_CHARACTERS`/`SCRIBE_CHARACTER`、`CHARACTER_REFERENCE_ID`
  (Packetの日本語表示名→comfyui-mobile-system側ローマ字フォルダ名の対応、
  両リポジトリ間の接続契約)、`performers`/`dialogues`/`scribe_panel`の
  検証関数、画角・フレーミングの多様性チェック(連続コマでの重複禁止、
  4コマ全体で3種類以上、全身構図は1話最大1コマ)、セリフの三点リーダー
  のみ拒否・行数/文字数制限(Unicode正規化後の表示文字数で検査)を追加。
  `PANEL_COUNT=4`は変更なし(第5コマは引き続きpanelsに含めない)
- **`scripts/validate_manga.py`**: `validate_chatgpt_route`関連を削除。
  `build_packet_text_blob`をv2フィールド名(`dialogues[].text`・
  `negative_prompt`・`caption`)に対応させた
- **`scripts/collect_manga_reference_images.py`**: `panels[].performers[]`・
  `scribe_panel`からreference_imageを抽出するよう更新(書記官の正本画像も
  収集対象に追加。旧コメント「書記官の正本画像は現時点で未準備」は誤り)
- **`data/state/manga_packet.example.json`**: v2形式へ更新。
  `data/state/manga_packet.chatgpt_route.example.json`は、ChatGPTルート
  専用制約の廃止に伴い削除(v2の単一サンプルへ統合)
- **`prompts/manga_script.md`**: v2版として全面書き換え。登場人物の選び方
  (4人から2〜3人)、画角・構図のルール、キャラクター固定事項(comfyui-
  mobile-system側の正本と一致させる装備・利き手の記載)、表情タグ31種の
  用途・避ける場面の対応表(31行)を追加
- **`docs/manga-pipeline.md`**: v0.8。前提条件を「5人全員の参照画像完成
  済み」に更新(旧「アキラ・フユミ・書記官は未完成」は誤り)。第5コマの
  仕様を「書記官解説カットストック5〜10枚」から「表情31種+書記局章の
  正本画像から選択」へ更新。テンプレート物理仕様はcomfyui-mobile-system側
  `five_panel_template.json`/`.md`へ分離することを明記
- **`docs/worldbook.md`**: 「X用5コマ構成」節を改訂。panels登場人物を
  「ハルト・ナツキ専任」から「4人から2〜3人選択」へ更新
- **`manga/characters.md`**: v0.3-draft。ナツキ・アキラ・フユミ・書記官の
  装備欄を、comfyui-mobile-system側で完成した実際の正本画像と一致するよう
  修正(旧記載はキャラクター設定の初期草案のままで、実際に生成・登録された
  資産〔ナツキ=日本弓+右籠手、アキラ=符・トンカチ・釘、フユミ=薬箱、
  書記官=タブレット+ペン〕と食い違っていたことが今回判明・修正)
- **`app/isekai_inbox.html`**: `panelCard`等をv2の`performers`/`dialogues`
  構造に対応させ、ChatGPT用プロンプトの生成部分もPacketの実際の
  `characters`を動的に反映するよう修正(旧実装はハルト・ナツキを
  ハードコードしていた)
- **テスト**: 320件全て合格(`python3 -m unittest discover -s tests`)。
  v2構造・多様性ルール・文字数制限・scribe_panel・既存の参照画像取得/
  論理ID解決テストを含め全件回帰確認済み
- **正本テンプレートPNG**: `/sdcard/Download/manga_panel_template_v3.png`
  (1080×1920)が指定座標と完全一致することをPillowで実測検証済み
  (詳細はcomfyui-mobile-system側HANDOFF.md参照)。数値正本はJSON側であり、
  PNG自体はどちらのリポジトリにもコミットしていない

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
- 元々`feature/chatgpt-manga-route`(v1のPacket仕様、`reference_images`
  複数形フィールド・`validate_chatgpt_route()`)への依存度が高い設計として
  提示していたが、**2026-07-24時点でPacketはv2へ全面移行済み**(下記
  「Manga News Packet v2への全面移行」参照)。`reference_images`(panel
  直下の複数形フィールド)は`panels[].performers[].reference_image`へ、
  `validate_chatgpt_route()`は`manga_schema.validate_packet`本体の
  characters/performers検証へ統合され、いずれも現在は存在しない。
  Gemini APIルートに着手する場合は、これらv1時点の設計ではなくv2の
  スキーマ(`scripts/manga_schema.py`)・`scripts/collect_manga_reference_images.py`
  (v2のperformers/scribe_panel抽出に対応済み)を前提に再設計すること。
  **ブランチ戦略・実装計画のたたき台自体もv2に合わせた再検討が必要**
- 概算コスト・ブランチ名案(`feature/gemini-api-manga-route`)・実装計画
  たたき台は提示済み。次のアクションはチャミの承認(SDK/REST方式・
  ブランチ戦略の確定)

---

## 次

1. **PR #15(https://github.com/popchami/news-game-translator/pull/15)の
   マージ判断**。最新状態はGitHub PRとgit履歴を参照すること
2. **Gemini API自動化ルート**: 調査結果(ブランチ戦略・SDK/REST方式・
   APIキー管理方針)についてチャミの承認を得てから、
   `feature/gemini-api-manga-route`で実装着手
3. **comfyui-mobile-system側の対応**(Phase 2、従来から継続): SDXL+
   IPAdapterのマンガ用ComfyUI Workflow構築(今回はデータ層・テンプレート
   仕様の確定のみ。Workflow本体・RunPod接続・画像生成は未着手)。
   5人全員の参照画像は2026-07-23時点で完成済み
4. **組版後処理の調査**(RunPodルート向け、従来から継続): 吹き出し配置・
   キャラ配置構図の制御・4コマへの結合処理・日本語描画方式(物理座標の
   正本はcomfyui-mobile-system側`five_panel_template.json`を参照)

---

## 保留

- **LoRA検討メモ**: LoRAを作ること自体は未確定。docs/manga-pipeline.mdの
  「LoRA検討メモ」に記録済み

(旧保留事項「アキラ・フユミ・書記官の設定画」「書記官の解説カットストック
5〜10枚」は、comfyui-mobile-system側で5人全員の参照画像〔表情31+
turnaround4、書記官は書記局章1も〕が完成・Release公開済みとなったため解消)
