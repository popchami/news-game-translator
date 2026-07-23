"""異世界ニホン X用5コマ構成 Manga News Packet(v2)のスキーマ定義。

news_schema.pyの作りに合わせ、Termux(NGT)が生成しRunPod側アプリへ渡す
構造化JSON(Manga News Packet)の構造検証関数を提供する。ニュース解釈・
5コマ構成・セリフ・画像生成用プロンプトはすべてTermux側で確定させ、
RunPod側はこのPacketを画像化するだけとする設計(docs/manga-pipeline.md
参照)。

v1からv2への変更点(2026-07-23、正本テンプレート仕様確定に伴う一括移行。
実運用中のv1データは存在しなかったため、後方互換コードは持たない):

- panels(第1〜4コマ)は、1コマ1人・単一dialogue文字列という制約を廃止し、
  1コマ最大2人(performers)・複数吹き出し(dialogues)を持てる構造へ変更
- panelごとのrole(コマの役割)を自由記述からsetup/development/turn/
  resolutionの固定4値へ変更し、panel_noとの対応を必須化
  (旧仕様は任意フィールドで自由記述可、値は例示のみだった)
- performerごとに position/facing/gaze/expression/reference_imageを持ち、
  1コマの構図(画角=camera_angle・フレーミング=framing)も必須化
- 第5コマは、旧仕様と同じくpanelsには含めず、scribe_note(解説本文)に
  加えて新設のscribe_panel(layout/expression/reference_image/
  emblem_reference)を追加。書記官の正本画像(表情31・turnaround4・
  equipment〔書記局章〕1)はcomfyui-mobile-system側で登録・Release公開が
  完了したため、書記官の参照画像を初めて指定できるようになった
- 旧`validate_chatgpt_route`(panels をハルト・ナツキの2人に固定する
  ChatGPTルート専用の追加検証)は廃止した。v2のcharacters/performers検証が
  「物語側2〜3人(ハルト・ナツキ・アキラ・フユミから選択)+書記官」という
  同等以上に厳密な制約を一般スキーマとして持つため、别レイヤーとして
  维持する理由がなくなったため(scripts/validate_manga.py参照)

scripts/validate_manga.pyはこのモジュールの構造検証に加え、
scripts/banned_terms.pyの禁止語検証を行う。
"""
import re
import unicodedata

PACKET_VERSION = 2

# manga/characters.mdで定義された5人のレギュラーのみ許可する。
STORY_CHARACTERS = ["ハルト", "ナツキ", "アキラ", "フユミ"]
SCRIBE_CHARACTER = "書記官"
ALLOWED_CHARACTERS = STORY_CHARACTERS + [SCRIBE_CHARACTER]

# Packetのcharacters(Japanese表示名)から、comfyui-mobile-system側の
# reference_images/<id>/ フォルダ名(ローマ字)への対応。両リポジトリ間の
# 接続契約であり、変更する場合は両リポジトリを同時に確認すること。
CHARACTER_REFERENCE_ID = {
    "ハルト": "haruto",
    "ナツキ": "natsuki",
    "アキラ": "akira",
    "フユミ": "fuyumi",
    "書記官": "scribe",
}

# 1話の登場人物: 書記官(必須・重複禁止)+物語側2〜3人(ハルト・ナツキ・
# アキラ・フユミから選択)。レギュラー総数の上限ではなく、1話あたりの上限。
MIN_STORY_CHARACTERS_PER_EPISODE = 2
MAX_STORY_CHARACTERS_PER_EPISODE = 3
MIN_CHARACTERS_PER_EPISODE = MIN_STORY_CHARACTERS_PER_EPISODE + 1  # 書記官込み
MAX_CHARACTERS_PER_EPISODE = MAX_STORY_CHARACTERS_PER_EPISODE + 1  # 書記官込み

# 第1〜4コマ(起承転結)だけがRunPodの画像生成対象。第5コマ(解説コマ)は
# panelsに含めず、scribe_note/scribe_panelとして別に持つ(v1から変更なし)。
PANEL_COUNT = 4

# panel_no(1〜4)に対応するroleの固定値。
ROLE_BY_PANEL_NO = {
    1: "setup",
    2: "development",
    3: "turn",
    4: "resolution",
}
ALLOWED_ROLES = list(ROLE_BY_PANEL_NO.values())

