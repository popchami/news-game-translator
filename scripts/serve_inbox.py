#!/usr/bin/env python3
"""異世界ニホン5コマ構成 受信アプリ用のローカルHTTPサーバー(Phase 1)。

Termux上で起動し、app/isekai_inbox.html と drafts/manga_packets/ 配下の
Manga News Packet(JSON)を同一オリジンから配信する(file://の直接開きは
CORS制約により参照系リクエストが失敗するため)。Python標準ライブラリ
(http.server)のみで実装し、追加の依存導入は行わない。127.0.0.1のみで
待ち受け、同一端末内通信のみを想定する(docs/manga-pipeline.mdの
「通信(確定)」参照)。

RunPodへの接続・画像生成はこのサーバーの責務ではない(Phase 1ではまだ
実装しない。「マンガ生成」ボタンはapp/isekai_inbox.html側でダミー表示
するのみで、このサーバーは対応するAPIエンドポイントを持たない)。

起動: python3 scripts/serve_inbox.py
"""
import json
import pathlib
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_HTML = ROOT / "app" / "isekai_inbox.html"
PACKETS_DIR = ROOT / "drafts" / "manga_packets"

HOST = "127.0.0.1"
PORT = 8787

# 受け付けるPacketファイル名は英数字・.・_・-のみの.jsonファイルに限定する
# (ディレクトリトラバーサル対策)。
SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.json$")
PACKET_PATH_RE = re.compile(r"^/api/packets/([A-Za-z0-9._-]+\.json)$")


def _is_contained_in_packets_dir(path):
    """pathがPACKETS_DIR直下に実体として存在するかを確認する
    (シンボリックリンク等でPACKETS_DIR外を指すファイルを除外する)。
    list_packets・load_packetの両方で同じ判定基準を使う(Codexレビュー
    指摘: 以前はload_packetのみがこの境界チェックを持っていた)。
    """
    try:
        resolved = path.resolve()
    except OSError:
        return False
    try:
        packets_dir_resolved = PACKETS_DIR.resolve()
    except OSError:
        return False
    return resolved.parent == packets_dir_resolved


def list_packets():
    """PACKETS_DIR配下のPacket一覧を、日付・タイトル・状態つきで返す。

    構造検証はscripts/validate_manga.pyの責務であり、ここでは行わない
    (壊れたPacketファイルは一覧から静かに除外する)。
    """
    if not PACKETS_DIR.is_dir():
        return []

    items = []
    for path in sorted(PACKETS_DIR.glob("*.json")):
        if not _is_contained_in_packets_dir(path):
            continue
        try:
            with path.open(encoding="utf-8") as f:
                packet = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(packet, dict):
            continue
        source = packet.get("source")
        title = source.get("title", "") if isinstance(source, dict) else ""
        items.append(
            {
                "filename": path.name,
                "created_at": packet.get("created_at", ""),
                "title": title,
                # Phase 1・2ではRunPod接続・画像生成が未実装のため、状態は
                # 常に「生成待ち」を返す(Phase 3以降で実際の生成状態を
                # 反映する)。
                "status": "生成待ち",
            }
        )
    return items


def load_packet(filename):
    """PACKETS_DIR配下の単一Packetを読み込む。不正なファイル名・存在しない
    ファイル・JSON不正の場合はNoneを返す。
    """
    if not SAFE_FILENAME_RE.match(filename):
        return None

    path = PACKETS_DIR / filename
    # SAFE_FILENAME_REでスラッシュ・".."等は既に排除しているが、
    # シンボリックリンク経由の脱出等に備えて二重に確認する。
    if not _is_contained_in_packets_dir(path):
        return None
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


class InboxHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, path):
        try:
            body = path.read_bytes()
        except OSError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send_html(APP_HTML)
            return

        if self.path == "/api/packets":
            self._send_json(list_packets())
            return

        m = PACKET_PATH_RE.match(self.path)
        if m:
            packet = load_packet(m.group(1))
            if packet is None:
                self._send_json({"error": "not found"}, status=404)
            else:
                self._send_json(packet)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format_, *args):
        sys.stderr.write("[serve_inbox] " + (format_ % args) + "\n")


def main():
    if not APP_HTML.is_file():
        print(f"[ERROR] {APP_HTML} が見つかりません", file=sys.stderr)
        sys.exit(1)

    server = ThreadingHTTPServer((HOST, PORT), InboxHandler)
    print(f"受信アプリを起動しました: http://{HOST}:{PORT}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
