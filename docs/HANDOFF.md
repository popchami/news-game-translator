# 引き継ぎメモ(HANDOFF)

このファイルは、セッションをまたいだ作業の引き継ぎ用に、直近の状況を
「完了/次/保留」の形で常に上書き更新する。詳細な設計は各ドキュメントを
参照すること(このファイル自体は要約のみを保持する)。

最終更新: 2026-07-19(異世界ニホン4コマ/5コマ構成マンガ化パイプライン
Phase 1完了)

---

## 完了

### Phase 1: 異世界ニホン5コマ構成マンガ化パイプライン(NGT側)

X投稿用に、ニュースを5コマ構成(起承転結4コマ+解説コマ)のマンガとして
半自動生成するパイプラインの、NGT(Termux)側の全工程をPhase 1として実装した。
ブランチ`manga-pipeline-phase1`でcommit `e6a6620`〜`b214ab9`(全9commit)、
main へマージ済み。

- **設計書**: docs/manga-pipeline.md(v0.6)。システム全体構成、役割分担
  (ChatGPT Work=収集のみ/Termux=司令塔/RunPod+ComfyUI=画像化のみ)、
  Manga News Packetの内容、通信方式(Termux上のローカルHTTPサーバー、
  確定済み)、Phase 2方針(CMS側SDXLプロファイル新規追加)、LoRA検討メモ
  (未確定)、Phase 2調査項目、開発ロードマップ(Phase 1〜6)を規定
- **5コマ構成への確定**: docs/worldbook.mdの「漫画化の制作方針」に
  「X用5コマ構成」を新設。1話=起承転結4コマ(画像生成対象、panels)+
  解説コマ(第5コマ、scribe_note表示)。第5コマは事前生成した書記官解説
  カットストックから選択+テキスト合成する方式(将来、毎回生成方式への
  b昇格も想定)
- **Manga News Packetスキーマ**: scripts/manga_schema.py。
  packet_version・created_at(ISO 8601検証つき)・source・isekai_text・
  scribe_note・characters(manga/characters.mdの5人のみ、最大3人)・
  panels(必ず4要素、表情タグはハルト表情セットの実ファイル体系
  〔00-neutral、01〜27=9感情×weak/medium/strong、28〜30=speaking専用の
  small/normal/forceful〕に確定)・cautionsを検証
- **脚本生成プロンプト**: prompts/manga_script.md。
  prompts/translate.md・config/runtime_rules.mdのルールを継承し、
  4コマの型(①出来事の提示②キャラの疑問③別キャラの補足・展開④書記官の
  解説)、image_promptとexpressionタグの整合ルールを規定
- **検証スクリプト**: scripts/validate_manga.py。manga_schema.pyの構造
  検証+scripts/banned_terms.pyの禁止語検証(法案・選挙の文脈語、政党名
  カタカナ化、ニホンに実在しない王制表現)。王制語の入力照合は、Packetの
  sourceだけでなくオプションで元記事JSON全文(`[<source_json>]`引数)も
  照合対象にできる
- **例(episode01.mdを4コマに圧縮)**: data/state/manga_packet.example.json
  (事実は変更なし)
- **受信アプリ(画像生成なし版、NGT側)**: app/isekai_inbox.html
  (スマホ向け1ファイル完結)。ニュース受信箱→内容確認(4コマ構成+
  第5コマ〔書記官の解説〕+注意事項)の2画面。「マンガ生成」ボタンは
  準備中のダミー表示、RunPod接続は未実装
- **ローカルHTTPサーバー**: scripts/serve_inbox.py。Python標準ライブラリ
  (http.server)のみ、127.0.0.1:8787で待ち受け。
  `drafts/manga_packets/`配下のPacket一覧・個別取得API。ファイル名検証+
  シンボリックリンク境界チェックの二重防御でディレクトリトラバーサルを
  防止(list_packets・load_packet共通のチェック関数)
- **テスト**: tests/test_manga_schema.py・test_validate_manga.py・
  test_serve_inbox.py を新規追加(実HTTPサーバーを起動するルーティング
  テストを含む)。既存分と合わせてリポジトリ全体で239件、全合格
- **Codexレビュー**: 各ステップのcommit後に実施(計4回)。Critical指摘
  (表情タグの実ファイル名不一致、王制語照合範囲の狭さ、同時実行時の
  台帳競合〔Phase 4の緊急モード関連、参考〕)・Minor指摘(javascript:
  スキームのリンク化、symlink境界チェックの不整合、HTTPルーティング層の
  テスト不足等)はいずれも修正済み。最終ラウンドでBlocker/Critical 0件

### Phase 4(参考、既にmain統合済み): 緊急ニュース処理モード

`bash run.sh --urgent --issue N`で、指定したWork News Issue 1件を通常の
日次下書きとは独立に処理できる。GitHubは読み取り専用、RSSフォールバック
なし、通常/緊急モード同時実行時の台帳競合はflockで排他制御。

---

## 次(Phase 2の予定)

1. **comfyui-mobile-system側の対応**: `chatgpt-work`ブランチの
   `profiles/sdxl/isekai_nihon_manga/`(現状`.gitkeep`のみ)に、
   SDXL+IPAdapterのマンガ用ComfyUI Workflowを構築する。既存のFlux系
   プロファイルには手を加えない(docs/manga-pipeline.mdの
   「Phase 2方針」参照)
2. **IPAdapterパイロット生成**: ハルトのカットで品質を確認し、キャラ
   固定方式(候補A: IPAdapter/候補B: 自作LoRA)を決定する
   (docs/manga-pipeline.mdの「Phase 2調査項目 > キャラ固定方式」
   「LoRA検討メモ」参照)
3. **組版後処理の調査**: 吹き出し配置・キャラ配置構図の制御・4コマへの
   結合処理・日本語描画方式(フォント・縦横書き・Pillow実装)を調査する
   (同「4コマ組版の後処理」「日本語テキスト」参照)
4. **第5コマ(解説コマ)関連の調査**: 書記官解説カットストックの作成
   (下記「保留」参照)を受けて、第5コマの毎回生成化(b昇格)の要否を
   検証する

---

## 保留

- **アキラ・書記官の設定画**: manga/characters.mdの必要な設定画一覧に
  沿って、ChatGPTでの生成を担当(チャミ側作業)。ハルトのみ完成済み
- **書記官の解説カットストック**: 5〜10枚(例: 正面で記録を読む/横顔で
  書き物/掲示板の奥に佇む)。設定画と同様にChatGPTで生成予定
- **LoRA検討メモ**: LoRAを作ること自体は未確定(キャラ固定方式の確定は
  Phase 2冒頭のIPAdapterパイロット生成待ち)。作ると決めた場合の優先順位
  ・学習画像枚数の目安はdocs/manga-pipeline.mdの「LoRA検討メモ」に記録済み
- **ナツキ・フユミ**: 現時点で未登場のため、設定画作成の優先度は低い
