"""Source adapters. Social posts retain authorship and their original URLs."""

import json
import re
import unicodedata
import threading
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from news_radio.feeds import MAX_BYTES, fetch_source as fetch_rss, normalize_url, parse_date

REDDIT_LOCK = threading.Lock()

def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


def matches_keywords(article: dict, keywords: list[str]) -> bool:
    if not keywords:
        return True
    content = _fold(article["title"] + " " + article["summary"])
    return any(re.search(r"(?<!\w)" + re.escape(_fold(word)) + r"(?!\w)", content) for word in keywords)


def matches_source(article: dict, source: dict) -> bool:
    if source.get("require_link", False) and not article.get("linked_url"):
        return False
    return matches_keywords(article, source.get("keywords", []))


def _bluesky_json(method: str, params: dict) -> dict:
    url = "https://public.api.bsky.app/xrpc/" + method + "?" + urlencode(params)
    request = Request(url, headers={"User-Agent": "NewsRadio/0.1", "Accept": "application/json"})
    with urlopen(request, timeout=18) as response:
        payload = response.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("La respuesta de Bluesky supera los 5 MiB.")
    data = json.loads(payload)
    if not isinstance(data, dict) or not isinstance(data.get("feed"), list):
        raise ValueError("Bluesky no devolvió una lista de publicaciones válida.")
    return data


def _external_link(post: dict) -> str:
    embed = post.get("embed", {})
    if not isinstance(embed, dict):
        embed = {}
    media = embed.get("media", embed)
    if isinstance(media, dict):
        external = media.get("external", {})
        if isinstance(external, dict):
            link = normalize_url(external.get("uri", ""))
            if link:
                return link
    for facet in post.get("record", {}).get("facets", []):
        for feature in facet.get("features", []):
            if feature.get("$type") == "app.bsky.richtext.facet#link":
                link = normalize_url(feature.get("uri", ""))
                if link:
                    return link
    return ""


def parse_bluesky(data: dict) -> list[dict]:
    articles = []
    seen = set()
    for item in data["feed"]:
        if not isinstance(item, dict) or item.get("reason"):
            continue  # Reposts and pinned items are not new announcements.
        post = item.get("post", {})
        record = post.get("record", {})
        if not isinstance(record, dict) or record.get("reply"):
            continue  # Replies without their thread lose necessary context.
        text = record.get("text", "")
        if not isinstance(text, str) or not text.strip():
            continue
        uri = post.get("uri", "")
        author = post.get("author", {})
        parts = uri[5:].split("/") if isinstance(uri, str) and uri.startswith("at://") else []
        if (len(parts) != 3 or parts[0] != author.get("did")
                or parts[1] != "app.bsky.feed.post" or not re.fullmatch(r"[a-zA-Z0-9._~-]+", parts[2])):
            continue
        url = f"https://bsky.app/profile/{parts[0]}/post/{parts[2]}"
        if url in seen:
            continue
        seen.add(url)
        text = text.strip()
        title = " ".join(text.split())
        articles.append({
            "title": title[:180] + ("…" if len(title) > 180 else ""),
            "url": url, "summary": text[:1200],
            "published_at": parse_date(record.get("createdAt", "")),
            "updated_at": None,
            "author": author.get("displayName") or author.get("handle", ""),
            "linked_url": _external_link(post), "content_kind": "social_post",
        })
    return articles


def fetch_source(source: dict) -> list[dict]:
    connector = source.get("connector", "rss")
    if connector == "searxng":
        from news_radio.search_source import fetch_search_source
        articles = fetch_search_source(source)
    elif connector == "newsroom":
        from news_radio.newsroom import fetch_newsroom
        articles = fetch_newsroom(source)
    elif connector == "bluesky_author":
        data = _bluesky_json("app.bsky.feed.getAuthorFeed", {
            "actor": source["actor"], "limit": 50, "filter": "posts_no_replies", "includePins": "false",
        })
        articles = parse_bluesky(data)
    elif connector == "bluesky_feed":
        articles = parse_bluesky(_bluesky_json("app.bsky.feed.getFeed", {"feed": source["feed"], "limit": 50}))
    else:
        if source.get("platform") == "reddit":
            with REDDIT_LOCK:
                articles = fetch_rss(source)
        else:
            articles = fetch_rss(source)
    platform = source.get("platform", "web")
    kind = "community_post" if platform == "reddit" else "social_post" if platform != "web" else "article"
    selected = []
    for article in articles:
        if matches_source(article, source):
            article["content_kind"] = kind
            article["author"] = article.get("author") or source.get("author", "")
            if platform == "mastodon" and not article["author"]:
                post_url = urlsplit(article["url"])
                match = re.match(r"/@([^/]+)/", post_url.path)
                if match:
                    handle = match.group(1)
                    article["author"] = f"@{handle}" if "@" in handle else f"@{handle}@{post_url.hostname}"
            selected.append(article)
    return selected
