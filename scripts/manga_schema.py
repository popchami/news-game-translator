"""異世界ニホン4コマ版 Manga News Packetのスキーマ定義。

news_schema.pyの作りに合わせ、Termux(NGT)が生成しRunPod側アプリへ渡す
構造化JSON(Manga News Packet)の構造検証関数を提供する。ニュース解釈・
4コマ構成・セリフ・画像生成用プロンプトはすべてTermux側で確定させ、
RunPod側はこのPacketを画像化するだけとする設計(docs/manga-pipeline.md
参照)。

scripts/validate_manga.pyはこのモジュールの構造検証に加え、
scripts/banned_terms.pyの禁止語検証を行う。
"""
import re

PACKET_VERSION = 1

# manga/characters.mdで定義された5人のレギュラーのみ許可する。
ALLOWED_CHARACTERS = ["ハルト", "ナツキ", "アキラ", "フユミ", "書記官"]

# worldbookの「1話の登場人物は原則として最大3人」をX用4コマ版にも適用する
# (docs/worldbook.mdの「X用4コマ版」節参照)。
MAX_CHARACTERS_PER_EPISODE = 3

# X用4コマ版は4コマ固定(docs/worldbook.mdの「X用4コマ版」節参照)。
PANEL_COUNT = 4

# ハルト表情セットの実ファイル名体系(チャミによる実物検証済み、確定):
#   00: neutral(強度指定なし)
#   01〜27: 9感情(joy/surprise/confusion/worry/anger/sadness/
#           embarrassment/determination/tears) × weak/medium/strong
#   28〜30: speakingのみ専用の強度語(small/normal/forceful)。
#           speakingにweak/medium/strongは使わない
# 合計 1 + 9×3 + 3 = 31種。expressionタグはこの体系に一致させる。
EXPRESSION_BASE_TAGS_NO_INTENSITY = ["neutral"]
EXPRESSION_STANDARD_INTENSITY_BASE_TAGS = [
    "joy",
    "surprise",
    "confusion",
    "worry",
    "anger",
    "sadness",
    "embarrassment",
    "determination",
    "tears",
]
EXPRESSION_STANDARD_INTENSITIES = ["weak", "medium", "strong"]

# speakingのみ、上記と異なる専用の強度語を使う(01〜27の9感情とは別体系)。
EXPRESSION_SPEAKING_BASE_TAG = "speaking"
EXPRESSION_SPEAKING_INTENSITIES = ["small", "normal", "forceful"]


def _build_allowed_expression_tags():
    tags = set(EXPRESSION_BASE_TAGS_NO_INTENSITY)
    for base in EXPRESSION_STANDARD_INTENSITY_BASE_TAGS:
        for intensity in EXPRESSION_STANDARD_INTENSITIES:
            tags.add(f"{base}-{intensity}")
    for intensity in EXPRESSION_SPEAKING_INTENSITIES:
        tags.add(f"{EXPRESSION_SPEAKING_BASE_TAG}-{intensity}")
    return tags


ALLOWED_EXPRESSION_TAGS = _build_allowed_expression_tags()

# created_atはISO 8601形式の日時文字列を要求する(prompts/manga_script.md
# 参照)。厳密なISO 8601全体の網羅ではなく、この用途で実際に出力される
# 形式(YYYY-MM-DDTHH:MM:SS + 任意の小数秒 + Zまたは±HH:MM)を検査する。
ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)


def is_valid_iso8601(value):
    return isinstance(value, str) and bool(ISO8601_RE.match(value))

