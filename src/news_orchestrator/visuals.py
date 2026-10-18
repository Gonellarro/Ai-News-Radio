"""Local source identities and reproducible static card plans. No network access."""

import colorsys
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from news_orchestrator import config

ROOT = config.DATA / "branding"
LOGOS = ROOT / "logos"
LAYOUTS = {"corner", "sidebar", "banner"}
FONTS = {"sans", "serif"}
RENDERER_VERSION = 2


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def catalog():
    value = json.loads((config.CONFIG / "visuals.json").read_text())
    if type(value.get("enabled")) is not bool or not isinstance(value.get("brands"), dict):
        raise ValueError("visuals.json debe contener enabled y brands.")
    for key, allowed in (("layouts", LAYOUTS), ("title_fonts", FONTS), ("themes", {"dark", "light"})):
        if (not isinstance(value.get(key), list) or not value[key]
                or any(not isinstance(v, str) or v not in allowed for v in value[key])):
            raise ValueError(f"Lista de {key} no válida en visuals.json.")
    ZoneInfo(value["timezone"])
    for key, brand in value["brands"].items():
        if (not re.fullmatch(r"[a-z0-9-]+", key) or not isinstance(brand, dict)
                or not isinstance(brand.get("name"), str) or not 1 <= len(brand["name"]) <= 100
                or not re.fullmatch(r"#[0-9a-fA-F]{6}", brand.get("accent", ""))
                or not re.fullmatch(r"[a-z0-9-]+\.png", brand.get("logo", ""))
                or not isinstance(brand.get("domains"), list)
                or any(not isinstance(d, str) or not re.fullmatch(r"[a-z0-9.-]+", d) for d in brand["domains"])):
            raise ValueError(f"Identidad visual no válida: {key}.")
    return value


def identity(article, brands):
    url = article.get("source_url") or article.get("linked_url") or article.get("url", "")
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    matches = [(len(domain), key, brand) for key, brand in brands.items() for domain in brand["domains"]
               if host == domain or host.endswith("." + domain)]
    if matches:
        _, key, brand = max(matches, key=lambda item: item[0])
        return key, brand, host
    # An original social post can come from an arbitrary federated instance.
    # Never label an external article with the logo of its discovery platform.
    original_host = (urlsplit(article.get("url", "")).hostname or "").lower().removeprefix("www.")
    source = article.get("source_name", "")
    if host and host == original_host and source.startswith("Mastodon") and "mastodon" in brands:
        return "mastodon", brands["mastodon"], host
    key = host or "news-radio"
    hue = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    rgb = colorsys.hls_to_rgb(hue, 0.57, 0.58)
    accent = "#" + "".join(f"{round(v * 255):02x}" for v in rgb)
    return key, {"name": host or source or "News Radio", "accent": accent, "logo": None}, host


def plan(article, story_id):
    settings = catalog()
    if not settings["enabled"]:
        return None
    key, brand, host = identity(article, settings["brands"])
    seed = hashlib.sha256(story_id.encode()).digest()
    logo_name = brand["logo"]
    path = LOGOS / logo_name if logo_name else None
    available = bool(path and path.is_file() and not path.is_symlink() and path.stat().st_size <= 4 * 1024 * 1024)
    logo = {"file": logo_name, "sha256": digest(path)} if available else None
    return {"renderer": RENDERER_VERSION, "source_id": key, "source_name": brand["name"], "domain": host,
            "discovery": article.get("source_name", ""), "accent": brand["accent"], "logo": logo,
            "layout": settings["layouts"][seed[0] % len(settings["layouts"])],
            "title_font": settings["title_fonts"][seed[1] % len(settings["title_fonts"])],
            "theme": settings["themes"][seed[2] % len(settings["themes"])],
            "decoration": seed[3] % 3, "timezone": settings["timezone"]}


def public_catalog():
    value = catalog()
    return {"enabled": value["enabled"], "layouts": value["layouts"], "brands": [
        {"id": key, "name": brand["name"], "accent": brand["accent"], "domains": brand["domains"],
         "logo_url": f"/branding/logos/{brand['logo']}" if (LOGOS / brand["logo"]).is_file() and not (LOGOS / brand["logo"]).is_symlink() else None}
        for key, brand in value["brands"].items()]}