# performer.position(コマ内の人物の左右配置)。
POSITIONS = ["left", "center", "right"]

# dialogue.bubble_position(吹き出し本体の上下左右配置)。performer.position
# (人物の左右配置)とは意味が異なる独立したenum(2026-07-24、チャミ決定に
# より分離。以前はPOSITIONSを流用していたが、「吹き出しの位置」と「人物の
# 位置」は別概念のため、performer.positionとの一致は要求しない)。吹き出し
# 本体はupper/lowerのいずれかに置くが、吹き出しの尾はdialogue.speakerに
# 対応するperformerへ向ける(組版〔後処理〕側の設計であり、Packetの
# フィールドとしては尾の向きを別途持たない)。
BUBBLE_POSITIONS = [
    "upper_left", "upper_center", "upper_right",
    "lower_left", "lower_center", "lower_right",
]

# panel.camera_angle(カメラの高さ・角度)。framingとは独立した軸で、多様性
# 判定は(camera_angle, framing)の組み合わせで行う。自由記述は不採用
# (2026-07-24、チャミ決定。"eye level"/"eye-level"/"normal angle"等の表記
# 揺れにより連続構図の検証を回避できてしまうため、固定enumへ変更した)。
CAMERA_ANGLES = ["eye_level", "high_angle", "low_angle", "over_shoulder", "top_down"]

# performer.facing(向き)。
FACINGS = ["face_left", "face_right", "front", "three_quarter_left", "three_quarter_right"]

# performer.gaze(視線)。
GAZES = ["other_character", "object", "reader", "down", "off_panel_left", "off_panel_right"]

# panel.framing(フレーミング)。
FRAMINGS = ["close_up", "bust", "waist", "full", "wide"]

MAX_PERFORMERS_PER_PANEL = 2
MIN_DIALOGUES_PER_PANEL = 1
MAX_DIALOGUES_PER_PANEL = 2
MAX_CHARS_PER_BUBBLE = 24
MAX_CHARS_PER_BUBBLE_LINE = 12
MAX_LINES_PER_BUBBLE = 2
MAX_CHARS_PER_PANEL_DIALOGUE_TOTAL = 36
MAX_CAPTION_CHARS = 16

MAX_SCRIBE_NOTE_CHARS = 72
MAX_SCRIBE_NOTE_CHARS_PER_LINE = 18
MAX_SCRIBE_NOTE_LINES = 4

# 1話全体(第1〜4コマ)で、(camera_angle, framing)の組み合わせが最低
# 何種類必要か(「4コマ全体で最低3種類の画角またはフレーミングを使う」)。
MIN_DISTINCT_CAMERA_FRAMING_COMBOS = 3
# 全身(framing="full")構図は1話最大1コマ。
MAX_FULL_BODY_PANELS = 1

SCRIBE_PANEL_LAYOUT = "scribe-left_note-right"
SCRIBE_EMBLEM_REFERENCE = "scribe/equipment/official-scribe-bureau-emblem.png"

# ハルト表情セットの実ファイル名体系(チャミによる実物検証済み、確定):
#   00: neutral(強度指定なし)
#   01〜27: 9感情(joy/surprise/confusion/worry/anger/sadness/
#           embarrassment/determination/tears) × weak/medium/strong
#   28〜30: speakingのみ専用の強度語(small/normal/forceful)。
#           speakingにweak/medium/strongは使わない
# 合計 1 + 9×3 + 3 = 31種。expressionタグはこの体系に一致させる。
# ハルト・ナツキ・アキラ・フユミ・書記官の5キャラクターとも同一のタグ集合。
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
# 決定済み/未決定/今後の手続き。任意フィールドとし後方互換を維持する
# (未指定の既存Packetは従来通り合格する)。該当情報がない項目を無理に
# 埋める必要はないため、空文字列も許容する(必須3フィールドと異なり
# 非空チェックは行わない)。
OPTIONAL_SOURCE_STR_FIELDS = ["decided", "not_decided", "next_step"]

REQUIRED_PANEL_STR_FIELDS = [
    "scene",
    "background",
    "image_prompt",
    "negative_prompt",
]

