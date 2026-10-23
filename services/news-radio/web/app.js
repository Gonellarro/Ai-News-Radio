const form = document.querySelector("#search-form");
const queryInput = document.querySelector("#query");
const button = document.querySelector("#search-button");
const resultsEl = document.querySelector("#results");
const statusEl = document.querySelector("#status");
const titleEl = document.querySelector("#results-title");
const countEl = document.querySelector("#result-count");
const resultsSection = document.querySelector(".results-section");
const providerEl = document.querySelector("#provider");
const sourceSelect = document.querySelector("#source-id");
const refreshButton = document.querySelector("#refresh-button");
const sourcesStatus = document.querySelector("#sources-status");
const sourcesList = document.querySelector("#sources-list");
const platformEl = document.querySelector("#platform");
let catalogSources = [];
let searching = false;
let refreshing = false;
let sourceTimer;

function updateMode() {
  const direct = providerEl.value === "direct";
  queryInput.required = !direct;
  queryInput.placeholder = direct
    ? "Deja vacío para ver las últimas noticias de todas las fuentes"
    : "Ej.: Qwen, nuevos modelos de IA, regulación europea…";
  document.querySelector("#query-label").textContent = direct ? "Filtrar noticias (opcional)" : "Tema o palabras clave";
  document.querySelector("#source-filter").hidden = !direct;
  document.querySelector("#platform-filter").hidden = !direct;
  document.querySelector("#category-filter").hidden = direct;
  document.querySelector("#language-label").textContent = direct ? "Idioma de la fuente" : "Idioma de búsqueda";
  document.querySelector("#filter-hint").textContent = direct
    ? (platformEl.value === "web"
      ? "Filtra titulares y extractos guardados. Los textos se muestran en su idioma original."
      : "Las redes y comunidades aportan publicaciones por contrastar. Revisa el autor y los enlaces compartidos; no son noticias verificadas automáticamente.")
    : "Búsqueda complementaria en la web. Puede depender de la disponibilidad de los motores de SearXNG.";
  if (!searching) button.textContent = direct ? (platformEl.value === "web" ? "Ver noticias" : "Ver publicaciones") : "Buscar en SearXNG";
}

providerEl.addEventListener("change", updateMode);

function updateSourceOptions() {
  const selected = sourceSelect.value;
  const platform = platformEl.value;
  sourceSelect.replaceChildren(new Option("Todas las fuentes activas", ""));
  for (const source of catalogSources) {
    const origin = source.platform || "web";
    const matches = platform === "all" || platform === origin || (platform === "social" && origin !== "web");
    if (source.enabled && (source.available ?? !!source.feed_url) && matches) {
      sourceSelect.append(new Option(source.name, source.id));
    }
  }
  if ([...sourceSelect.options].some((option) => option.value === selected)) sourceSelect.value = selected;
}

platformEl.addEventListener("change", () => {
  updateSourceOptions();
  updateMode();
  if (!searching && providerEl.value === "direct") form.requestSubmit();
});

function textElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = text;
  return element;
}

function showStatus(message, kind = "info") {
  statusEl.hidden = false;
  statusEl.className = `status ${kind}`;
  statusEl.textContent = message;
}

