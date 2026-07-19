"""異世界ニホン4コマ版 Manga News Packetのスキーマ定義。

news_schema.pyの作りに合わせ、Termux(NGT)が生成しRunPod側アプリへ渡す
構造化JSON(Manga News Packet)の構造検証関数を提供する。ニュース解釈・
4コマ構成・セリフ・画像生成用プロンプトはすべてTermux側で確定させ、
RunPod側はこのPacketを画像化するだけとする設計(docs/manga-pipeline.md
参照)。

scripts/validate_manga.pyはこのモジュールの構造検証に加え、
scripts/banned_terms.pyの禁止語検証を行う。
"""

PACKET_VERSION = 1

# manga/characters.mdで定義された5人のレギュラーのみ許可する。
ALLOWED_CHARACTERS = ["ハルト", "ナツキ", "アキラ", "フユミ", "書記官"]

# worldbookの「1話の登場人物は原則として最大3人」をX用4コマ版にも適用する
# (docs/worldbook.mdの「X用4コマ版」節参照)。
MAX_CHARACTERS_PER_EPISODE = 3

# X用4コマ版は4コマ固定(docs/worldbook.mdの「X用4コマ版」節参照)。
PANEL_COUNT = 4

# ハルト表情セットのファイル名体系(00-neutral〜30-speaking-forceful、
# 計31種)に対応させる。neutralのみ強度指定なしの単独タグとし、他の10種は
# 強度(weak/medium/strong)付きの複合タグとする(1 + 10×3 = 31)。
EXPRESSION_BASE_TAGS_NO_INTENSITY = ["neutral"]
EXPRESSION_BASE_TAGS_WITH_INTENSITY = [
    "joy",
    "surprise",
    "confusion",
    "worry",
    "anger",
    "sadness",
    "embarrassment",
    "determination",
    "tears",
    "speaking",
]
EXPRESSION_INTENSITIES = ["weak", "medium", "strong"]


def _build_allowed_expression_tags():
    tags = set(EXPRESSION_BASE_TAGS_NO_INTENSITY)
    for base in EXPRESSION_BASE_TAGS_WITH_INTENSITY:
        for intensity in EXPRESSION_INTENSITIES:
            tags.add(f"{base}-{intensity}")
    return tags


ALLOWED_EXPRESSION_TAGS = _build_allowed_expression_tags()

REQUIRED_SOURCE_STR_FIELDS = ["title", "url", "summary"]
REQUIRED_PANEL_STR_FIELDS = [
    "scene",
    "dialogue",
    "expression",
    "background",
    "image_prompt",
    "reference_image",
]


def validate_source(source):
    """source(元記事タイトル・URL・中立要約)を検証する。"""
    if not isinstance(source, dict):
        return ["sourceがオブジェクトではありません"]

    reasons = []
    for field in REQUIRED_SOURCE_STR_FIELDS:
        value = source.get(field)
        if not isinstance(value, str) or value == "":
            reasons.append(f"source.{field}が不正です(空でない文字列である必要)")
    return reasons


def validate_characters(characters):
    """登場キャラクター一覧を検証する(許可された5人のみ・最大3人・重複なし)。"""
    if not isinstance(characters, list):
        return ["charactersが配列ではありません"]

    reasons = []
    if len(characters) == 0:
        reasons.append("charactersが0人です")
    if len(characters) > MAX_CHARACTERS_PER_EPISODE:
        reasons.append(
            f"charactersが{MAX_CHARACTERS_PER_EPISODE}人を超えています({len(characters)}人)"
        )

    seen = []
    for name in characters:
        if not isinstance(name, str):
            reasons.append(f"charactersの要素が文字列ではありません: {name!r}")
            continue
        if name not in ALLOWED_CHARACTERS:
            reasons.append(
                f"charactersに許可されていない名前があります: {name!r}"
                f"(許可: {', '.join(ALLOWED_CHARACTERS)})"
            )
        if name in seen:
            reasons.append(f"charactersに重複があります: {name!r}")
        seen.append(name)

    return reasons


def validate_panel(panel, index):
    """panels[index]の1コマ分を検証する。"""
    if not isinstance(panel, dict):
        return [f"panels[{index}]がオブジェクトではありません"]

    reasons = []
    if panel.get("panel_no") != index + 1:
        reasons.append(
            f"panels[{index}].panel_noが{index + 1}である必要があります: {panel.get('panel_no')!r}"
        )

    for field in REQUIRED_PANEL_STR_FIELDS:
        value = panel.get(field)
        if not isinstance(value, str) or value == "":
            reasons.append(f"panels[{index}].{field}が不正です(空でない文字列である必要)")

    expression = panel.get("expression")
    if isinstance(expression, str) and expression != "" and expression not in ALLOWED_EXPRESSION_TAGS:
        reasons.append(f"panels[{index}].expressionが不正な表情タグです: {expression!r}")

    return reasons


def validate_packet(packet):
    """Manga News Packetの構造を検証し、違反理由のリストを返す(空なら合格)。"""
    if not isinstance(packet, dict):
        return ["パケットのルートはオブジェクトである必要があります"]

    reasons = []

    if packet.get("packet_version") != PACKET_VERSION:
        reasons.append(
            f"packet_versionが不正です({PACKET_VERSION}である必要): {packet.get('packet_version')!r}"
        )

    if not isinstance(packet.get("created_at"), str) or not packet.get("created_at"):
        reasons.append("created_atが不正です(空でない文字列である必要)")

    reasons.extend(validate_source(packet.get("source")))

    if not isinstance(packet.get("isekai_text"), str) or not packet.get("isekai_text"):
        reasons.append("isekai_textが不正です(空でない文字列である必要)")

    if not isinstance(packet.get("scribe_note"), str) or not packet.get("scribe_note"):
        reasons.append("scribe_noteが不正です(空でない文字列である必要)")

    reasons.extend(validate_characters(packet.get("characters")))

    panels = packet.get("panels")
    if not isinstance(panels, list):
        reasons.append("panelsが配列ではありません")
    else:
        if len(panels) != PANEL_COUNT:
            reasons.append(f"panelsは{PANEL_COUNT}要素である必要があります({len(panels)}要素)")
        for idx, panel in enumerate(panels):
            reasons.extend(validate_panel(panel, idx))

    cautions = packet.get("cautions")
    if not isinstance(cautions, list):
        reasons.append("cautionsが配列ではありません")
    elif not all(isinstance(item, str) for item in cautions):
        reasons.append("cautionsの各要素は文字列である必要があります")

    return reasons