# reference_image(論理ID)は「<character>/<tag>.png」形式(categoryを省略した
# 場合の既存の後方互換形式と同じ)。character segmentはCHARACTER_REFERENCE_ID
# のローマ字IDのいずれかに一致させる。`$`ではなく`\Z`を使う(Codexレビュー
# 指摘、Major: `$`はPythonの正規表現では末尾の改行の直前にもマッチするため、
# "haruto/neutral.png\n"のような末尾改行つきの値を誤って許可してしまう)。
REFERENCE_IMAGE_RE = re.compile(r"\A(?P<character>[a-z]+)/(?P<tag>[A-Za-z0-9._-]+)\.png\Z")

# セリフの「無言」判定用: 三点リーダー・中黒・ピリオドのみで構成される
# 文字列(正規化・改行除去後)を「内容のあるセリフ」ではないとして拒否する。
# U+22EF(MIDLINE HORIZONTAL ELLIPSIS、見た目上「…」と区別しづらい)も
# 対象に含める(Codexレビュー指摘、Major)。
_ELLIPSIS_ONLY_RE = re.compile(r"^[…⋯\.・]+$")


def _strip_all_whitespace(text):
    """三点リーダー等の間に空白(半角・全角とも)を挟んで判定を回避される
    ことを防ぐため、内部の空白もすべて除去してからellipsis-only判定を行う
    (Codexレビュー指摘、Major: 従来は行頭・行末の空白しか除去しておらず、
    "… …"のような中間に空白を挟んだ入力が素通りしていた)。
    """
    return re.sub(r"\s+", "", text)


def _normalize_text(value):
    """Unicode正規化(NFKC)し、前後の空白を除去する。"""
    return unicodedata.normalize("NFKC", value).strip()


def _bubble_lines(text):
    """セリフ本文を正規化した上で改行で分割し、各行の前後空白を除去した
    行のリストを返す(改行による文字数上限回避を防止するため、行ごとにも
    正規化する)。
    """
    normalized = _normalize_text(text)
    return [line.strip() for line in normalized.split("\n")]


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
    """登場キャラクター一覧を検証する。

    書記官を必須(重複禁止)、物語側(ハルト・ナツキ・アキラ・フユミから
    選択)を2〜3人とする(1話の登場人数の上限。レギュラー総数の上限では
    ない)。
    """
    if not isinstance(characters, list):
        return ["charactersが配列ではありません"]

    reasons = []
    if len(characters) < MIN_CHARACTERS_PER_EPISODE:
        reasons.append(
            f"charactersが{MIN_CHARACTERS_PER_EPISODE}人未満です({len(characters)}人)"
        )
    if len(characters) > MAX_CHARACTERS_PER_EPISODE:
        reasons.append(
            f"charactersが{MAX_CHARACTERS_PER_EPISODE}人を超えています({len(characters)}人)"
        )

    seen = []
    story_count = 0
    scribe_count = 0
    for name in characters:
        if not isinstance(name, str):
            reasons.append(f"charactersの要素が文字列ではありません: {name!r}")
            continue
        if name not in ALLOWED_CHARACTERS:
            reasons.append(
                f"charactersに許可されていない名前があります: {name!r}"
                f"(許可: {', '.join(ALLOWED_CHARACTERS)})"
            )
        elif name == SCRIBE_CHARACTER:
            scribe_count += 1
        else:
            story_count += 1
        if name in seen:
            reasons.append(f"charactersに重複があります: {name!r}")
        seen.append(name)

    if scribe_count == 0:
        reasons.append(f"charactersに{SCRIBE_CHARACTER}が含まれていません(必須)")

    if scribe_count <= 1:
        # 物語側人数の範囲チェックは、書記官の有無・重複が正しい場合のみ
        # 意味を持つ数値なので、明らかにおかしい場合(書記官が2人以上等)は
        # 別のreasonで既に報告済みのため、ここでの重複報告は避ける。
        if story_count < MIN_STORY_CHARACTERS_PER_EPISODE:
            reasons.append(
                f"{SCRIBE_CHARACTER}以外のcharactersが{MIN_STORY_CHARACTERS_PER_EPISODE}人未満です"
                f"({story_count}人)"
            )
        if story_count > MAX_STORY_CHARACTERS_PER_EPISODE:
            reasons.append(
                f"{SCRIBE_CHARACTER}以外のcharactersが{MAX_STORY_CHARACTERS_PER_EPISODE}人を超えています"
                f"({story_count}人)"
            )

    return reasons


