"""Bounded, on-demand article extraction. Social threads are never downloaded."""

from html.parser import HTMLParser
import ipaddress
import json
import re
import socket
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from news_radio.feeds import parse_date


MAX_BYTES = 3 * 1024 * 1024
MAX_TEXT = 12000
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
IGNORED = {"nav", "footer", "header", "aside", "form", "script", "style", "noscript", "svg", "button"}


class Node:
    def __init__(self, tag="root", attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []

    def text(self):
        return " ".join(child.text() if isinstance(child, Node) else child for child in self.children)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()


class ArticleHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.count = 0

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if self.count > 60000 or len(self.stack) > 180:
            raise ValueError("La página es demasiado compleja para extraerla.")
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _clean(text):
    return re.sub(r"\s+", " ", text).strip()


def _json_bodies(value):
    if isinstance(value, dict):
        if isinstance(value.get("articleBody"), str):
            yield value["articleBody"]
        for child in value.values():
            yield from _json_bodies(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_bodies(child)


def _paragraphs(node):
    if node.tag in IGNORED or node.attrs.get("aria-hidden") == "true":
        return []
    identity = (node.attrs.get("id", "") + " " + node.attrs.get("class", "")).lower()
    if re.search(r"(?:^|[\s_-])(comments?|cookie|consent|related|sidebar|advertisement)(?:$|[\s_-])", identity):
        return []
    if node.tag in {"p", "h2", "h3", "blockquote"}:
        return [_clean(node.text())]
    return [text for child in node.children if isinstance(child, Node) for text in _paragraphs(child)]


def extract_html(html):
    parser = ArticleHTML()
    parser.feed(html)
    candidates = []
    for node in parser.root.walk():
        if node.tag == "script" and node.attrs.get("type", "").split(";")[0] == "application/ld+json":
            try:
                for body in _json_bodies(json.loads(node.text())):
                    candidates.append((12, _clean(body)))
            except (ValueError, RecursionError):
                pass
        if node.tag in {"article", "main"} or node.attrs.get("role") == "main" or node.attrs.get("itemprop") == "articleBody":
            parts = list(dict.fromkeys(p for p in _paragraphs(node) if p))
            candidates.append((10 if node.tag == "article" else 8, "\n\n".join(parts)))
        if node.tag == "blockquote" and "abstract" in node.attrs.get("class", "").split():
            candidates.append((15, _clean(node.text()).removeprefix("Abstract:").strip()))
    candidates = [(rank, text) for rank, text in candidates if len(text) >= 160]
    if not candidates:
        raise ValueError("No se ha podido aislar un cuerpo de noticia fiable en esta página.")
    return max(candidates, key=lambda candidate: (candidate[0], len(candidate[1])))[1]


def publication_date(html):
    """Read publication metadata, never a discovery date or dateModified."""
    parser = ArticleHTML()
    parser.feed(html)

    def json_dates(value):
        if isinstance(value, dict):
            if isinstance(value.get("datePublished"), str):
                yield value["datePublished"]
            for child in value.values():
                yield from json_dates(child)
        elif isinstance(value, list):
            for child in value:
                yield from json_dates(child)

    structured = []
    for node in parser.root.walk():
        if node.tag == "meta":
            key = (node.attrs.get("property") or node.attrs.get("name") or node.attrs.get("itemprop") or "").lower()
            if key in {"article:published_time", "datepublished", "pubdate", "publication_date", "dc.date.issued", "citation_date"}:
                date = parse_date(node.attrs.get("content", "").replace("/", "-"))
                if date:
                    return date
        if node.tag == "time" and node.attrs.get("itemprop", "").lower() == "datepublished":
            date = parse_date(node.attrs.get("datetime", ""))
            if date:
                return date
        if node.tag == "script" and node.attrs.get("type", "").split(";")[0] == "application/ld+json":
            try:
                structured.extend(json_dates(json.loads(node.text())))
            except (ValueError, RecursionError):
                pass
    return next((date for value in structured if (date := parse_date(value))), None)


def _public_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("La fuente no tiene una URL pública válida.")
    if parsed.port not in {None, 80, 443}:
        raise ValueError("La fuente usa un puerto no admitido.")
    host = parsed.hostname.lower().rstrip(".")
    if host == "reddit.com" or host.endswith(".reddit.com") or host == "redd.it" or host.endswith(".redd.it"):
        raise ValueError("No se descargan hilos de Reddit. Usa el enlace compartido o el extracto guardado.")
    addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(entry[4][0]).is_global for entry in addresses):
        raise ValueError("La descarga de noticias requiere una dirección pública de Internet.")


class PublicRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_article(url):
    _public_url(url)
    request = Request(url, headers={"User-Agent": "NewsRadio/0.1 (+local article reader)",
                                    "Accept": "text/html, text/plain;q=0.9", "Accept-Encoding": "identity"})
    with build_opener(PublicRedirects()).open(request, timeout=18) as response:
        media_type = response.headers.get_content_type()
        if media_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
            raise ValueError("La fuente no devuelve texto o HTML; no se extraen PDF ni archivos multimedia.")
        payload = response.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise ValueError("La página supera el límite de descarga de 3 MiB.")
        html = payload.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        text = _clean(html) if media_type == "text/plain" else extract_html(html)
        note = "Texto extraído de la página; revisa que corresponde a la noticia. No implica verificación independiente."
        final = urlsplit(response.url)
        if final.hostname in {"arxiv.org", "www.arxiv.org"} and final.path.startswith("/abs/"):
            note = "Resumen científico (abstract) de arXiv, no el artículo completo. No implica revisión por pares ni verificación independiente."
        return {"text": text[:MAX_TEXT], "url": response.url,
                "kind": "extracted", "truncated": len(text) > MAX_TEXT,
                "note": note, "published_at": publication_date(html) if media_type != "text/plain" else None}
