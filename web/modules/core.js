export const $ = (id) => document.getElementById(id);
export const date = (s) => (s ? new Date(s).toLocaleString("es-ES") : "—");
export const duration = (seconds) => {
  if (seconds == null) return "—";
  const rounded = Math.max(0, Math.round(seconds));
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, "0")}`;
};
export const title = (job) =>
  job.result?.title || job.work?.title || job.article?.title || "Sin título";
export const stage = (job) =>
  ({
    waiting: "En reserva",
    queued: "En cola",
    retry: "Reintento pendiente",
    running: "En producción",
    ready: job.active ? "En parrilla" : "Terminada",
    discarded: "Descartada",
    superseded: "Retirada",
  })[job.status] || job.status;
export function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key in node && !key.startsWith("aria-")) node[key] = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  node.append(...children.filter((c) => c != null));
  return node;
}
export const btn = (text, action, cls = "", attrs = {}) =>
  h("button", { type: "button", class: cls, onclick: action, ...attrs }, text);
export function link(text, url) {
  let safe;
  try {
    safe = new URL(url, location.origin);
  } catch {
    return h("span", {}, text);
  }
  if (!["http:", "https:"].includes(safe.protocol)) return h("span", {}, text);
  return h(
    "a",
    { href: safe.href, target: "_blank", rel: "noopener noreferrer" },
    text,
  );
}
export function notify(message, error = false) {
  const n = $("toast");
  n.textContent = message;
  n.className = error ? "error-toast" : "";
  n.hidden = false;
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => (n.hidden = true), error ? 11000 : 5500);
}
export async function api(path, payload) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 70000);
  try {
    const response = await fetch(path, {
      signal: controller.signal,
      cache: "no-store",
      ...(payload === undefined
        ? {}
        : {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Error ${response.status}`);
    return data;
  } catch (e) {
    if (e.name === "AbortError")
      throw new Error(
        "El servicio no ha respondido a tiempo. Actualiza su estado antes de repetir la operación.",
      );
    throw e;
  } finally {
    clearTimeout(timer);
  }
}
export async function perform(action, message) {
  try {
    const value = await action();
    if (message) notify(message);
    return value;
  } catch (e) {
    notify(e.message, true);
    return null;
  }
}
export const badge = (text, cls = "") =>
  h("span", { class: `badge ${cls}` }, text);
export const empty = (text) =>
  h("div", { class: "empty" }, h("span", {}, "◇"), h("p", {}, text));
export const panel = (heading, ...children) =>
  h(
    "section",
    { class: "panel" },
    h("div", { class: "panel-title" }, h("h2", {}, heading)),
    ...children,
  );
