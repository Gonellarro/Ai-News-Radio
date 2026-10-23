"""SearXNG adapter used by the search prototype."""

from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
import json
import os


ALLOWED_TIME_RANGES = {"", "day", "week", "month", "year"}
ALLOWED_LANGUAGES = {"all", "es", "en"}
ALLOWED_CATEGORIES = {"news", "general"}
MAX_RESULTS = 30


class SearchError(Exception):
    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


def _instance_url() -> str:
    value = os.environ.get("SEARXNG_URL", "").strip().rstrip("/")
    if not value:
        raise SearchError("SearXNG no está configurado. Añade SEARXNG_URL en .env si quieres usar la búsqueda complementaria.", 503)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SearchError("La dirección de SearXNG no es válida. Revísala en el archivo .env.", 503)
    return value


def search_news(
    query: str, *, time_range: str = "", language: str = "all", category: str = "news"
) -> dict[str, object]:
    if time_range not in ALLOWED_TIME_RANGES:
        raise SearchError("El periodo seleccionado no es válido.", 400)
    if language not in ALLOWED_LANGUAGES:
        raise SearchError("El idioma seleccionado no es válido.", 400)
    if category not in ALLOWED_CATEGORIES:
        raise SearchError("La categoría seleccionada no es válida.", 400)

    params = {
        "q": query,
        "format": "json",
        "language": language,
        "safesearch": "1",
        "categories": category,
    }
    if time_range:
        params["time_range"] = time_range
    engine_setting = "SEARXNG_GENERAL_ENGINES" if category == "general" else "SEARXNG_NEWS_ENGINES"
    engines = os.environ.get(engine_setting, "").strip()
    if engines:
        params["engines"] = engines

    data = _fetch(params)
    initial_errors = _engine_errors(data)
    fallback_used = False
    # Some engines fail parsing dated searches, and SearXNG excludes engines
    # without time-range support. Recover once, with an explicit notice to users.
    if time_range and not data["results"] and initial_errors:
        retry_params = {key: value for key, value in params.items() if key != "time_range"}
        data = _fetch(retry_params)
        fallback_used = True

    extra_engine_used = False
    fallback_engines = os.environ.get("SEARXNG_FALLBACK_ENGINES", "bing").strip()
    if category == "general" and not data["results"] and fallback_engines and fallback_engines != engines:
        # An optional final engine choice; direct feeds do not depend on it.
        fallback_params = {key: value for key, value in params.items() if key != "time_range"}
        fallback_params["engines"] = fallback_engines
        data = _fetch(fallback_params)
        fallback_used = bool(time_range)
        extra_engine_used = True

    results = _normalize_results(data["results"])
    return {
        "query": query,
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(results),
        "results": results,
        "warnings": _engine_errors(data),
        "notices": ([
            "Los motores fallaron al buscar en el periodo solicitado. Se ha repetido la búsqueda sin filtro temporal; comprueba las fechas en las fuentes originales."
        ] if fallback_used else []) + ([f"Se ha utilizado la selección de motores de respaldo: {fallback_engines}."] if extra_engine_used else []),
        "requested_time_range": time_range,
        "applied_time_range": "" if fallback_used else time_range,
        "fallback_used": fallback_used,
        "diagnostics": {"initial_engine_errors": initial_errors},
    }


def _fetch(params: dict[str, str]) -> dict[str, object]:
    url = f"{_instance_url()}/search?{urlencode(params)}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "NewsRadio/0.1"})

    try:
        with urlopen(request, timeout=25) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 403:
            raise SearchError(
                "SearXNG rechazó el formato JSON. Habilita `json` en `search.formats` de su configuración.",
                502,
            ) from exc
        raise SearchError(f"SearXNG respondió con HTTP {exc.code}.") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise SearchError(
            "No se pudo conectar con SearXNG. Comprueba la IP, el puerto y el acceso del contenedor a la red local."
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SearchError("SearXNG no devolvió una respuesta JSON válida.") from exc

    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise SearchError("SearXNG devolvió una respuesta sin una lista de resultados válida.")
    return data


def _normalize_results(raw_results: list[object]) -> list[dict[str, str]]:
    results = []
    for item in raw_results[:MAX_RESULTS]:
        if not isinstance(item, dict):
            continue
        result_url = item.get("url")
        title = item.get("title")
        if not isinstance(result_url, str) or not result_url.startswith(("http://", "https://")):
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        results.append(
            {
                "title": title.strip(),
                "url": result_url,
                "content": _as_text(item.get("content")),
                "published_at": _as_text(item.get("publishedDate")),
                "engine": _as_text(item.get("engine")),
            }
        )

    return results


def _engine_errors(data: dict[str, object]) -> list[str]:
    warnings = []
    raw_unresponsive = data.get("unresponsive_engines", [])
    if not isinstance(raw_unresponsive, list):
        return warnings
    for item in raw_unresponsive:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            engine, reason = _as_text(item[0]), _as_text(item[1])
            if engine:
                warnings.append(f"{engine}: {reason or 'sin respuesta'}")

    return warnings


def _as_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
