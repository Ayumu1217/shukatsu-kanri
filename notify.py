#!/usr/bin/env python3
"""Indeed RSS を監視し、条件に合う求人を LINE Messaging API で通知する。"""

import os
import sqlite3
import sys
from urllib.parse import urlencode

import feedparser
import requests

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
DB_PATH = "seen_jobs.db"

KEYWORDS = ["AI", "ビジネス", "企画", "事業開発", "インターン"]
COMPANIES = [
    "DeNA",
    "CyberAgent",
    "サイバーエージェント",
    "メルカリ",
    "Mercari",
    "SmartNews",
]

# AI / ビジネス / インターン × 東京 の3フィード
RSS_FEEDS = [
    f"https://jp.indeed.com/rss?{urlencode({'q': 'AI', 'l': '東京'})}",
    f"https://jp.indeed.com/rss?{urlencode({'q': 'ビジネス', 'l': '東京'})}",
    f"https://jp.indeed.com/rss?{urlencode({'q': 'インターン', 'l': '東京'})}",
]


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seen_jobs (job_id TEXT PRIMARY KEY, notified_at TEXT)"
    )
    conn.commit()


def is_seen(conn: sqlite3.Connection, job_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM seen_jobs WHERE job_id = ?", (job_id,)
    ).fetchone()
    return row is not None


def mark_seen(conn: sqlite3.Connection, job_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO seen_jobs (job_id, notified_at) VALUES (?, datetime('now'))",
        (job_id,),
    )
    conn.commit()


def matches(text: str) -> bool:
    """キーワードまたは対象企業のいずれかを含むか。"""
    for keyword in KEYWORDS:
        if keyword in text:
            return True
    lower = text.lower()
    for company in COMPANIES:
        if company in text or company.lower() in lower:
            return True
    return False


def send_line_push(channel_token: str, user_id: str, message: str) -> None:
    response = requests.post(
        LINE_PUSH_URL,
        headers={
            "Authorization": f"Bearer {channel_token}",
            "Content-Type": "application/json",
        },
        json={
            "to": user_id,
            "messages": [{"type": "text", "text": message}],
        },
        timeout=30,
    )
    response.raise_for_status()


def entry_text(entry: feedparser.FeedParserDict) -> str:
    parts = [entry.get("title", "")]
    if entry.get("summary"):
        parts.append(entry["summary"])
    return "\n".join(parts)


def job_id(entry: feedparser.FeedParserDict) -> str:
    return entry.get("link") or entry.get("id") or entry.get("title", "")


def process_feeds(channel_token: str, user_id: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    notified = 0

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        if feed.bozo and not feed.entries:
            print(f"警告: フィード取得に失敗した可能性があります: {feed_url}", file=sys.stderr)

        for entry in feed.entries:
            jid = job_id(entry)
            if not jid or is_seen(conn, jid):
                continue

            text = entry_text(entry)
            if not matches(text):
                continue

            title = entry.get("title", "（タイトルなし）")
            link = entry.get("link", "")
            message = f"【新着求人】\n{title}\n{link}"
            send_line_push(channel_token, user_id, message)
            mark_seen(conn, jid)
            notified += 1
            print(f"通知: {title}")

    conn.close()
    return notified


def main() -> None:
    channel_token = os.environ.get("LINE_CHANNEL_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")
    if not channel_token:
        print("エラー: 環境変数 LINE_CHANNEL_TOKEN が設定されていません", file=sys.stderr)
        sys.exit(1)
    if not user_id:
        print("エラー: 環境変数 LINE_USER_ID が設定されていません", file=sys.stderr)
        sys.exit(1)

    count = process_feeds(channel_token, user_id)
    print(f"完了: {count} 件を通知しました")


if __name__ == "__main__":
    main()
