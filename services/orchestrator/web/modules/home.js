import {
  h,
  btn,
  badge,
  panel,
  date,
  title,
  duration,
  api,
  perform,
  previewJob,
  empty,
} from "./core.js";
export function mount(root, ctx) {
  let data, hls;
  const video = h("video", {
      id: "live-video",
      controls: true,
      playsInline: true,
      preload: "none",
    }),
    state = badge("Preparando"),
    caption = h("p"),
    next = h("div"),
    production = h("div"),
    stats = h("div", { class: "stats" }),
    message = h(
      "p",
      { class: "hint" },
      "El reproductor local tiene unos segundos de búfer respecto al emisor.",
    );
  const play = async () => {
    try {
      if (video.canPlayType("application/vnd.apple.mpegurl")) {
        if (!video.src) video.src = "/live/index.m3u8";
      } else if (window.Hls?.isSupported()) {
        if (!hls) {
          hls = new Hls({
            liveSyncDurationCount: 3,
            liveMaxLatencyDurationCount: 8,
            maxBufferLength: 24,
          });
          hls.loadSource("/live/index.m3u8");
          hls.attachMedia(video);
          hls.on(Hls.Events.ERROR, (_, d) => {
            if (d.fatal) {
              hls.destroy();
              hls = null;
              message.textContent =
                "No se pudo reproducir. Pulsa «Ver directo» para reconectar.";
            }
          });
        }
      }
      await video.play();
      message.textContent =
        "Escuchando la señal local. YouTube puede tener un retraso adicional.";
    } catch (e) {
      message.textContent =
        "Pulsa «Ver directo» cuando la señal esté disponible.";
    }
  };
  const pause = btn("Pausar automatización", async () => {
    await perform(async () => {
      const config = await api("/api/dashboard/config");
      return api("/api/dashboard/config", {
        revision: config.revision,
        changes: { enabled: !config.settings.enabled },
      });
    }, "Automatización actualizada. La emisión continúa.");
    ctx.refresh();
  });
  const scan = btn("Revisar noticias", () =>
    perform(
      () => api("/api/scan", {}),
      "Revisión solicitada; se respetan los límites de las fuentes.",
    ),
  );
  root.append(
    h(
      "div",
      { class: "home-main" },
      h(
        "section",
        { class: "panel live-panel" },
        h(
          "div",
          { class: "panel-title" },
          h("h2", {}, "Emisión del canal"),
          state,
        ),
        h("div", { class: "video-wrap" }, video),
        h(
          "div",
          { class: "live-caption" },
          badge("EN EL EMISOR", "good"),
          caption,
        ),
        h(
          "div",
          { class: "actions" },
          btn("▶ Ver directo", play, "primary"),
          btn("Silenciar / activar", () => (video.muted = !video.muted)),
          scan,
          pause,
        ),
        message,
      ),
      h(
        "aside",
        { class: "home-side" },
        panel("A continuación", next),
        panel("Producción automática", production),
        h(
          "div",
          { class: "actions" },
          btn("Editar parrilla →", () => ctx.navigate("playlist")),
          btn("Ver noticias →", () => ctx.navigate("news")),
        ),
      ),
    ),
    stats,
  );
  return {
    update(value) {
      data = value;
      const healthy =
        value.broadcast.updated_at &&
        Date.now() - Date.parse(value.broadcast.updated_at) < 30000;
      state.textContent = healthy
        ? "● Señal local activa"
        : "Preparando continuidad";
      state.className = `badge ${healthy ? "good" : "warn"}`;
      caption.textContent = value.broadcast.title || "Preparando noticias";
      let jobs = value.playlist;
      const current = jobs.findIndex((j) => j.id === value.broadcast.job_id);
      jobs =
        current < 0
          ? jobs
          : [...jobs.slice(current + 1), ...jobs.slice(0, current)];
      if (value.schedule?.next_id) {
        const explicit = jobs.find((j) => j.id === value.schedule.next_id);
        if (explicit)
          jobs = [explicit, ...jobs.filter((j) => j.id !== explicit.id)];
      }
      next.replaceChildren(
        ...jobs
          .slice(0, 3)
          .map((j, i) =>
            h(
              "div",
              { class: "next-item" },
              h("span", { class: "number" }, String(i + 1).padStart(2, "0")),
              h(
                "div",
                {},
                h("h3", {}, title(j)),
                h(
                  "p",
                  {},
                  `${j.article.source_name} · ${duration(j.result?.duration_seconds)}`,
                ),
              ),
            ),
          ),
      );
      if (!jobs.length)
        next.append(empty("Todavía no hay noticias terminadas."));
      const running = value.jobs.find((j) => j.status === "running");
      production.replaceChildren(
        h(
          "p",
          { class: "accent big-status" },
          !value.settings.enabled
            ? "En pausa"
            : running
              ? "Produciendo"
              : "En espera",
        ),
        h(
          "p",
          { class: "hint", style: "margin-top:10px" },
          running
            ? title(running)
            : value.rotation.can_start
              ? "Lista para trabajar con las próximas candidatas."
              : value.scanning
                ? "Recopilando noticias para el nuevo lote."
                : value.rotation.reason === "retry"
                  ? `Reintento de producción: ${date(value.rotation.next_start_at)}`
                  : value.rotation.cycle_status === "exhausted"
                    ? `Sin más candidatas elegibles. Próxima actualización: ${date(value.next_scan_at)}`
                    : `Próxima actualización: ${date(value.next_scan_at)}`,
        ),
        h(
          "p",
          { class: "hint", style: "margin-top:10px" },
          `${value.rotation.published_this_cycle} / ${value.rotation.target_per_update} noticias del lote · ${value.update_schedule?.timezone || "Europe/Madrid"}.`,
        ),
      );
      pause.textContent = value.settings.enabled
        ? "Pausar automatización"
        : "Reanudar automatización";
      scan.disabled = value.scanning;
      stats.replaceChildren(
        ...[
          [
            "En parrilla",
            `${value.playlist.length} / ${value.settings.max_playlist}`,
          ],
          [
            "Pendientes",
            (value.inventory.queued || 0) +
              (value.inventory.running || 0) +
              (value.inventory.retry || 0),
          ],
          ["Reserva disponible", value.inventory.waiting || 0],
          [
            "Última búsqueda",
            value.last_scan_at
              ? new Date(value.last_scan_at).toLocaleTimeString("es-ES", {
                  hour: "2-digit",
                  minute: "2-digit",
                })
              : "—",
          ],
        ].map(([a, b]) =>
          h(
            "div",
            { class: "stat" },
            h("span", {}, a),
            h("strong", {}, String(b)),
          ),
        ),
      );
    },
  };
}