def _validate_reference_image(reference_image, expected_character_id, expected_tag, field_label):
    """reference_image(論理ID)が、期待するcharacter(ローマ字ID)・tagと
    一致する`<character>/<tag>.png`形式であることを検証する。
    """
    if not isinstance(reference_image, str) or reference_image == "":
        return [f"{field_label}が不正です(空でない文字列である必要)"]

    m = REFERENCE_IMAGE_RE.match(reference_image)
    if not m:
        return [f"{field_label}の形式が不正です(<character>/<tag>.png形式である必要): {reference_image!r}"]

    if m.group("character") != expected_character_id:
        return [
            f"{field_label}のcharacter部分が一致しません"
            f"(期待: {expected_character_id!r}, 実際: {m.group('character')!r}): {reference_image!r}"
        ]
    if m.group("tag") != expected_tag:
        return [
            f"{field_label}のタグがexpressionと一致しません"
            f"(expression: {expected_tag!r}, reference_image: {m.group('tag')!r})"
        ]
    return []


def validate_performer(performer, panel_index, performer_index, characters):
    """panels[panel_index].performers[performer_index]を検証する。"""
    if not isinstance(performer, dict):
        return [f"panels[{panel_index}].performers[{performer_index}]がオブジェクトではありません"]

    label = f"panels[{panel_index}].performers[{performer_index}]"
    reasons = []

    name = performer.get("name")
    if not isinstance(name, str) or name == "":
        reasons.append(f"{label}.nameが不正です(空でない文字列である必要)")
    else:
        if name not in ALLOWED_CHARACTERS:
            reasons.append(
                f"{label}.nameが許可されていないキャラクター名です: {name!r}"
                f"(許可: {', '.join(ALLOWED_CHARACTERS)})"
            )
        if isinstance(characters, list) and name not in characters:
            reasons.append(f"{label}.nameがPacketのcharactersに存在しません: {name!r}")
        if name == SCRIBE_CHARACTER:
            reasons.append(f"{label}に{SCRIBE_CHARACTER}を登場させることはできません(第5コマ専任)")

    position = performer.get("position")
    if position not in POSITIONS:
        reasons.append(f"{label}.positionが不正です(許可: {', '.join(POSITIONS)}): {position!r}")

    facing = performer.get("facing")
    if facing not in FACINGS:
        reasons.append(f"{label}.facingが不正です(許可: {', '.join(FACINGS)}): {facing!r}")

    gaze = performer.get("gaze")
    if gaze not in GAZES:
        reasons.append(f"{label}.gazeが不正です(許可: {', '.join(GAZES)}): {gaze!r}")

    expression = performer.get("expression")
    if not isinstance(expression, str) or expression not in ALLOWED_EXPRESSION_TAGS:
        reasons.append(f"{label}.expressionが不正な表情タグです: {expression!r}")

    reference_image = performer.get("reference_image")
    if isinstance(name, str) and name in CHARACTER_REFERENCE_ID and isinstance(expression, str):
        reasons.extend(
            _validate_reference_image(
                reference_image,
                CHARACTER_REFERENCE_ID[name],
                expression,
                f"{label}.reference_image",
            )
        )
    elif not isinstance(reference_image, str) or reference_image == "":
        reasons.append(f"{label}.reference_imageが不正です(空でない文字列である必要)")

    return reasons


