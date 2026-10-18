"""Read dated article cards from an official newsroom, without a browser."""

from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener

from news_radio.article_text import ArticleHTML, MAX_BYTES, PublicRedirects, _public_url
from news_radio.feeds import MAX_ITEMS, normalize_url, parse_date


def _date(node):
    value = node.attrs.get("datetime") or " ".join(node.text().split())
    parsed = parse_date(value)
    if parsed:
        return parsed
    # Some newsrooms print a date without a machine-readable datetime.
    for pattern in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return None


def parse_newsroom(html, base_url, article_path):
    parser = ArticleHTML()
    parser.feed(html)
    host = urlsplit(base_url).hostname
    articles = {}
    for card in parser.root.walk():
        if card.tag != "a" or not card.attrs.get("href"):
            continue
        url = normalize_url(urljoin(base_url, card.attrs["href"]))
        target = urlsplit(url)
        if target.hostname != host or not target.path.startswith(article_path) or target.path == article_path:
            continue
        nodes = list(card.walk())
        date = next((value for node in nodes if node.tag == "time" and (value := _date(node))), None)
        if not date:
            continue  # Never invent publication dates from the collection time.
        titles = [node for node in nodes if node.tag in {"h1", "h2", "h3"}]
        if not titles:
            titles = [node for node in nodes if "title" in node.attrs.get("class", "").lower()]
        title = next((text for node in titles if (text := " ".join(node.text().split()))), "")
        if not title:
            continue
        summary = " ".join(" ".join(node.text().split()) for node in nodes if node.tag == "p")
        item = {"title": title, "url": url, "summary": (summary or title)[:1200],
                "published_at": date, "updated_at": None, "author": "", "linked_url": ""}
        if url not in articles or len(item["summary"]) > len(articles[url]["summary"]):
            articles[url] = item
    if not articles:
        raise ValueError("La página no contiene tarjetas de noticias con título, enlace y fecha reconocibles; revisa si cambió su estructura.")
    return sorted(articles.values(), key=lambda item: item["published_at"], reverse=True)[:MAX_ITEMS]


def fetch_newsroom(source):
    url = source["url"]
    _public_url(url)
    request = Request(url, headers={"User-Agent": "NewsRadio/0.1 (+local newsroom reader)", "Accept": "text/html"})
    with build_opener(PublicRedirects()).open(request, timeout=18) as response:
        if response.headers.get_content_type() not in {"text/html", "application/xhtml+xml"}:
            raise ValueError("La página de noticias no devuelve HTML.")
        if urlsplit(response.url).hostname != urlsplit(url).hostname:
            raise ValueError("La página de noticias ha redirigido a otro dominio.")
        payload = response.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise ValueError("La página de noticias supera los 3 MiB.")
        html = payload.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        return parse_newsroom(html, response.url, source["article_path"])
