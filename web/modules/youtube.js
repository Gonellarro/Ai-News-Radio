import {
  h,
  btn,
  panel,
  field,
  badge,
  date,
  api,
  perform,
  link,
  notify,
  confirmAction,
  tabs,
} from "./core.js";
export function mount(root, ctx) {
  let current,
    busy = false;
  const state = h("p", { class: "big-status" }),
    key = h("input", {
      type: "password",
      autocomplete: "off",
      maxLength: 200,
      placeholder: "Pega la clave nueva de YouTube Studio",
    }),
    keyHint = h("p", { class: "hint" }),
    error = h("p", { class: "error" }),
    metrics = h("div", { class: "metrics" }),
    log = h(
      "pre",
      { class: "log" },
      "Pulsa «Actualizar registro» para consultar las últimas incidencias.",
    );
  const action = async (name, payload = {}) => {
    if (busy) return;
    busy = true;
    render();
    try {
      current = await api("/api/youtube/" + name, payload);
      if (name === "key") {
        key.value = "";
        notify("Clave guardada. Pulsa «Enviar señal» para conectar.");
      } else
        notify(
          name === "stop"
            ? "Salida a YouTube detenida. La emisión local continúa."
            : "Solicitud enviada al servicio de YouTube.",
        );
    } catch (e) {
      notify(e.message, true);
    } finally {
      busy = false;
      render();
      ctx.refresh();
    }
  };
  const start = btn("▶ Enviar señal", () => action("start"), "primary"),
    stop = btn("Detener envío", () =>
      confirmAction(
        "Se detendrá solo la salida a YouTube. La emisión local y la producción seguirán funcionando.",
        () => action("stop"),
      ),
    ),
    reconnect = btn("Reconectar", () => action("reconnect")),
    save = btn("Guardar clave", () => action("key", { key: key.value.trim() })),
    change = btn("Cambiar clave", () => {
      if (current?.enabled)
        confirmAction(
          "Para cambiar la clave se detendrá el envío a YouTube. Después podrás pegar la nueva y volver a conectar.",
          async () => {
            await action("stop");
            key.focus();
          },
        );
      else key.focus();
    });
  const loadLogs = async () => {
    const value = await perform(() => api("/api/youtube/logs"));
    if (value) log.textContent = value.logs || "Sin incidencias.";
  };
  const connection = h(
    "section",
    {
      class: "panel grow",
      style: "display:flex;flex-direction:column;gap:15px",
    },
    h(
      "div",
      { class: "panel-title" },
      h("h2", {}, "Conexión con YouTube"),
      badge("RTMPS"),
    ),
    h(
      "div",
      { class: "two-columns" },
      h(
        "div",
        { class: "compact-list" },
        state,
        h("div", { class: "actions" }, start, stop, reconnect),
        field("Clave de emisión", key),
        h("div", { class: "actions" }, save, change),
        keyHint,
        error,
      ),
      h(
        "div",
        { class: "compact-list" },
        h(
          "div",
          { class: "notice" },
          "«Enviando señal» confirma el transporte desde este servidor. La publicación y la visibilidad del directo se comprueban en YouTube Studio.",
        ),
        h(
          "div",
          { class: "guide-links" },
          link("Abrir YouTube Studio ↗", "https://studio.youtube.com/"),
          link("Guía de conexión ↗", "/youtube-guide.html"),
        ),
      ),
    ),
  );
  const logs = h(
    "section",
    {
      class: "panel grow",
      style: "display:flex;flex-direction:column;gap:14px",
    },
    h(
      "div",
      { class: "panel-title" },
      h("h2", {}, "Registro del envío"),
      btn("Actualizar registro", loadLogs),
    ),
    log,
  );
  const tabbar = h("div");
  let tab = "connection";
  const changeTab = (value) => {
    tab = value;
    connection.hidden = tab !== "connection";
    logs.hidden = tab !== "logs";
    tabbar.replaceChildren(
      tabs(
        [
          ["connection", "Conexión y clave"],
          ["logs", "Diagnóstico"],
        ],
        tab,
        changeTab,
      ),
    );
    if (tab === "logs") loadLogs();
  };
  root.append(metrics, tabbar, connection, logs);
  changeTab("connection");
  function render() {
    if (!current) return;
    const states = {
      stopped: "Salida detenida",
      sending: "Enviando señal",
      starting: "Iniciando conexión…",
      stopping: "Deteniendo…",
      connecting: "Conectando…",
      waiting: "Esperando la señal local",
      retrying: "Reconectando…",
      unavailable: "Servicio no disponible",
    };
    state.textContent = states[current.state] || current.state;
    state.className = `big-status ${current.state === "sending" ? "accent" : ""}`;
    key.disabled = busy || current.enabled;
    save.disabled = busy || current.enabled;
    change.disabled = busy;
    start.disabled =
      busy || current.enabled || !current.configured || !current.worker_online;
    stop.disabled = busy || !current.enabled;
    reconnect.disabled = busy || !current.enabled;
    key.placeholder = current.configured
      ? "Clave guardada · se mantiene oculta"
      : "Pega la clave de YouTube Studio";
    keyHint.textContent = current.enabled
      ? "La clave está protegida mientras se envía. Usa «Cambiar clave» para detener el envío y sustituirla."
      : "Guarda la nueva clave y después inicia el envío. No requiere reiniciar Docker.";
    error.textContent = current.error || "";
    metrics.replaceChildren(
      ...[
        [
          "Ritmo del envío",
          current.media_rate == null
            ? "—"
            : current.media_rate.toFixed(2) + "×",
        ],
        [
          "Retraso",
          current.lag_seconds == null
            ? "—"
            : current.lag_seconds.toFixed(1) + " s",
        ],
        ["Reconexiones", current.reconnects ?? 0],
      ].map(([a, b]) =>
        h(
          "div",
          { class: "metric" },
          h("small", {}, a),
          h("strong", {}, String(b)),
        ),
      ),
    );
  }
  return {
    update(data) {
      current = data.youtube;
      render();
    },
  };
}