REQUIRED_SOURCE_STR_FIELDS = ["title", "url", "summary"]
# 決定済み/未決定/今後の手続き。ChatGPTルート(docs/manga-pipeline.md)の
# Step1で使うが、任意フィールドとし後方互換を維持する(未指定の既存Packetは
# 従来通り合格する)。該当情報がない項目を無理に埋める必要はないため、
# 空文字列も許容する(必須3フィールドと異なり非空チェックは行わない)。
OPTIONAL_SOURCE_STR_FIELDS = ["decided", "not_decided", "next_step"]
REQUIRED_PANEL_STR_FIELDS = [
    "scene",
    "dialogue",
    "expression",
    "background",
    "image_prompt",
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

    for field in OPTIONAL_SOURCE_STR_FIELDS:
        if field not in source:
            continue
        value = source.get(field)
        if not isinstance(value, str):
            reasons.append(f"source.{field}が不正です(指定する場合は文字列である必要): {value!r}")
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


def _validate_panel_reference_images(panel, index):
    """panels[index]のreference_image(単数・既存)/reference_images(複数・新規)
    を検証する。

    既存Packetとの後方互換のため、両方式は排他的に扱う: reference_images
    (キャラクター名→ファイル名の辞書。1コマに複数キャラが映る新仕様
    〔docs/manga-pipeline.md ChatGPTルート〕向け)が指定されていればそちらを
    検証し、指定されていなければ従来通りreference_image(単数の非空文字列)を
    必須として検証する。両方同時指定はあいまいさを避けるため拒否する。
    """
    has_single = "reference_image" in panel
    has_multi = "reference_images" in panel

    if has_single and has_multi:
        return [
            f"panels[{index}]にreference_imageとreference_imagesを同時に指定できません"
        ]

    if has_multi:
        value = panel.get("reference_images")
        if not isinstance(value, dict) or not value:
            return [
                f"panels[{index}].reference_imagesが不正です(空でないオブジェクトである必要)"
            ]
        reasons = []
        for name, filename in value.items():
            if name not in ALLOWED_CHARACTERS:
                reasons.append(
                    f"panels[{index}].reference_imagesに許可されていないキャラクター名があります: "
                    f"{name!r}(許可: {', '.join(ALLOWED_CHARACTERS)})"
                )
            if not isinstance(filename, str) or filename == "":
                reasons.append(
                    f"panels[{index}].reference_images[{name!r}]が不正です(空でない文字列である必要)"
                )
        return reasons

    value = panel.get("reference_image")
    if not isinstance(value, str) or value == "":
        return [f"panels[{index}].reference_imageが不正です(空でない文字列である必要)"]
    return []


def validate_panel(panel, index):
    """panels[index]の1コマ分を検証する。"""
    if not isinstance(panel, dict):
        return [f"panels[{index}]がオブジェクトではありません"]

    reasons = []
    panel_no = panel.get("panel_no")
    # bool は int のサブクラスであり True == 1 が成立するため、明示的に
    # bool を除外しないと panel_no: true が 1 として通ってしまう
    # (Codexレビュー指摘)。
    if isinstance(panel_no, bool) or panel_no != index + 1:
        reasons.append(
            f"panels[{index}].panel_noが{index + 1}である必要があります: {panel_no!r}"
        )

    for field in REQUIRED_PANEL_STR_FIELDS:
        value = panel.get(field)
        if not isinstance(value, str) or value == "":
            reasons.append(f"panels[{index}].{field}が不正です(空でない文字列である必要)")

    reasons.extend(_validate_panel_reference_images(panel, index))

    expression = panel.get("expression")
    if isinstance(expression, str) and expression != "" and expression not in ALLOWED_EXPRESSION_TAGS:
        reasons.append(f"panels[{index}].expressionが不正な表情タグです: {expression!r}")

    # role(コマの役割。例: introduction/question/explanation/current_status)
    # は任意フィールド。固定enumにはせず、指定する場合は空でない文字列である
    # ことのみ検証する(運用の変化に対応しやすくするため。具体的な語彙は
    # prompts/manga_script.mdで規定する)。
    role = panel.get("role")
    if "role" in panel and (not isinstance(role, str) or role == ""):
        reasons.append(f"panels[{index}].roleが不正です(指定する場合は空でない文字列である必要): {role!r}")

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

    if not is_valid_iso8601(packet.get("created_at")):
        reasons.append(
            f"created_atが不正です(ISO 8601形式の日時文字列である必要): {packet.get('created_at')!r}"
        )

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
