import { h } from "./core.js";

export const PALETTE = Object.freeze([
  { id: "blue", name: "Azul", color: "#006edb" },
  { id: "teal", name: "Turquesa", color: "#167d7f" },
  { id: "green", name: "Verde", color: "#407d16" },
  { id: "amber", name: "Ámbar", color: "#946600" },
  { id: "orange", name: "Naranja", color: "#c24d16" },
  { id: "red", name: "Rojo", color: "#c52c4b" },
  { id: "magenta", name: "Magenta", color: "#a32fa5" },
  { id: "violet", name: "Violeta", color: "#7050c7" },
  { id: "sage", name: "Salvia", color: "#526e5c" },
  { id: "sand", name: "Arena", color: "#8b6740" },
]);
const STORAGE_KEY = "news-radio.appearance.v1";
const defaults = { mode: "dark", accent: "green" };
function normalize(value) {
  return {
    mode: ["light", "dark"].includes(value?.mode) ? value.mode : defaults.mode,
    accent: PALETTE.some((color) => color.id === value?.accent)
      ? value.accent
      : defaults.accent,
  };
}
function read() {
  try {
    return normalize(JSON.parse(localStorage.getItem(STORAGE_KEY)));
  } catch {
    return { ...defaults };
  }
}
let current = read();
function apply() {
  document.documentElement.dataset.theme = current.mode;
  document.documentElement.dataset.accent = current.accent;
}
export function initAppearance() {
  apply();
  window.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEY || event.key === null) {
      current = read();
      apply();
      document.dispatchEvent(new CustomEvent("appearancechange"));
    }
  });
}
export function setAppearance(changes) {
  current = normalize({ ...current, ...changes });
  apply();
  let persisted = true;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(current));
  } catch {
    persisted = false;
  }
  document.dispatchEvent(
    new CustomEvent("appearancechange", { detail: { persisted } }),
  );
  return persisted;
}

export function appearancePanel() {
  const controls = [];
  const status = h(
    "p",
    { class: "hint" },
    "Los cambios se aplican al instante y se guardan en este navegador.",
  );
  const modes = h(
    "fieldset",
    { class: "appearance-fieldset" },
    h("legend", {}, "Estilo del dashboard"),
  );
  const modeGrid = h("div", { class: "theme-options" });
  for (const [mode, name] of [
    ["light", "Claro"],
    ["dark", "Oscuro"],
  ]) {
    const input = h("input", {
      type: "radio",
      name: "dashboard-theme",
      value: mode,
      checked: current.mode === mode,
      "aria-label": name,
    });
    input.onchange = () => {
      if (input.checked) save({ mode });
    };
    controls.push([input, "mode", mode]);
    modeGrid.append(
      h(
        "label",
        { class: "theme-option" },
        input,
        h(
          "span",
          { class: `theme-sample ${mode}`, "aria-hidden": "true" },
          h("span", { class: "sample-panel" }),
        ),
        h("span", { class: "theme-label" }, name),
      ),
    );
  }
  modes.append(modeGrid);
  const colors = h(
    "fieldset",
    { class: "appearance-fieldset" },
    h("legend", {}, "Color de resaltado"),
  );
  const swatches = h("div", { class: "color-palette" });
  for (const color of PALETTE) {
    const input = h("input", {
      type: "radio",
      name: "dashboard-accent",
      value: color.id,
      checked: current.accent === color.id,
      "aria-label": color.name,
    });
    input.onchange = () => {
      if (input.checked) save({ accent: color.id });
    };
    controls.push([input, "accent", color.id]);
    swatches.append(
      h(
        "label",
        {
          class: "color-option",
          title: color.name,
          style: `--swatch:${color.color}`,
        },
        input,
        h("span", { class: "color-disc", "aria-hidden": "true" }),
      ),
    );
  }
  colors.append(swatches);
  const selected = h("p", { class: "hint" });
  function update() {
    for (const [input, key, value] of controls)
      input.checked = current[key] === value;
    selected.textContent = `Color seleccionado: ${PALETTE.find((color) => color.id === current.accent).name}`;
  }
  function save(changes) {
    const persisted = setAppearance(changes);
    status.textContent = persisted
      ? "Apariencia guardada en este navegador."
      : "Apariencia aplicada. El navegador no permite guardar esta preferencia.";
    update();
  }
  document.addEventListener("appearancechange", update);
  update();
  return h(
    "div",
    { class: "appearance-settings" },
    h(
      "div",
      {},
      h("h2", {}, "Apariencia"),
      h(
        "p",
        { class: "hint" },
        "Elige un estilo y uno de los diez colores del dashboard.",
      ),
    ),
    modes,
    colors,
    h("div", { class: "appearance-caption" }, selected, status),
  );
}
