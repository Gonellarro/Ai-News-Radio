"""Direct RSS/Atom fetching and normalization, without search engines."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


MAX_BYTES = 5 * 1024 * 1024
MAX_ITEMS = 200


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag in {"br", "p", "div", "li", "blockquote", "tr", "td", "h1", "h2", "h3"} and not self.hidden:
            self.parts.append(" ")
        if tag == "a":
            self.links.append(dict(attrs).get("href", ""))
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        if tag in {"p", "div", "li", "blockquote", "tr", "td", "h1", "h2", "h3"} and not self.hidden:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value: str) -> str:
    parser = TextOnly()
    parser.feed(value)
    return " ".join(unescape("".join(parser.parts)).split())


def normalize_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        return ""
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path or "/", urlencode(sorted(query)), ""))


def parse_date(value: str) -> str | None:
    if not value:
        return None
    try:
        date = parsedate_to_datetime(value)
    except (ValueError, TypeError, OverflowError):
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError, OverflowError):
            return None
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return date.astimezone(timezone.utc).isoformat()


def _name(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _text(element, names: set[str]) -> str:
    for child in element:
        if _name(child) in names:
            return "".join(child.itertext()).strip()
    return ""


def _author(entry) -> str:
    for child in entry:
        if _name(child) == "author":
            return _text(child, {"name"}) or (child.text or "").strip()
    return _text(entry, {"creator"})


def shared_link(markup: str, post_url: str) -> str:
    parser = TextOnly()
    parser.feed(markup)
    own_host = urlsplit(post_url).hostname
    for link in parser.links:
        candidate = normalize_url(link)
        host = urlsplit(candidate).hostname if candidate else None
        if host and host != own_host and host != "reddit.com" and not host.endswith(".reddit.com"):
            return candidate
    return ""


def parse_feed(payload: bytes, base_url: str) -> list[dict]:
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise ValueError("El feed contiene declaraciones XML no admitidas.")
    root = ET.fromstring(payload)
    if _name(root) not in {"rss", "feed", "RDF"}:
        raise ValueError("La dirección no devuelve un feed RSS o Atom.")
    articles = []
    seen = set()
    for entry in root.iter():
        kind = _name(entry)
        if kind not in {"entry", "item"}:
            continue
        summary_markup = _text(entry, {"description", "summary", "content"})
        summary = plain_text(summary_markup)
        title = plain_text(_text(entry, {"title"}))
        if not title:
            title = summary[:180] + ("…" if len(summary) > 180 else "")
        link = ""
        for child in entry:
            if _name(child) == "link":
                if kind == "entry":
                    if child.get("rel", "alternate") == "alternate":
                        link = child.get("href", "")
                        if link:
                            break
                else:
                    link = (child.text or "").strip()
                    if link:
                        break
        if not link:
            for child in entry:
                if _name(child) == "guid" and child.get("isPermaLink", "true").lower() == "true":
                    link = (child.text or "").strip()
        link = normalize_url(urljoin(base_url, link)) if link else ""
        if not title or not link or link in seen:
            continue
        seen.add(link)
        articles.append({
            "title": title,
            "url": link,
            "summary": summary[:1200],
            "published_at": parse_date(_text(entry, {"published", "pubDate", "date"})),
            "updated_at": parse_date(_text(entry, {"updated"})),
            "author": plain_text(_author(entry)),
            "linked_url": shared_link(summary_markup, link),
        })
    articles.sort(key=lambda article: article["published_at"] or "", reverse=True)
    return articles[:MAX_ITEMS]


def fetch_source(source: dict) -> list[dict]:
    request = Request(source["feed_url"], headers={
        "User-Agent": "NewsRadio/0.1 (+local RSS reader)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
    })
    with urlopen(request, timeout=18) as response:
        payload = response.read(MAX_BYTES + 1)
        final_url = response.url
    if len(payload) > MAX_BYTES:
        raise ValueError("El feed supera el límite de 5 MiB.")
    return parse_feed(payload, final_url)
