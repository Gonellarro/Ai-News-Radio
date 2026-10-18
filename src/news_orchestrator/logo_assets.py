"""Explicit one-time asset import; never used by live production or the web API."""

import argparse
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from PIL import Image

from news_orchestrator import config, visuals


def download(key, source, force=False):
    destination = visuals.LOGOS / (key + ".png")
    metadata = visuals.LOGOS / (key + ".json")
    if destination.is_file() and not force:
        return {"id": key, "status": "existing"}
    errors = []
    for url in source["urls"]:
        try:
            if urlsplit(url).scheme != "https":
                raise ValueError("Los recursos deben usar HTTPS.")
            with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=18) as response:
                data = response.read(4 * 1024 * 1024 + 1)
                resolved = response.url
            if not data or len(data) > 4 * 1024 * 1024:
                raise ValueError("Tamaño de logo no válido.")
            original = visuals.ROOT / "originals" / (key + ".asset")
            original.write_bytes(data)
            svg = b"<svg" in data[:2000].lower()
            if svg:
                text = data.decode("utf-8")
                if (re.search(r"<!DOCTYPE|<!ENTITY|<script|<image|<foreignObject", text, re.I)
                        or re.search(r'''(?:href|src)\s*=\s*["'](?!#)''', text, re.I)
                        or re.search(r'''url\(\s*["']?(?:https?:|file:|//)''', text, re.I)):
                    raise ValueError("SVG con referencias externas o contenido no admitido.")
                root = ET.fromstring(text)
                if not root.tag.endswith("svg"):
                    raise ValueError("El recurso no es un SVG.")
                for attr in ("width", "height"):
                    dimension = re.match(r"^[0-9.]+", root.get(attr, ""))
                    if dimension and float(dimension.group()) > 4096:
                        raise ValueError("SVG demasiado grande.")
                # Some logos define only viewBox. librsvg's implicit square
                # canvas would add large margins and shrink a wordmark later.
                viewbox = root.get("viewBox", "").replace(",", " ").split()
                if len(viewbox) == 4:
                    width, height = map(float, viewbox[2:])
                    if width <= 0 or height <= 0:
                        raise ValueError("viewBox de logo no válido.")
                    ratio = min(768 / width, 768 / height)
                    root.set("width", str(max(1, round(width * ratio))))
                    root.set("height", str(max(1, round(height * ratio))))
                render_source = destination.with_suffix(".render.svg")
                render_source.write_bytes(ET.tostring(root, encoding="utf-8"))
                raster = destination.with_suffix(".raster.png")
                try:
                    result = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-threads", "1",
                                             "-filter_threads", "1", "-protocol_whitelist", "file,pipe",
                                             "-c:v", "librsvg", "-i", str(render_source), "-vf",
                                             "scale=768:768:force_original_aspect_ratio=decrease", "-frames:v", "1", str(raster)],
                                            capture_output=True, text=True, timeout=20)
                    if result.returncode:
                        raise ValueError("No se pudo rasterizar el SVG: " + result.stderr[-150:])
                    with Image.open(raster) as image:
                        logo = image.convert("RGBA")
                finally:
                    raster.unlink(missing_ok=True)
                    render_source.unlink(missing_ok=True)
            else:
                with Image.open(original) as image:
                    if image.width > 4096 or image.height > 4096:
                        raise ValueError("Imagen demasiado grande.")
                    logo = image.convert("RGBA")
                logo.thumbnail((768, 768), Image.Resampling.LANCZOS)
            bounds = logo.getchannel("A").getbbox()
            if bounds:
                logo = logo.crop(bounds)
            temporary = destination.with_suffix(".part.png")
            logo.save(temporary, format="PNG")
            temporary.replace(destination)
            config.atomic_json(metadata, {"source_url": url, "resolved_url": resolved, "reference_page": source["page"],
                               "downloaded_at": datetime.now(timezone.utc).isoformat(),
                               "original_sha256": hashlib.sha256(data).hexdigest(), "png_sha256": visuals.digest(destination),
                               "width": logo.width, "height": logo.height})
            return {"id": key, "status": "downloaded", "width": logo.width, "height": logo.height}
        except Exception as exc:
            errors.append(str(exc)[:240])
    return {"id": key, "status": "pending", "errors": errors}


def main():
    parser = argparse.ArgumentParser(description="Descargar logos configurados, una vez, fuera de la producción de noticias.")
    parser.add_argument("--force", action="store_true", help="Sustituir logos existentes usando las URLs configuradas")
    parser.add_argument("--only", nargs="+", help="Importar solo los identificadores indicados")
    args = parser.parse_args()
    visuals.LOGOS.mkdir(parents=True, exist_ok=True)
    (visuals.ROOT / "originals").mkdir(exist_ok=True)
    sources = json.loads((config.CONFIG / "logo_sources.json").read_text())
    if args.only:
        if any(key not in sources for key in args.only):
            parser.error("Hay identificadores no incluidos en logo_sources.json.")
        sources = {key: sources[key] for key in args.only}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(download, key, source, args.force) for key, source in sources.items()]
        for future in concurrent.futures.as_completed(futures):
            print(json.dumps(future.result(), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