function formatDate(value) {
  if (!value) return "Fecha sin verificar";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function renderResults(items) {
  resultsEl.replaceChildren();
  for (const item of items) {
    let parsedUrl;
    try {
      parsedUrl = new URL(item.url);
      if (!["http:", "https:"].includes(parsedUrl.protocol)) continue;
    } catch {
      continue;
    }
    const card = document.createElement("article");
    card.className = "result-card";
    const meta = document.createElement("div");
    meta.className = "result-meta";
    meta.append(textElement("span", "engine", item.source_name || `SearXNG · ${item.engine || "Web"}`));
    meta.append(textElement("time", "date", formatDate(item.published_at)));
    const link = document.createElement("a");
    link.className = "result-title";
    link.href = parsedUrl.href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = item.title;
    card.append(meta, link);
    if (item.content_kind === "social_post" || item.content_kind === "community_post") {
      const network = { reddit: "Reddit", mastodon: "Mastodon", bluesky: "Bluesky" }[item.platform] || "Red social";
      card.append(textElement("p", "social-label", `${network} · Publicación por contrastar`));
    }
    if (item.author) card.append(textElement("p", "post-author", item.author));
    if (item.content && item.content !== item.title) card.append(textElement("p", "result-summary", item.content));
    if (item.linked_url && item.content_kind !== "article") {
      try {
        const shared = new URL(item.linked_url);
        if (["https:", "http:"].includes(shared.protocol)) {
          const sharedLink = textElement("a", "shared-link", "Enlace compartido ↗");
          sharedLink.href = shared.href;
          sharedLink.target = "_blank";
          sharedLink.rel = "noopener noreferrer";
          card.append(sharedLink);
        }
      } catch { /* Ignore malformed links in upstream metadata. */ }
    }
    card.append(textElement("p", "source", parsedUrl.hostname.replace(/^www\./, "")));
    if (item.id && item.provider === "direct") {
      const writeButton = textElement("button", "write-button", "Redactar en español");
      writeButton.type = "button";
      writeButton.addEventListener("click", () => document.dispatchEvent(new CustomEvent("editorial:open", { detail: { articleId: item.id } })));
      card.append(writeButton);
    }
    resultsEl.append(card);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (searching) return;
  const formData = new FormData(form);
  const query = String(formData.get("q") || "").trim();
  const direct = providerEl.value === "direct";
  if (!direct && !query) return;
  const params = new URLSearchParams({
    q: query,
    time_range: String(formData.get("time_range") || ""),
    language: String(formData.get("language") || "all"),
    category: String(formData.get("category") || "news"),
    source_id: String(formData.get("source_id") || ""),
    platform: String(formData.get("platform") || "web"),
  });
  searching = true;
  button.disabled = true;
  button.textContent = "Buscando…";
  resultsSection.setAttribute("aria-busy", "true");
  resultsEl.replaceChildren();
  countEl.textContent = "";
  titleEl.textContent = query ? `Buscando “${query}”` : "Últimas noticias de las fuentes";
  showStatus(direct ? "Consultando las noticias guardadas…" : "Consultando SearXNG…");
  try {
    const endpoint = direct ? "/api/news" : "/api/search";
    const response = await fetch(`${endpoint}?${params.toString()}`, { headers: { Accept: "application/json" } });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Error HTTP ${response.status}`);
    titleEl.textContent = direct
      ? (query ? `Publicaciones sobre “${query}”` : (platformEl.value === "web" ? "Últimas noticias de las fuentes" : "Últimas publicaciones de las fuentes"))
      : (data.fallback_used ? `Resultados sin filtro temporal para “${data.query}”` : `Resultados para “${data.query}”`);
    countEl.textContent = data.total_count > data.count
      ? `${data.count} de ${data.total_count} noticias`
      : `${data.count} ${data.count === 1 ? "resultado" : "resultados"}`;
    statusEl.hidden = true;
    renderResults(data.results);
    const messages = [...(data.notices || [])];
    if (direct && data.refreshing) messages.push("Actualizando las fuentes. Esta lista se recargará al terminar.");
    if (direct && data.undated_count && params.get("time_range")) {
      messages.push(`${data.undated_count} noticias sin fecha de publicación se han excluido del periodo solicitado.`);
    }
    if (data.warnings?.length) {
      messages.push(`${data.count ? "Resultados parciales" : "No llegaron resultados"}. Motores con errores: ${data.warnings.join(" · ")}.`);
    }
    if (messages.length) showStatus(messages.join(" "), "warning");
    else if (!data.count) showStatus(direct
      ? "No hay noticias guardadas que coincidan con estos filtros. Amplía el periodo, revisa el idioma o actualiza las fuentes."
      : "No hay resultados. Prueba con términos más amplios o cambia el periodo.");
  } catch (error) {
    titleEl.textContent = "No se pudo completar la búsqueda";
    showStatus(error.message || "Error inesperado al buscar.", "error");
  } finally {
    button.disabled = false;
    searching = false;
    updateMode();
    resultsSection.setAttribute("aria-busy", "false");
  }
});

async function loadSources() {
  clearTimeout(sourceTimer);
  try {
    const response = await fetch("/api/sources");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "No se pudo leer el catálogo de fuentes.");
    const wasRefreshing = refreshing;
    refreshing = data.refreshing;
    refreshButton.disabled = refreshing;
    refreshButton.textContent = refreshing ? "Actualizando…" : "Actualizar fuentes";
    const ok = data.sources.filter((source) => source.state === "ok").length;
    const pending = data.sources.filter((source) => source.state === "missing_feed").length;
    const errors = data.sources.filter((source) => source.state === "error").length;
    const limited = data.sources.filter((source) => source.state === "rate_limited").length;
    sourcesStatus.textContent = data.error || (refreshing
      ? "Recopilación en curso. Las noticias guardadas siguen disponibles."
      : `${ok} fuentes consultadas · ${pending} pendientes · ${limited} limitadas · ${errors} con errores · cada ${Math.round(data.refresh_seconds / 60)} min`);
    sourcesList.replaceChildren();
    catalogSources = data.sources;
    updateSourceOptions();
    const labels = { ok: "Conectada", error: "Error de lectura", rate_limited: "Pausa por límite de acceso", missing_feed: "Pendiente de vía directa", pending: "Primera lectura pendiente", disabled: "Desactivada" };
    for (const source of data.sources) {
      const card = textElement("article", "source-card", "");
      const link = textElement("a", "", source.name);
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      card.append(link, textElement("p", `state-${source.state}`, labels[source.state] || source.state));
      if (source.last_success_at) card.append(textElement("p", "", `Última lectura: ${formatDate(source.last_success_at)} · ${source.article_count} entradas`));
      if (source.error && source.state === "error") card.append(textElement("p", "", source.error));
      if (source.state === "rate_limited") card.append(textElement("p", "", `Se reintentará a partir de ${formatDate(source.next_retry_at)}. Se respeta el límite del servidor.`));
      if (source.platform === "reddit") {
        card.append(textElement("p", "", `Revisión mínima por flujo: ${Math.round(source.refresh_seconds / 3600)} h. Se consulta un solo flujo de Reddit por turno.`));
        if (source.limit_scope === "reddit") card.append(textElement("p", "", "La pausa se aplica a Reddit en conjunto."));
      }
      if (source.available && source.next_check_at) card.append(textElement("p", "", `Próxima revisión: no antes de ${formatDate(source.next_check_at)}`));
      if (source.notes) card.append(textElement("p", "", source.notes));
      sourcesList.append(card);
    }
    if (wasRefreshing && !refreshing && providerEl.value === "direct" && !searching) form.requestSubmit();
  } catch (error) {
    sourcesStatus.textContent = error.message;
    refreshButton.disabled = false;
  }
  sourceTimer = setTimeout(loadSources, refreshing ? 2000 : 30000);
}

refreshButton.addEventListener("click", async () => {
  refreshButton.disabled = true;
  try {
    const response = await fetch("/api/refresh", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "No se pudo actualizar.");
    refreshing = true;
    await loadSources();
  } catch (error) {
    refreshButton.disabled = false;
    sourcesStatus.textContent = error.message;
  }
});

const initialQuery = new URLSearchParams(window.location.search).get("q");
if (initialQuery) {
  queryInput.value = initialQuery;
}
updateMode();
loadSources().then(() => form.requestSubmit());