def validate_dialogue(dialogue, panel_index, dialogue_index, performer_names):
    """panels[panel_index].dialogues[dialogue_index]を検証する。"""
    if not isinstance(dialogue, dict):
        return [f"panels[{panel_index}].dialogues[{dialogue_index}]がオブジェクトではありません"]

    label = f"panels[{panel_index}].dialogues[{dialogue_index}]"
    reasons = []

    speaker = dialogue.get("speaker")
    if not isinstance(speaker, str) or speaker == "":
        reasons.append(f"{label}.speakerが不正です(空でない文字列である必要)")
    elif speaker not in performer_names:
        reasons.append(f"{label}.speakerが同じコマのperformersに存在しません: {speaker!r}")

    text = dialogue.get("text")
    if not isinstance(text, str) or text == "":
        reasons.append(f"{label}.textが不正です(空でない文字列である必要)")
    else:
        lines = _bubble_lines(text)
        if any(line == "" for line in lines):
            reasons.append(f"{label}.textに空行が含まれています")
        if len(lines) > MAX_LINES_PER_BUBBLE:
            reasons.append(
                f"{label}.textが{MAX_LINES_PER_BUBBLE}行を超えています({len(lines)}行)"
            )
        for line_no, line in enumerate(lines):
            if len(line) > MAX_CHARS_PER_BUBBLE_LINE:
                reasons.append(
                    f"{label}.textの{line_no + 1}行目が{MAX_CHARS_PER_BUBBLE_LINE}文字を"
                    f"超えています({len(line)}文字)"
                )
        total_chars = sum(len(line) for line in lines)
        if total_chars > MAX_CHARS_PER_BUBBLE:
            reasons.append(
                f"{label}.textが{MAX_CHARS_PER_BUBBLE}文字を超えています({total_chars}文字)"
            )
        joined = _strip_all_whitespace("".join(lines))
        if joined != "" and _ELLIPSIS_ONLY_RE.match(joined):
            reasons.append(f"{label}.textが三点リーダー等のみで内容がありません: {text!r}")

    bubble_position = dialogue.get("bubble_position")
    if bubble_position not in BUBBLE_POSITIONS:
        reasons.append(
            f"{label}.bubble_positionが不正です(許可: {', '.join(BUBBLE_POSITIONS)}): {bubble_position!r}"
        )

    return reasons


def _dialogue_total_chars(dialogue):
    text = dialogue.get("text")
    if not isinstance(text, str):
        return 0
    return sum(len(line) for line in _bubble_lines(text))


def validate_panel(panel, index, characters=None):
    """panels[index]の1コマ分を検証する。

    charactersはPacketルートのcharacters配列(performer.nameの存在確認用)。
    未指定(単体テスト等でpanel単独検証する場合)はperformer.nameの
    characters整合チェックのみ省略する。
    """
    if not isinstance(panel, dict):
        return [f"panels[{index}]がオブジェクトではありません"]

    reasons = []
    panel_no = panel.get("panel_no")
    # bool は int のサブクラスであり True == 1 が成立するため、明示的に
    # bool を除外しないと panel_no: true が 1 として通ってしまう
    # (Codexレビュー指摘、v1から継続)。
    if isinstance(panel_no, bool) or panel_no != index + 1:
        reasons.append(
            f"panels[{index}].panel_noが{index + 1}である必要があります: {panel_no!r}"
        )

    role = panel.get("role")
    expected_role = ROLE_BY_PANEL_NO.get(index + 1)
    if role not in ALLOWED_ROLES:
        reasons.append(f"panels[{index}].roleが不正です(許可: {', '.join(ALLOWED_ROLES)}): {role!r}")
    elif expected_role is not None and role != expected_role:
        reasons.append(
            f"panels[{index}].roleがpanel_noと一致しません"
            f"(panel_no={index + 1}には{expected_role!r}が必要): {role!r}"
        )

    for field in REQUIRED_PANEL_STR_FIELDS:
        value = panel.get(field)
        if not isinstance(value, str) or value == "":
            reasons.append(f"panels[{index}].{field}が不正です(空でない文字列である必要)")

    framing = panel.get("framing")
    if framing not in FRAMINGS:
        reasons.append(f"panels[{index}].framingが不正です(許可: {', '.join(FRAMINGS)}): {framing!r}")

    camera_angle = panel.get("camera_angle")
    if camera_angle not in CAMERA_ANGLES:
        reasons.append(
            f"panels[{index}].camera_angleが不正です(許可: {', '.join(CAMERA_ANGLES)}): {camera_angle!r}"
        )

    if "caption" in panel:
        caption = panel.get("caption")
        if not isinstance(caption, str):
            reasons.append(f"panels[{index}].captionが不正です(指定する場合は文字列である必要): {caption!r}")
        elif len(_normalize_text(caption)) > MAX_CAPTION_CHARS:
            reasons.append(
                f"panels[{index}].captionが{MAX_CAPTION_CHARS}文字を超えています"
            )

    performers = panel.get("performers")
    performer_names = []
    if not isinstance(performers, list) or not performers:
        reasons.append(f"panels[{index}].performersが不正です(1〜{MAX_PERFORMERS_PER_PANEL}人の配列である必要)")
    else:
        if len(performers) > MAX_PERFORMERS_PER_PANEL:
            reasons.append(
                f"panels[{index}].performersが{MAX_PERFORMERS_PER_PANEL}人を超えています({len(performers)}人)"
            )
        seen_names = []
        for p_idx, performer in enumerate(performers):
            reasons.extend(validate_performer(performer, index, p_idx, characters))
            if isinstance(performer, dict):
                name = performer.get("name")
                if isinstance(name, str):
                    if name in seen_names:
                        reasons.append(f"panels[{index}].performersに同じ人物が重複しています: {name!r}")
                    seen_names.append(name)
                    performer_names.append(name)

    dialogues = panel.get("dialogues")
    if not isinstance(dialogues, list) or len(dialogues) < MIN_DIALOGUES_PER_PANEL:
        reasons.append(
            f"panels[{index}].dialoguesが不正です"
            f"({MIN_DIALOGUES_PER_PANEL}〜{MAX_DIALOGUES_PER_PANEL}個の配列である必要、空配列は禁止)"
        )
    else:
        if len(dialogues) > MAX_DIALOGUES_PER_PANEL:
            reasons.append(
                f"panels[{index}].dialoguesが{MAX_DIALOGUES_PER_PANEL}個を超えています({len(dialogues)}個)"
            )
        seen_positions = []
        total_chars = 0
        for d_idx, dialogue in enumerate(dialogues):
            reasons.extend(validate_dialogue(dialogue, index, d_idx, performer_names))
            if isinstance(dialogue, dict):
                bubble_position = dialogue.get("bubble_position")
                if bubble_position is not None:
                    if bubble_position in seen_positions:
                        reasons.append(
                            f"panels[{index}].dialoguesのbubble_positionが重複しています: {bubble_position!r}"
                        )
                    seen_positions.append(bubble_position)
                total_chars += _dialogue_total_chars(dialogue)
        if total_chars > MAX_CHARS_PER_PANEL_DIALOGUE_TOTAL:
            reasons.append(
                f"panels[{index}]のセリフ合計が{MAX_CHARS_PER_PANEL_DIALOGUE_TOTAL}文字を"
                f"超えています({total_chars}文字)"
            )

    return reasons


