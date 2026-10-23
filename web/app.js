import { h, $, api, notify, date } from "./modules/core.js";
import { mount as home } from "./modules/home.js";
import { mount as youtube } from "./modules/youtube.js";
import { mount as news } from "./modules/news.js";
import { mount as playlist } from "./modules/playlist.js";
import { mount as sources } from "./modules/sources.js";
import { mount as voices } from "./modules/voices.js";
import { mount as settings } from "./modules/settings.js";
import { initAppearance } from "./modules/appearance.js";
initAppearance();
const definitions = {
  home: [home, "Inicio · Directo", "Tu emisión y lo que viene después."],
  youtube: [
    youtube,
    "YouTube",
    "Conexión, clave de emisión y diagnóstico del envío.",
  ],
  news: [
    news,
    "Noticias",
    "Consulta el contenido y previsualiza sin modificar la emisión.",
  ],
  playlist: [
    playlist,
    "Parrilla",
    "Decide qué noticias se emiten y en qué orden.",
  ],
  sources: [
    sources,
    "Búsqueda y fuentes",
    "Controla la recogida y la presencia de cada fuente.",
  ],
  voices: [
    voices,
    "Voces y producción",
    "Motores de locución, biblioteca y trabajos del canal.",
  ],
  settings: [
    settings,
    "Panel de control",
    "Configuración del canal, automatización y estilo editorial.",
  ],
};
const mounted = new Map();
let current = "",
  data = null,
  polling = false,
  timer;
const context = {
  navigate,
  refresh: () => refresh(),
  get data() {
    return data;
  },
};
function navigate(name) {
  if (!definitions[name]) name = "home";
  if (location.hash !== "#" + name) {
    location.hash = name;
    return;
  }
  const [mount, title, subtitle] = definitions[name];
  const created = !mounted.has(name);
  if (created) {
    const root = h("section", { class: "view", "aria-label": title });
    $("views").append(root);
    mounted.set(name, { root, controller: mount(root, context) });
  }
  const previous = current;
  current = name;
  for (const [id, view] of mounted) view.root.hidden = id !== name;
  document
    .querySelectorAll("[data-view]")
    .forEach((b) =>
      b.setAttribute(
        "aria-current",
        b.dataset.view === name ? "page" : "false",
      ),
    );
  $("view-title").textContent = title;
  $("view-subtitle").textContent = subtitle;
  const view = mounted.get(name).controller;
  if (data) view.update?.(data);
  if (previous && previous !== name && !created) view.show?.();
}
async function refresh() {
  if (polling) return;
  polling = true;
  clearTimeout(timer);
  try {
    data = await api("/api/status");
    $("channel-name").textContent = data.settings.channel_name;
    $("connection").textContent = "Conectado con el canal";
    $("connection-dot").style.background = "var(--success)";
    const live =
      data.broadcast.updated_at &&
      Date.now() - Date.parse(data.broadcast.updated_at) < 30000;
    $("top-local").textContent = live ? "● Local activa" : "Local · preparando";
    $("top-local").className = `pill ${live ? "good" : "warn"}`;
    const yt = data.youtube;
    $("top-youtube").textContent =
      yt.state === "sending"
        ? "● Señal a YouTube"
        : yt.enabled
          ? "YouTube · conectando"
          : "YouTube · detenida";
    $("top-youtube").className =
      `pill ${yt.state === "sending" ? "good" : yt.enabled ? "warn" : ""}`;
    $("top-playlist").textContent =
      `Parrilla · ${data.playlist.length}/${data.settings.max_playlist}`;
    const errors = [
      data.scan_error,
      data.production_error,
      data.presentation_error,
      data.cleanup_error,
      data.broadcast.error,
    ].filter(Boolean);
    $("global-status").textContent = errors.length
      ? errors[0]
      : !data.settings.enabled
        ? "Producción pausada · La emisión mantiene las noticias disponibles."
        : data.active_id
          ? "Producción en curso · La emisión continúa con normalidad."
          : `Automatización activa · ${data.rotation.published_this_cycle}/${data.rotation.target_per_update} noticias del lote · Próxima revisión: ${date(data.next_scan_at)}.`;
    $("global-status").className = errors.length ? "error" : "";
    $("updated-at").textContent =
      "Actualizado " + new Date().toLocaleTimeString("es-ES");
    mounted.get(current)?.controller.update?.(data);
  } catch (e) {
    $("connection").textContent = "Sin conexión con el panel";
    $("connection-dot").style.background = "var(--amber)";
    $("global-status").textContent =
      e.message + " La emisión es independiente de esta página.";
  } finally {
    polling = false;
    timer = setTimeout(refresh, 5000);
  }
}
window.addEventListener("hashchange", () => navigate(location.hash.slice(1)));
document
  .querySelectorAll("[data-view]")
  .forEach((b) => (b.onclick = () => navigate(b.dataset.view)));
$("top-youtube").onclick = () => navigate("youtube");
window.addEventListener("beforeunload", (event) => {
  if ([...mounted.values()].some((v) => v.controller.canLeave?.() === false)) {
    event.preventDefault();
    event.returnValue = "";
  }
});
setInterval(
  () => ($("clock").textContent = new Date().toLocaleTimeString("es-ES")),
  1000,
);
navigate(location.hash.slice(1) || "home");
refresh();
