#!/usr/bin/env python3
"""異世界ニホン X用5コマ構成 Manga News Packet(v2)の検証スクリプト。

manga_schema.pyによる構造検証(packet_version・source・4コマ固定・
登場キャラ2〜3人+書記官・performers/dialogues・scribe_panel等)に加え、
scripts/validate.py・scripts/banned_terms.pyの既存の禁止語検証(法案・選挙の
文脈語、政党名カタカナ化、ニホンに実在しない王制表現)を、Packet内の
日本語テキスト全体(isekai_text・scribe_note・各コマのscene/background/
image_prompt/negative_prompt・各dialogueのtext)に対して行う。RunPod側へ
渡す前の最終確認として使う。

v1からv2への変更点: 旧`validate_chatgpt_route`(panelsをハルト・ナツキの
2人に固定する追加検証レイヤー)は廃止した。v2のmanga_schema.validate_packet
自体が「物語側2〜3人(ハルト・ナツキ・アキラ・フユミから選択)+書記官、
書記官はpanelsに登場させない」という同等以上の制約を一般スキーマとして
持つため、別レイヤーとして維持する理由がなくなったため(実運用データが
なかったことも確認済み、詳細はdocs/HANDOFF.md参照)。

王制語の入力照合(check_kingdom_terms)は、Packetのsource(title・url・
summaryのみ)だけでは元記事の情報量が乏しく、元記事に実在する正当な語彙
(例: 外国・歴史上の呼称)を誤って「入力に存在しない語」として却下する
おそれがある。そのためオプションで元記事JSON(data/raw/*.json と同じ
記事スキーマの配列。scripts/validate.pyが使うものと同一)を渡せるように
し、source.urlと一致するlinkの記事があれば、その全文
(scripts/validate.pyのbuild_source_text_blobと同じフィールド)も照合
対象に含める。
"""
import json
import sys

import manga_schema
import validate
from banned_terms import CONTEXTUAL_FORBIDDEN_TERMS, FORBIDDEN_PARTY_KATAKANA


def build_packet_text_blob(packet):
    """Packet内のテキストフィールドを連結し、禁止語検査用の正規化済み
    テキストを作る。image_prompt/negative_promptは本来英語だが、モデルが
    日本語(禁止語・政党名カタカナ化等)を混入させる可能性を検査で捕捉
    できるよう、検査対象に含める(Codexレビュー指摘、v1から継続)。
    """
    parts = [
        str(packet.get("isekai_text", "") or ""),
        str(packet.get("scribe_note", "") or ""),
    ]
    panels = packet.get("panels")
    if isinstance(panels, list):
        for panel in panels:
            if not isinstance(panel, dict):
                continue
            for field in ("scene", "background", "image_prompt", "negative_prompt"):
                parts.append(str(panel.get(field, "") or ""))
            dialogues = panel.get("dialogues")
            if isinstance(dialogues, list):
                for dialogue in dialogues:
                    if isinstance(dialogue, dict):
                        parts.append(str(dialogue.get("text", "") or ""))
            caption = panel.get("caption")
            if isinstance(caption, str):
                parts.append(caption)
    return validate.normalize_for_check("\n".join(parts))


def build_source_text_blob(source, raw_article=None):
    """source(Packetのtitle・url・summary)を、王制語検査の入力照合用
    テキストへ変換する。raw_article(元記事JSONの該当記事、フィールドは
    scripts/validate.pyのbuild_source_text_blobと同じ)が渡された場合は、
    そちらの全文もあわせて照合対象に含める(sourceの中立要約だけでは
    落ちてしまう元記事中の正当な語彙を拾うため)。
    """
    parts = []
    if isinstance(source, dict):
        parts.append(str(source.get("title", "") or ""))
        parts.append(str(source.get("summary", "") or ""))
    text = validate.normalize_for_check("\n".join(parts))
    if isinstance(raw_article, dict):
        text = text + "\n" + validate.build_source_text_blob(raw_article)
    return text


def find_matching_raw_article(raw_articles, url):
    """raw_articles(元記事JSONの配列)から、linkがurlと一致する記事を返す。
    見つからない場合はNone。
    """
    if not isinstance(raw_articles, list) or not url:
        return None
    for article in raw_articles:
        if isinstance(article, dict) and article.get("link") == url:
            return article
    return None


def check_banned_terms(normalized_text, source_text):
    reasons = []
    reasons.extend(validate.check_kingdom_terms(normalized_text, source_text))

    for term, context_markers in CONTEXTUAL_FORBIDDEN_TERMS.items():
        if term in normalized_text and any(marker in normalized_text for marker in context_markers):
            reasons.append(f"禁止語「{term}」を法案・選挙の文脈で検出")

    for term in FORBIDDEN_PARTY_KATAKANA:
        if term in normalized_text:
            reasons.append(f"政党名カタカナ変換「{term}」を検出")

    return reasons


def validate_manga_packet(packet, raw_article=None):
    """Manga News Packet1件を検証し、違反理由のリストを返す(空なら合格)。

    raw_articleを渡すと、王制語の入力照合にPacketのsourceだけでなく
    元記事の全文も使う(モジュールdocstring参照)。
    """
    reasons = list(manga_schema.validate_packet(packet))

    if not isinstance(packet, dict):
        # packetがdict以外(list等)の場合、manga_schema.validate_packet側で
        # 既に不正と報告済み。build_packet_text_blob等がpacket.get(...)を
        # 呼び出すため、続行するとAttributeErrorで異常終了してしまう
        # (Codexレビュー指摘、Major)。
        return reasons

    normalized_text = build_packet_text_blob(packet)
    source_text = build_source_text_blob(packet.get("source"), raw_article=raw_article)
    reasons.extend(check_banned_terms(normalized_text, source_text))

    return reasons


def main():
    if len(sys.argv) not in (2, 3):
        print("usage: validate_manga.py <packet_file> [<source_json>]", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        packet = json.load(f)

    raw_article = None
    if len(sys.argv) == 3:
        source_path = sys.argv[2]
        with open(source_path, encoding="utf-8") as f:
            raw_articles = json.load(f)
        source = packet.get("source")
        url = source.get("url") if isinstance(source, dict) else None
        raw_article = find_matching_raw_article(raw_articles, url)

    reasons = validate_manga_packet(packet, raw_article=raw_article)
    if reasons:
        print(f"NG: {path}")
        for reason in reasons:
            print(f"  - {reason}")
        sys.exit(1)

    print(f"OK: {path}")
    sys.exit(0)


if __name__ == "__main__":
    main()