def _validate_panel_diversity(panels):
    """第1〜4コマ全体の画角・フレーミングの多様性を検証する。

    - 連続する2コマで(camera_angle, framing)の組が同一の場合は拒否
    - 4コマ全体で(camera_angle, framing)の組が最低3種類必要
    - 全身(framing="full")構図は1話最大1コマ
    """
    if not isinstance(panels, list):
        return []

    reasons = []
    combos = []
    full_body_count = 0
    for panel in panels:
        if not isinstance(panel, dict):
            combos.append(None)
            continue
        camera_angle = panel.get("camera_angle")
        framing = panel.get("framing")
        # camera_angle/framingが文字列以外(dict/list等)の不正値だと、
        # (camera_angle, framing)のタプルがハッシュ不能になり、後段の
        # 集合(set)構築でTypeErrorが発生する(Codexレビュー指摘、Major)。
        # 型が不正な組は多様性判定の対象外(None)として扱う(型自体の
        # エラーはvalidate_panel側のcamera_angle/framing enumチェックが
        # 別途報告する)。
        if isinstance(camera_angle, str) and isinstance(framing, str):
            combos.append((camera_angle, framing))
        else:
            combos.append(None)
        if framing == "full":
            full_body_count += 1

    for i in range(1, len(combos)):
        if combos[i] is not None and combos[i] == combos[i - 1]:
            reasons.append(
                f"panels[{i - 1}]とpanels[{i}]の画角(camera_angle)とフレーミング(framing)が"
                "同一です(連続するコマで同じ構図を使わない)"
            )

    distinct = {c for c in combos if c is not None}
    if len(distinct) < MIN_DISTINCT_CAMERA_FRAMING_COMBOS:
        reasons.append(
            f"4コマ全体で画角またはフレーミングの種類が{MIN_DISTINCT_CAMERA_FRAMING_COMBOS}種類未満です"
            f"({len(distinct)}種類)"
        )

    if full_body_count > MAX_FULL_BODY_PANELS:
        reasons.append(
            f"全身構図(framing=full)が1話最大{MAX_FULL_BODY_PANELS}コマを超えています"
            f"({full_body_count}コマ)"
        )

    return reasons


