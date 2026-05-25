#!/usr/bin/env python3
"""Indeed RSS / Wantedly を監視し、条件に合う求人を LINE Messaging API で通知する。"""

import os
import sqlite3
import sys
from urllib.parse import urlencode

import anthropic
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

_claude_client: anthropic.Anthropic | None = None

# システムプロンプト（毎回同じなのでプロンプトキャッシュを活用）
_AI_JUDGE_SYSTEM = """\
あなたは就職活動のアドバイザーです。
以下のユーザープロフィールに基づき、求人がユーザーに適しているか評価してください。

【ユーザープロフィール】
- 中央大学 経済学部 2年生
- AI・ビジネス職志望のインターン生
- 文系バックグラウンド（プログラミングは基礎〜中級程度）
- AI技術・ビジネス戦略・事業開発・企画・マーケティングに興味あり

【評価基準】
1. 大学生（特に文系2年生）がインターンとして参加できるか
2. AI・ビジネス・企画・事業開発・マーケティングに関連するか
3. 経済学部生でも対応できる職種・業務内容か

【返答形式】
1行目に「適切」または「不適切」とだけ記載し、2行目以降に判断理由を1〜2文で記載してください。\
"""

WANTEDLY_API_URL = "https://www.wantedly.com/api/v1/projects"
WANTEDLY_SEARCH_KEYWORDS = ["AI", "ビジネス", "インターン"]
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


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


def _get_claude_client() -> anthropic.Anthropic:
    global _claude_client
    if _claude_client is None:
        _claude_client = anthropic.Anthropic()
    return _claude_client


def is_suitable_for_user(title: str, description: str) -> bool:
    """Claude APIで求人がユーザー（中央大学経済学部2年・AI/ビジネス志望インターン）に適切か判断する。"""
    try:
        client = _get_claude_client()
        content = f"求人タイトル: {title}\n\n求人説明:\n{description[:3000]}"
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=1024,
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},
            system=[{
                "type": "text",
                "text": _AI_JUDGE_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": content}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        result = text.strip().startswith("適切")
        print(f"AI判定: {'✓' if result else '✗'} {title[:40]}")
        return result
    except anthropic.APIError as exc:
        print(f"警告: Claude API エラー ({exc})", file=sys.stderr)
        return True  # API障害時はキーワードマッチ済みとして通知する


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
            summary = entry.get("summary", "")
            if not is_suitable_for_user(title, summary):
                continue

            link = entry.get("link", "")
            message = f"【新着求人】\n{title}\n{link}"
            send_line_push(channel_token, user_id, message)
            mark_seen(conn, jid)
            notified += 1
            print(f"通知: {title}")

    conn.close()
    return notified


def project_text(project: dict) -> str:
    parts = [
        project.get("title", ""),
        project.get("looking_for", ""),
        project.get("description", ""),
    ]
    company = project.get("company") or {}
    parts.append(company.get("name", ""))
    return "\n".join(p for p in parts if p)


def fetch_wantedly_projects(keyword: str, page: int = 1) -> list[dict]:
    response = requests.get(
        WANTEDLY_API_URL,
        params={"keyword": keyword, "page": page},
        headers=REQUEST_HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("data", [])


def check_wantedly(channel_token: str, user_id: str) -> int:
    """Wantedly の求人をチェックし、マッチするものを毎回 LINE 通知する（既読管理なし）。"""
    notified = 0
    notified_ids: set[str] = set()

    for keyword in WANTEDLY_SEARCH_KEYWORDS:
        try:
            projects = fetch_wantedly_projects(keyword)
        except requests.RequestException as exc:
            print(f"警告: Wantedly 取得失敗 ({keyword}): {exc}", file=sys.stderr)
            continue

        for project in projects:
            pid = str(project.get("id", ""))
            if not pid or pid in notified_ids:
                continue

            if not matches(project_text(project)):
                continue

            title = project.get("title", "（タイトルなし）")
            description = "\n".join(filter(None, [
                project.get("looking_for", ""),
                project.get("description", ""),
            ]))
            if not is_suitable_for_user(title, description):
                continue

            notified_ids.add(pid)
            company = (project.get("company") or {}).get("name", "")
            link = f"https://www.wantedly.com/projects/{pid}"
            message = f"【Wantedly】\n{company}\n{title}\n{link}"
            send_line_push(channel_token, user_id, message)
            notified += 1
            print(f"Wantedly通知: {title}")

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
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("エラー: 環境変数 ANTHROPIC_API_KEY が設定されていません", file=sys.stderr)
        sys.exit(1)

    count_indeed = process_feeds(channel_token, user_id)
    count_wantedly = check_wantedly(channel_token, user_id)
    print(
        f"完了: Indeed {count_indeed} 件、Wantedly {count_wantedly} 件を通知しました"
    )


if __name__ == "__main__":
    main()
