#!/usr/bin/env python3
"""ChatGPT漫画生成ルート向けに、Manga News Packetが参照する正本画像
(ハルト・ナツキ)一式を、comfyui-mobile-system側のローカルチェックアウトから
まとめて収集するスクリプト。

正本画像の実体(PNG)はnews-game-translator側には存在せず、別リポジトリ
comfyui-mobile-system側(profiles/sdxl/isekai_nihon_manga/reference_images/
<character>/)にGitHub Release資産として取得済みの前提とする(取得手順は
そちら側のscripts/fetch_reference_images.py参照)。本スクリプトはネットワーク
アクセスを一切行わず、ローカルファイルの解決・コピーのみを行う。
comfyui-mobile-system側のパスが見つからない、または個別の参照画像が
まだfetch_reference_images.py未実行で存在しない場合は、その旨を明確な
エラーとして報告して停止する(存在しないふりをして処理を続けない)。

論理ID(<character>/<tag>.png または <character>/<category>/<tag>.png)から
実ファイルへの解決ロジックは、comfyui-mobile-system側の
scripts/resolve_reference_image.pyの仕様(manifest.json経由の解決、
category省略時はexpressions扱い、予約キー・ドットのみセグメントの拒否、
ベースディレクトリ封じ込め)を踏襲した最小限の再実装である(別リポジトリの
ため直接importはしない。解決ロジックの正本はcomfyui-mobile-system側)。
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

DEFAULT_COMFYUI_MOBILE_SYSTEM_PATH = Path("/root/comfyui-mobile-system")
REFERENCE_IMAGES_REL = Path("profiles/sdxl/isekai_nihon_manga/reference_images")

DEFAULT_CATEGORY = "expressions"
CATEGORY_PLACE_TO = {
    "expressions": "images",
    "turnaround": "turnaround/images",
    "equipment": "equipment/images",
}
CATEGORY_MANIFEST_REL = {
    "expressions": "manifest.json",
    "turnaround": "turnaround/manifest.json",
    "equipment": "equipment/manifest.json",
}

REFERENCE_IMAGE_RE = re.compile(
    r"^(?P<character>[A-Za-z0-9._-]+)/"
    r"(?:(?P<category>[A-Za-z0-9._-]+)/)?"
    r"(?P<tag>[A-Za-z0-9._-]+)\.png$"
)

# "."・".."等、ドットのみで構成されるセグメントを拒否する(comfyui-mobile-system
# 側resolve_reference_image.pyと同じ理由。文字クラスが"."を許可するため、
# character=".."のようなセグメントがディレクトリトラバーサルにつながりうる)。
_DOT_ONLY_RE = re.compile(r"^\.+$")

# ハルト・ナツキの4方向立ち絵、計8枚(--default-turnaroundで使う最小セット)。
DEFAULT_TURNAROUND_LOGICAL_IDS = [
    f"{character}/turnaround/{tag}.png"
    for character in ("haruto", "natsuki")
    for tag in ("front", "left-profile", "back", "right-profile")
]


class CollectError(Exception):
    """収集処理の失敗を表す。"""


def _resolve_contained(base_dir, relative_path, description):
    """base_dir配下に厳密に収まる形でrelative_pathを解決する。

    manifest.json内のファイル名は形式検証の対象外であり、"../../../outside.png"
    のような値が書かれていれば画像ディレクトリの外を指せてしまう
    (comfyui-mobile-system側で実際に見つかったCritical指摘と同種)。
    """
    base_dir = base_dir.resolve()
    target = (base_dir / relative_path).resolve()
    if target != base_dir and base_dir not in target.parents:
        raise CollectError(f"{description}がベースディレクトリの外を指しています(拒否): {relative_path!r}")
    return target


def parse_reference_image(reference_image):
    """reference_image文字列を (character, category, tag) に分解する。"""
    m = REFERENCE_IMAGE_RE.match(reference_image or "")
    if not m:
        raise CollectError(f"reference_imageの形式が不正です: {reference_image!r}")

    character = m.group("character")
    category = m.group("category") or DEFAULT_CATEGORY
    tag = m.group("tag")

    for seg in (character, category, tag):
        if seg.startswith("_"):
            raise CollectError(f"reference_imageに予約語(_始まり)は使用できません: {reference_image!r}")
        if _DOT_ONLY_RE.match(seg):
            raise CollectError(f"reference_imageのセグメントに不正な値が含まれています: {seg!r}")

    if category not in CATEGORY_PLACE_TO:
        raise CollectError(
            f"未知のcategoryです: {category!r}(許可: {', '.join(sorted(CATEGORY_PLACE_TO))})"
        )

    return character, category, tag


def resolve_source_path(comfyui_root, reference_image):
    """reference_image(論理ID)を、comfyui-mobile-system側の実ファイルパスへ
    解決する。パス未存在(fetch_reference_images.py未実行等)は明確な
    CollectErrorとして報告する。
    """
    character, category, tag = parse_reference_image(reference_image)
    character_dir = comfyui_root / REFERENCE_IMAGES_REL / character

    manifest_path = _resolve_contained(
        character_dir, CATEGORY_MANIFEST_REL[category], "categoryのmanifest"
    )
    if not manifest_path.is_file():
        raise CollectError(
            f"manifest.jsonが見つかりません: {manifest_path}"
            "(comfyui-mobile-system側でscripts/fetch_reference_images.pyを"
            f"実行済みか確認してください。--character {character})"
        )
    with manifest_path.open(encoding="utf-8") as f:
        manifest = json.load(f)

    entry = manifest.get(tag)
    if entry is None:
        raise CollectError(
            f"manifest.jsonにタグ{tag!r}の対応がありません: {manifest_path}"
        )
    filename = entry["file"] if isinstance(entry, dict) else entry

    images_dir = character_dir / CATEGORY_PLACE_TO[category]
    image_path = _resolve_contained(images_dir, filename, "manifestのファイル名")
    if not image_path.is_file():
        raise CollectError(
            f"参照画像の実ファイルが存在しません: {image_path}"
            "(comfyui-mobile-system側でscripts/fetch_reference_images.pyを"
            f"実行済みか確認してください。--character {character})"
        )
    return image_path


def extract_reference_images_from_packet(packet):
    """Manga News Packetのpanels[]から、参照されているreference_image
    (論理ID)一覧を重複なく抽出する(出現順を維持)。単数形
    (reference_image)・複数形(reference_images)の両方に対応する。
    書記官(scribe_note)は文字列フィールドのみで参照画像を持たないため、
    対象外(書記官の正本画像は現時点で未準備。docs/manga-pipeline.md参照)。
    """
    seen = []
    panels = packet.get("panels")
    if not isinstance(panels, list):
        return seen
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        if "reference_images" in panel:
            value = panel.get("reference_images")
            if isinstance(value, dict):
                for filename in value.values():
                    if isinstance(filename, str) and filename not in seen:
                        seen.append(filename)
        else:
            value = panel.get("reference_image")
            if isinstance(value, str) and value not in seen:
                seen.append(value)
    return seen


def collect(comfyui_root, reference_images, dest_dir):
    """reference_images(論理IDのリスト)を、comfyui_root配下から解決して
    dest_dirへコピーする。dest_dir配下のファイル名は論理IDの"/"を"__"へ
    置換した名前とする(衝突回避、拡張子はそのまま)。全件の解決に成功した
    場合のみコピーを行う(1件でも解決に失敗した場合は何もコピーしない)。
    戻り値は {reference_image: コピー先パス} の辞書。
    """
    if not comfyui_root.is_dir():
        raise CollectError(
            f"comfyui-mobile-systemのパスが見つかりません: {comfyui_root}"
            "(--comfyui-rootで正しいパスを指定してください)"
        )

    resolved = {ref: resolve_source_path(comfyui_root, ref) for ref in reference_images}

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for ref, source_path in resolved.items():
        dest_name = ref.replace("/", "__")
        dest_path = dest_dir / dest_name
        shutil.copyfile(source_path, dest_path)
        results[ref] = dest_path
    return results


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("dest_dir", help="収集先ディレクトリ")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--packet", help="Manga News PacketのJSONファイル")
    source_group.add_argument(
        "--logical-id",
        action="append",
        dest="logical_ids",
        help="収集する論理ID(複数指定可。例: haruto/neutral.png)",
    )
    source_group.add_argument(
        "--default-turnaround",
        action="store_true",
        help="ハルト・ナツキの4方向立ち絵、計8枚を収集する(最小セット)",
    )
    parser.add_argument(
        "--comfyui-root",
        default=str(DEFAULT_COMFYUI_MOBILE_SYSTEM_PATH),
        help=f"comfyui-mobile-systemのローカルチェックアウトパス(既定: {DEFAULT_COMFYUI_MOBILE_SYSTEM_PATH})",
    )
    args = parser.parse_args()

    if args.packet:
        with open(args.packet, encoding="utf-8") as f:
            packet = json.load(f)
        reference_images = extract_reference_images_from_packet(packet)
        if not reference_images:
            print("[ERROR] Packetに参照画像(reference_image/reference_images)が見つかりません", file=sys.stderr)
            sys.exit(1)
    elif args.default_turnaround:
        reference_images = list(DEFAULT_TURNAROUND_LOGICAL_IDS)
    else:
        reference_images = args.logical_ids

    try:
        results = collect(Path(args.comfyui_root), reference_images, args.dest_dir)
    except CollectError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    for ref, path in results.items():
        print(f"{ref} -> {path}")


if __name__ == "__main__":
    main()