def validate_scribe_panel(scribe_panel):
    """Packetルートのscribe_panel(第5コマ、書記官の解説)を検証する。"""
    if not isinstance(scribe_panel, dict):
        return ["scribe_panelがオブジェクトではありません"]

    reasons = []

    layout = scribe_panel.get("layout")
    if layout != SCRIBE_PANEL_LAYOUT:
        reasons.append(f"scribe_panel.layoutが不正です({SCRIBE_PANEL_LAYOUT!r}である必要): {layout!r}")

    expression = scribe_panel.get("expression")
    if not isinstance(expression, str) or expression not in ALLOWED_EXPRESSION_TAGS:
        reasons.append(f"scribe_panel.expressionが不正な表情タグです: {expression!r}")

    reference_image = scribe_panel.get("reference_image")
    if isinstance(expression, str):
        reasons.extend(
            _validate_reference_image(
                reference_image,
                CHARACTER_REFERENCE_ID[SCRIBE_CHARACTER],
                expression,
                "scribe_panel.reference_image",
            )
        )
    elif not isinstance(reference_image, str) or reference_image == "":
        reasons.append("scribe_panel.reference_imageが不正です(空でない文字列である必要)")

    emblem_reference = scribe_panel.get("emblem_reference")
    if emblem_reference != SCRIBE_EMBLEM_REFERENCE:
        reasons.append(
            f"scribe_panel.emblem_referenceが不正です({SCRIBE_EMBLEM_REFERENCE!r}である必要): "
            f"{emblem_reference!r}"
        )

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

    scribe_note = packet.get("scribe_note")
    if not isinstance(scribe_note, str) or scribe_note == "":
        reasons.append("scribe_noteが不正です(空でない文字列である必要)")
    else:
        lines = _bubble_lines(scribe_note)
        joined = "".join(lines)
        # 空白・改行のみ、または三点リーダー等の記号のみのscribe_noteは、
        # 文字列としては非空でも実質的に内容がないため拒否する(第5コマの
        # 唯一のテキストであり、dialoguesの「無言コマ不採用」と同じ趣旨。
        # Codexレビューで発見された最小長チェックの抜け、2026-07-24修正)。
        if joined == "":
            reasons.append("scribe_noteが不正です(空白のみは空文字列として扱い拒否)")
        elif _ELLIPSIS_ONLY_RE.match(_strip_all_whitespace(joined)):
            reasons.append(f"scribe_noteが三点リーダー等のみで内容がありません: {scribe_note!r}")
        if len(lines) > MAX_SCRIBE_NOTE_LINES:
            reasons.append(f"scribe_noteが{MAX_SCRIBE_NOTE_LINES}行を超えています({len(lines)}行)")
        for line_no, line in enumerate(lines):
            if len(line) > MAX_SCRIBE_NOTE_CHARS_PER_LINE:
                reasons.append(
                    f"scribe_noteの{line_no + 1}行目が{MAX_SCRIBE_NOTE_CHARS_PER_LINE}文字を"
                    f"超えています({len(line)}文字)"
                )
        total_chars = sum(len(line) for line in lines)
        if total_chars > MAX_SCRIBE_NOTE_CHARS:
            reasons.append(f"scribe_noteが{MAX_SCRIBE_NOTE_CHARS}文字を超えています({total_chars}文字)")

    characters = packet.get("characters")
    reasons.extend(validate_characters(characters))
    characters_for_panels = characters if isinstance(characters, list) else None

    panels = packet.get("panels")
    if not isinstance(panels, list):
        reasons.append("panelsが配列ではありません")
    else:
        if len(panels) != PANEL_COUNT:
            reasons.append(f"panelsは{PANEL_COUNT}要素である必要があります({len(panels)}要素)")
        for idx, panel in enumerate(panels):
            reasons.extend(validate_panel(panel, idx, characters_for_panels))
        reasons.extend(_validate_panel_diversity(panels))

    reasons.extend(validate_scribe_panel(packet.get("scribe_panel")))

    cautions = packet.get("cautions")
    if not isinstance(cautions, list):
        reasons.append("cautionsが配列ではありません")
    elif not all(isinstance(item, str) for item in cautions):
        reasons.append("cautionsの各要素は文字列である必要があります")

    return reasons