export function tabs(items, current, change) {
  return h(
    "div",
    { class: "tabs", role: "tablist" },
    ...items.map(([id, label]) =>
      btn(label, () => change(id), id === current ? "active" : "", {
        "aria-selected": id === current,
        role: "tab",
      }),
    ),
  );
}
export function field(label, control, hint = "", full = false) {
  return h(
    "label",
    { class: `field${full ? " full" : ""}` },
    h("span", {}, label),
    control,
    hint ? h("small", {}, hint) : null,
  );
}
export function select(items, value) {
  return h(
    "select",
    {},
    ...items.map(([id, label]) =>
      h("option", { value: String(id), selected: String(id) === String(value) }, label),
    ),
  );
}
export function pager(page, total, size, change) {
  const count = Math.max(1, Math.ceil(total / size));
  return h(
    "div",
    { class: "pager" },
    h("span", {}, `${total} elementos · Página ${page} de ${count}`),
    h(
      "div",
      { class: "actions" },
      btn("← Anterior", () => change(page - 1), "", { disabled: page <= 1 }),
      btn("Siguiente →", () => change(page + 1), "", {
        disabled: page >= count,
      }),
    ),
  );
}
export function pageSize(kind = "cards") {
  if (kind === "rows")
    return Math.max(3, Math.min(9, Math.floor((innerHeight - 370) / 67)));
  return innerWidth <= 760 ? 2 : innerWidth <= 1100 ? 4 : 6;
}
export function modal(heading, content, onClose = () => {}) {
  const d = $("modal");
  if (modal.cleanup) modal.cleanup();
  const close = () => {
    if (modal.cleanup) modal.cleanup();
    modal.cleanup = null;
    d.close();
  };
  const body = h("div", { class: "modal-body" }, content);
  d.replaceChildren(
    h(
      "div",
      { class: "modal-header" },
      h("h2", { id: "modal-title" }, heading),
      btn("Cerrar ×", close),
    ),
    body,
  );
  modal.cleanup = () => {
    body.querySelectorAll("video,audio").forEach((m) => m.pause());
    onClose();
  };
  d.onclose = () => {
    if (!d.open) {
      modal.cleanup?.();
      modal.cleanup = null;
    }
  };
  if (!d.open) d.showModal();
  return { dialog: d, close };
}
export function confirmAction(message, action) {
  const content = h(
    "div",
    { class: "compact-list" },
    h("p", { class: "hint" }, message),
  );
  const m = modal("Confirmar acción", content);
  content.append(
    h(
      "div",
      { class: "actions" },
      btn("Cancelar", m.close),
      btn(
        "Confirmar",
        async () => {
          m.close();
          await perform(action);
        },
        "danger",
      ),
    ),
  );
}
export function silenceOthers(except) {
  document.querySelectorAll("video,audio").forEach((m) => {
    if (m !== except) m.pause();
  });
}
export function previewJob(job, tab = "text") {
  const result = job.result || {},
    work = job.work || {};
  const box = h("div", { class: "compact-list" });
  let active = tab;
  const render = () => {
    box.querySelectorAll("audio,video").forEach((m) => m.pause());
    box.replaceChildren(
      tabs(
        [
          ["text", "Texto editorial"],
          ["original", "Texto disponible"],
          ["media", "Audio y vídeo"],
          ["history", "Producción"],
        ],
        active,
        (t) => {
          active = t;
          render();
        },
      ),
      h(
        "p",
        { class: "hint" },
        `${job.article.source_name} · ${date(job.published_at)}`,
      ),
    );
    if (active === "text")
      box.append(
        h(
          "p",
          { class: "story-text" },
          result.script ||
            work.script ||
            "El texto editorial todavía no está generado.",
        ),
      );
    if (active === "original")
      box.append(
        h(
          "p",
          { class: "story-text" },
          job.article.content ||
            job.article.summary ||
            job.article.description ||
            "Consulta el texto completo en la fuente.",
        ),
      );
    if (active === "media") {
      if (result.video_url && !job.artifacts_deleted_at) {
        const v = h("video", {
          controls: true,
          playsInline: true,
          preload: "metadata",
          src: result.video_url,
        });
        v.addEventListener("play", () => silenceOthers(v));
        box.append(v);
      }
      if (result.mp3_url && !job.artifacts_deleted_at) {
        const a = h("audio", {
          controls: true,
          preload: "none",
          src: result.mp3_url,
        });
        a.addEventListener("play", () => silenceOthers(a));
        box.append(a);
      }
      if (!result.video_url || job.artifacts_deleted_at)
        box.append(
          empty(
            "Los archivos todavía no existen o ya se retiraron para liberar disco.",
          ),
        );
    }
    if (active === "history")
      box.append(
        h(
          "p",
          { class: "story-text" },
          `Estado: ${stage(job)}\nFase: ${job.stage}\nMotor: ${result.tts_engine || work.tts_engine || "Por asignar"}\nVoz: ${result.voice_name || work.voice_name || "Por asignar"}\nDuración: ${duration(result.duration_seconds)}\nFallos: ${job.failures}\nActualizada: ${date(job.updated_at)}${job.error ? "\n\n" + job.error : ""}`,
        ),
      );
    box.append(
      h(
        "div",
        { class: "guide-links" },
        link("Abrir fuente original ↗", result.source_url || job.article.url),
        result.video_url && !job.artifacts_deleted_at
          ? link("Abrir MP4 ↗", result.video_url)
          : null,
      ),
    );
  };
  render();
  modal(title(job), box);
}
