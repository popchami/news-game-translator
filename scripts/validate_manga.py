#!/usr/bin/env python3
"""異世界ニホン4コマ版 Manga News Packetの検証スクリプト。

manga_schema.pyによる構造検証(packet_version・source・4コマ固定・
登場キャラ<=3人等)に加え、scripts/validate.py・scripts/banned_terms.pyの
既存の禁止語検証(法案・選挙の文脈語、政党名カタカナ化、ニホンに実在
しない王制表現)を、Packet内の日本語テキスト全体
(isekai_text・scribe_note・各コマのscene/dialogue/background)に対して
行う。RunPod側へ渡す前の最終確認として使う。
"""
import json
import sys

import manga_schema
from banned_terms import CONTEXTUAL_FORBIDDEN_TERMS, FORBIDDEN_PARTY_KATAKANA
from validate import check_kingdom_terms, normalize_for_check


def build_packet_text_blob(packet):
    """Packet内の日本語テキストフィールドを連結し、禁止語検査用の
    正規化済みテキストを作る。
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
            for field in ("scene", "dialogue", "background"):
                parts.append(str(panel.get(field, "") or ""))
    return normalize_for_check("\n".join(parts))


def build_source_text_blob(source):
    """source(元記事タイトル・URL・中立要約)を、王制語検査の入力照合用
    テキストへ変換する。
    """
    if not isinstance(source, dict):
        return ""
    parts = [str(source.get("title", "") or ""), str(source.get("summary", "") or "")]
    return normalize_for_check("\n".join(parts))


def check_banned_terms(normalized_text, source_text):
    reasons = []
    reasons.extend(check_kingdom_terms(normalized_text, source_text))

    for term, context_markers in CONTEXTUAL_FORBIDDEN_TERMS.items():
        if term in normalized_text and any(marker in normalized_text for marker in context_markers):
            reasons.append(f"禁止語「{term}」を法案・選挙の文脈で検出")

    for term in FORBIDDEN_PARTY_KATAKANA:
        if term in normalized_text:
            reasons.append(f"政党名カタカナ変換「{term}」を検出")

    return reasons


def validate_manga_packet(packet):
    """Manga News Packet1件を検証し、違反理由のリストを返す(空なら合格)。"""
    reasons = list(manga_schema.validate_packet(packet))

    normalized_text = build_packet_text_blob(packet)
    source_text = build_source_text_blob(packet.get("source"))
    reasons.extend(check_banned_terms(normalized_text, source_text))

    return reasons


def main():
    if len(sys.argv) != 2:
        print("usage: validate_manga.py <packet_file>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        packet = json.load(f)

    reasons = validate_manga_packet(packet)
    if reasons:
        print(f"NG: {path}")
        for reason in reasons:
            print(f"  - {reason}")
        sys.exit(1)

    print(f"OK: {path}")
    sys.exit(0)


if __name__ == "__main__":
    main()
