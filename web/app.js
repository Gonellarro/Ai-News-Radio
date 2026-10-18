(() => {
  const el = (id) => document.getElementById(id);
  const stages = { queued: "En cola", extracting: "Descargando texto", drafting: "Redactando en español", voicing: "Generando voz con Qwen", downloading: "Recuperando audio", rendering: "Preparando vídeo", packaging: "Preparando emisión", ready: "Terminado", superseded: "Sustituido por noticias más recientes" };
  let hls;
  let timer;
  let playlistSignature;
  let youtubeBusy = false;
  let youtubeStatus;
  const date = (value) => value ? new Date(value).toLocaleString("es-ES") : "—";
  const node = (tag, text, cls) => { const value = document.createElement(tag); value.textContent = text; if (cls) value.className = cls; return value; };
  function link(text, href, download = false) {
    const value = node("a", text); value.href = href;
    if (download) value.download = ""; else { value.target = "_blank"; value.rel = "noopener noreferrer"; }
    return value;
  }
  function renderYoutube(value) {
    youtubeStatus = value;
    if (!value) return;
    const states = { stopped: "Detenida", unavailable: "Servicio no disponible", starting: "Inicio solicitado",
      stopping: "Deteniendo envío…", connecting: "Conectando con YouTube…", sending: "Enviando señal a YouTube",
      waiting: "Esperando señal local", retrying: "Reconexión automática", shutdown: "Servicio detenido" };
    el("youtube-state").textContent = states[value.state] || "Consultando estado…";
    el("youtube-key-state").textContent = value.configured ? "Clave guardada. Para cambiarla, detén primero el envío." : "Todavía no hay una clave guardada. Sigue la guía para obtenerla.";
    el("youtube-start").disabled = youtubeBusy || !value.configured || !value.worker_online || value.enabled;
    el("youtube-stop").disabled = youtubeBusy || !value.enabled;
    el("youtube-save").disabled = youtubeBusy || value.enabled;
    el("youtube-key").disabled = youtubeBusy || value.enabled;
    el("youtube-key").placeholder = value.configured ? "Clave guardada · se mantiene oculta" : "Pega aquí la clave de YouTube Studio";
    el("youtube-error").textContent = value.error || "";
    const parts = [];
    if (value.last_progress_at) parts.push(`Último avance: ${date(value.last_progress_at)}`);
    if (value.reconnects) parts.push(`Reconexiones del servicio: ${value.reconnects}`);
    if (value.retry_at && value.state === "retrying") parts.push(`Próximo intento: ${date(value.retry_at)}`);
    el("youtube-metrics").textContent = parts.join(" · ");
  }
  async function youtubeLogs() {
    if (!el("youtube-log-details").open) return;
    try {
      const response = await fetch("/api/youtube/logs");
      const value = await response.json();
      if (!response.ok) throw new Error(value.error || "No se pudo leer el registro.");
      el("youtube-logs").textContent = value.logs || "Todavía no hay incidencias.";
    } catch (error) { el("youtube-logs").textContent = error.message; }
  }
  async function youtubeAction(action, payload = {}) {
    if (youtubeBusy) return;
    youtubeBusy = true;
    renderYoutube(youtubeStatus);
    el("youtube-message").textContent = "Guardando solicitud…";
    try {
      const response = await fetch(`/api/youtube/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const value = await response.json();
      if (!response.ok) throw new Error(value.error || "No se pudo completar la operación.");
      youtubeStatus = value;
      if (action === "key") el("youtube-key").value = "";
      el("youtube-message").textContent = action === "key" ? "Clave guardada. El envío sigue detenido hasta que lo inicies."
        : action === "start" ? "Envío solicitado. Comprueba la vista previa y la visibilidad del directo en YouTube Studio."
        : "Parada solicitada. La emisión local y la producción siguen funcionando.";
    } catch (error) { el("youtube-message").textContent = error.message; }
    finally { youtubeBusy = false; renderYoutube(youtubeStatus); refresh(); }
  }
  async function refresh() {
    clearTimeout(timer);
    try {
      const response = await fetch("/api/status");
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "No se pudo leer el estado.");
      const settings = data.settings;
      renderYoutube(data.youtube);
      youtubeLogs();
      const maxRetries = data.max_retries ?? 3;
      el("channel-title").textContent = settings.channel_name;
      el("automatic-state").textContent = settings.enabled ? "Activa · Sin intervención humana" : "Producción pausada en la configuración";
      el("settings").replaceChildren();
      for (const [name, value] of [["Tema", settings.topic], ["Voces", settings.voice_mode === "random" ? "Al azar por noticia" : settings.voice_name], ["Fuentes", settings.platform === "all" ? "Medios, Reddit, Mastodon, Bluesky y búsqueda SearXNG" : settings.platform === "web" ? "Medios y fuentes oficiales" : settings.platform], ["Reserva", `Hasta ${settings.max_age_hours / 24} días; actualidad por fuente`], ["Frecuencia", `${settings.scan_interval_seconds / 3600} hora(s)`], ["Última revisión", date(data.last_scan_at)], ["Próxima revisión", date(data.next_scan_at)]]) {
        el("settings").append(node("dt", name), node("dd", value));
      }
      const balance = data.source_balance;
      if (balance && el("source-balance")) {
        el("balance-summary").textContent = `${balance.description} · ${balance.total_published} noticias publicadas en el historial`;
        el("source-balance").replaceChildren();
        for (const source of balance.sources) {
          const row = node("tr", "", source.enabled === false ? "muted" : "");
          const name = node("th", `${source.name}${source.enabled === false ? " · desactivada" : ""}`);
          name.scope = "row";
          row.append(name, ...[source.published, source.on_air, source.pending, source.waiting, source.weight].map((value) => node("td", String(value))));
          el("source-balance").append(row);
        }
      }
      const healthy = data.broadcast.updated_at && Date.now() - Date.parse(data.broadcast.updated_at) < 30000;
      el("live-state").textContent = healthy ? "En directo local" : "Preparando emisión…";
      el("now-playing").textContent = `En el emisor: ${data.broadcast.title || "Iniciando la continuidad"}`;
      el("service-errors").textContent = [data.scan_error, data.production_error, data.presentation_error, data.cleanup_error, data.broadcast.error].filter(Boolean).join("\n");
      el("playlist-count").textContent = `${data.playlist.length} / ${settings.max_playlist}`;
      el("scan").disabled = data.scanning;
      el("scan").textContent = data.scanning ? "Revisando fuentes…" : "Revisar noticias ahora";
      const counts = data.inventory || {};
      if (el("production-summary")) el("production-summary").textContent = `${data.playlist.length} de ${settings.max_playlist} listas · ${counts.running || 0} en producción · ${counts.queued || 0} en cola · ${counts.retry || 0} aplazadas · ${counts.waiting || 0} en reserva${data.presentation_active_id ? " · Actualizando presentación de una pieza terminada" : ""}`;
      if (el("scan-summary")) {
        const scan = data.scan_count || {};
        el("scan-summary").textContent = data.scanning
          ? "Revisando las fuentes. La producción puede avanzar con el material ya guardado."
          : data.last_scan_at ? `${scan.found || 0} candidatas en la última revisión; ${scan.new || 0} nuevas incorporadas a la reserva.${scan.new === 0 ? " Las ya procesadas o descartadas no se generan otra vez." : ""}` : "Esperando la primera revisión.";
      }
      if (el("source-warnings")) {
        el("source-warnings").replaceChildren(...(data.source_warnings || []).map((text) => node("p", text)));
        if (!(data.source_warnings || []).length) el("source-warnings").textContent = "Sin incidencias registradas en la última revisión.";
      }
      const signature = JSON.stringify(data.playlist);
      if (signature !== playlistSignature) {
        playlistSignature = signature;
        el("playlist").replaceChildren();
        if (!data.playlist.length) el("playlist").append(node("p", "La producción está preparando la primera noticia. La emisión muestra continuidad hasta que termine.", "hint"));
        for (const job of data.playlist) {
          const card = node("article", "", "clip");
          if (job.result.presentation?.visual) {
            const preview = document.createElement("img");
            preview.className = "card-preview"; preview.loading = "lazy";
            preview.src = `/media/${job.id}/poster.png`; preview.alt = `Tarjeta: ${job.result.title}`;
            card.append(preview);
          }
          card.append(node("p", `${date(job.published_at)} · ${job.result.duration_seconds} s`, "source"));
          card.append(node("h3", job.result.title), node("p", `${job.article.source_name} · Voz: ${job.result.voice_name}`, "source"));
          if (job.result.presentation?.intro_music) card.append(node("p", `Intro: ${job.result.presentation.intro_music.name}`, "source"));
          if (job.result.presentation?.voice_normalization) card.append(node("p", "Voz normalizada", "source"));
          const links = node("div", "", "links");
          links.append(link("Ver vídeo", job.result.video_url), link("MP4 ↓", job.result.video_url, true), link("MP3 ↓", job.result.mp3_url, true), link("Fuente ↗", job.result.source_url || job.article.url));
          if (job.result.presentation?.visual) links.append(link("Ver tarjeta", `/media/${job.id}/poster.png`));
          if (job.result.source_url && job.result.source_url !== job.article.url) links.append(link("Publicación original ↗", job.article.url));
          const details = document.createElement("details"); details.append(node("summary", "Texto de la noticia"), node("p", job.result.script, "hint"));
          card.append(details, links); el("playlist").append(card);
        }
      }
      el("production").replaceChildren();
      const pending = data.jobs.filter((job) => ["running", "queued", "retry"].includes(job.status));
      if (!pending.length) el("production").append(node("p", "Sin trabajos pendientes. El canal sigue emitiendo y la búsqueda volverá a ejecutarse a su hora.", "hint"));
      pending.sort((a, b) => (b.status === "running") - (a.status === "running")
        || (a.queue_rank ?? Number.MAX_SAFE_INTEGER) - (b.queue_rank ?? Number.MAX_SAFE_INTEGER)
        || b.published_at.localeCompare(a.published_at));
      for (const job of pending) {
        const card = node("article", "", "job");
        card.append(node("h3", job.work.title || job.article.title));
        card.append(node("p", job.status === "retry" ? `Reintento ${Math.min(job.failures, maxRetries)} de ${maxRetries}: ${date(job.retry_at)}` : job.status === "queued" ? `En cola · posición ${(job.queue_rank ?? 0) + 1}` : stages[job.stage] || job.stage, "stage"));
        card.append(node("p", `${job.article.source_name} · ${date(job.published_at)}`, "hint"));
        if (job.work.voice_id) card.append(node("p", `Voz: ${job.work.voice_name}`, "hint"));
        if (job.work.intro_music) card.append(node("p", `Intro: ${job.work.intro_music.name}`, "hint"));
        if (job.error) card.append(node("p", job.error, "error"));
        el("production").append(card);
      }
      const discardedList = el("discarded");
      if (discardedList) {
        discardedList.replaceChildren();
        const discarded = data.jobs.filter((job) => job.status === "discarded");
        if (!discarded.length) discardedList.append(node("p", "No hay noticias descartadas entre los trabajos recientes.", "hint"));
        for (const job of discarded) {
          const card = node("article", "", "job");
          card.append(node("h3", job.work.title || job.article.title));
          card.append(node("p", `Descartada · Límite de ${maxRetries} reintentos agotado · ${job.failures} fallos registrados`, "stage"));
          card.append(node("p", `${job.article.source_name} · ${date(job.updated_at)} · Fase: ${stages[job.stage] || job.stage}`, "hint"));
          if (job.error) card.append(node("p", job.error, "error"));
          discardedList.append(card);
        }
      }
      el("events").replaceChildren(...data.events.map((event) => node("div", `${date(event.created_at)} · ${event.message}`, "event")));
    } catch (error) { el("service-errors").textContent = error.message; }
    timer = setTimeout(refresh, 5000);
  }
  el("play-live").addEventListener("click", async () => {
    const video = el("live-video");
    el("player-message").textContent = "Conectando con la emisión local…";
    try {
      if (video.canPlayType("application/vnd.apple.mpegurl")) {
        if (!video.src) video.src = "/live/index.m3u8";
      } else if (window.Hls && Hls.isSupported()) {
        if (!hls) {
          hls = new Hls({ liveSyncDurationCount: 3, liveMaxLatencyDurationCount: 6, maxBufferLength: 24 });
          hls.loadSource("/live/index.m3u8"); hls.attachMedia(video);
          hls.on(Hls.Events.MANIFEST_PARSED, () => video.play().catch(() => {}));
          hls.on(Hls.Events.ERROR, (_, data) => {
            if (!data.fatal) return;
            if (data.type === Hls.ErrorTypes.NETWORK_ERROR) { el("player-message").textContent = "Esperando señal local; reconectando…"; setTimeout(() => hls.startLoad(), 3000); }
            else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) hls.recoverMediaError();
            else el("player-message").textContent = "No se pudo reproducir la señal. Recarga la página o abre el flujo HLS en VLC.";
          });
        }
      } else throw new Error("Este navegador no admite HLS. Abre el enlace del flujo en VLC.");
      await video.play();
      el("player-message").textContent = "Reproduciendo la parrilla local. La señal continúa aunque cierres esta página.";
    } catch (error) { el("player-message").textContent = error.message || "Pulsa reproducir cuando aparezca la señal."; }
  });
  el("scan").addEventListener("click", async () => {
    el("scan").disabled = true;
    try {
      const response = await fetch("/api/scan", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      if (!response.ok) throw new Error("No se pudo programar la revisión.");
      el("scan-message").textContent = "Revisión solicitada. Las fuentes respetarán sus intervalos y límites de acceso.";
      refresh();
    } catch (error) { el("scan-message").textContent = error.message; el("scan").disabled = false; }
  });
  el("youtube-key-form").addEventListener("submit", (event) => {
    event.preventDefault();
    youtubeAction("key", { key: el("youtube-key").value.trim() });
  });
  el("youtube-start").addEventListener("click", () => youtubeAction("start"));
  el("youtube-stop").addEventListener("click", () => youtubeAction("stop"));
  el("youtube-log-details").addEventListener("toggle", youtubeLogs);
  refresh();
})();
