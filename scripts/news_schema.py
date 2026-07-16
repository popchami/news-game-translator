"""Work記事・RSS記事に共通する正規化済み記事スキーマの定義。

scripts/collect.py(RSS)とscripts/import_work_news.py(Work)は、
どちらも同じフィールド構成の記事レコードを data/raw/*.json へ書き出す。
scripts/validate.py・prompts/translate.md はこの共通スキーマを前提に
sourceType(work/rss)へ応じた検査・変換を行う。
"""
import hashlib

SOURCE_TYPES = ("work", "rss")

# Work記事にのみ実データが入りうるフィールド。RSS記事では常に
# 空配列(このモジュールのCOMMON_LIST_FIELDS)または空文字・nullにする。
COMMON_LIST_FIELDS = [
    "people",
    "organizations",
    "confirmedFacts",
    "remainingProcess",
    "officialUrls",
    "relatedUrls",
    "sourceDifferences",
    "translationCautions",
]


def make_rss_event_key(link):
    """RSS記事のeventKeyをlinkから決定的に生成する。

    同じlinkは常に同じeventKeyになる(同一記事の重複取り込み判定に使う)。
    """
    digest = hashlib.sha256(link.encode("utf-8")).hexdigest()[:16]
    return f"rss:{digest}"


def normalize_rss_article(title, link, summary, pub_date):
    """scripts/collect.pyが取得したRSS記事1件を共通スキーマへ正規化する。

    RSSで取得できない項目(Work固有の項目)は空配列・空文字にする。
    """
    article = {
        "eventKey": make_rss_event_key(link),
        "sourceType": "rss",
        "category": "",
        "title": title,
        "link": link,
        "summary": summary,
        "pubDate": pub_date,
        "status": "",
    }
    for field in COMMON_LIST_FIELDS:
        article[field] = []
    return article
