import {
  h,
  btn,
  field,
  select,
  tabs,
  api,
  perform,
  notify,
  pager,
  pageSize,
  badge,
} from "./core.js";
import { appearancePanel } from "./appearance.js";
export function mount(root, ctx) {
  let snapshot = null,
    section = "channel",
    dirty = false,
    saving = false,
    editorial = null;
  let brandingPage = 1,
    appearanceView;
  const bar = h("div"),
    content = h("section", {
      class: "panel grow",
      style: "display:flex;flex-direction:column;gap:16px",
    }),
    fields = h("div", { class: "form-grid grow" }),
    note = h("p", { class: "hint" }),
    footer = h("div", { class: "form-footer" });
  let controls = {};
  const definitions = {
    channel: [
      ["channel_name", "Nombre del canal", "text"],
      ["topic", "Tema del canal", "text"],
      ["enabled", "Búsqueda y producción automáticas", "bool"],
      [
        "max_playlist",
        "Noticias en parrilla",
        "number",
        1,
        null,
        "Capacidad de noticias terminadas.",
      ],
      ["max_pending", "Trabajos pendientes máximos", "number", 1],
      [
        "new_stories_per_update",
        "Noticias nuevas por actualización",
        "number",
        1,
        null,
        "Se producen seguidas, de una en una. El tamaño se aplica al siguiente lote.",
      ],
      [
        "scan_interval_seconds",
        "Horario de actualización",
        "schedule",
        null,
        null,
        "Horas en punto y medias según la zona horaria del canal.",
      ],
      ["max_age_hours", "Antigüedad máxima (horas)", "number", 1, 168],
    ],
    audio: [
      ["tts_language", "Idioma de locución", "language"],
      ["intro_music_enabled", "Intro musical aleatoria", "bool"],
      ["audio_intro_seconds", "Silencio antes de la voz (s)", "decimal", 0, 10],
      [
        "audio_outro_seconds",
        "Silencio después de la voz (s)",
        "decimal",
        0,
        10,
      ],
      ["voice_normalization_enabled", "Normalizar voces", "bool"],
      ["voice_loudness_lufs", "Volumen objetivo (LUFS)", "decimal", -30, -12],
      ["voice_true_peak_dbtp", "Pico máximo (dBTP)", "decimal", -9, -1],
      ["voice_loudness_range_lu", "Rango dinámico (LU)", "decimal", 1, 20],
    ],
  };
  const save = btn(
    "Guardar cambios",
    async () => {
      if (saving || !dirty) return;
      saving = true;
      save.disabled = true;
      try {
        if (section === "editorial") {
          editorial = await api("/api/dashboard/editorial", {
            revision: editorial.revision,
            text: controls.text.value,
          });
        } else {
          let changes = {};
          if (section === "advanced") changes = JSON.parse(controls.json.value);
          else
            for (const [key, , type] of definitions[section]) {
              const v = controls[key].value;
              changes[key] =
                type === "bool"
                  ? v === "true"
                  : ["number", "decimal", "schedule"].includes(type)
                    ? Number(v)
                    : v;
            }
          snapshot = await api("/api/dashboard/config", {
            revision: snapshot.revision,
            changes,
          });
        }
        dirty = false;
        notify(
          "Cambios guardados. Los trabajos iniciados conservan sus ajustes.",
        );
        ctx.refresh();
        render();
      } catch (e) {
        notify(e.message, true);
      } finally {
        saving = false;
        save.disabled = !dirty;
      }
    },
    "primary",
  );
  async function load() {
    snapshot = await perform(() => api("/api/dashboard/config"));
    if (snapshot) {
      editorial = await perform(() => api("/api/dashboard/editorial"));
      dirty = false;
      render();
    }
  }
  function render() {
    bar.replaceChildren(
      tabs(
        [
          ["channel", "Canal y automatización"],
          ["appearance", "Apariencia"],
          ["audio", "Audio"],
          ["editorial", "Estilo editorial"],
          ["advanced", "Configuración completa"],
          ["branding", "Identidad visual"],
        ],
        section,
        (s) => {
          if (dirty)
            return notify(
              "Guarda o cancela tus cambios antes de cambiar de apartado.",
              true,
            );
          section = s;
          render();
        },
      ),
    );
    if (section === "appearance") {
      appearanceView ||= appearancePanel();
      content.replaceChildren(appearanceView);
      return;
    }
    if (!snapshot) return;
    if (section === "branding") {
      content.replaceChildren(
        h("p", { class: "hint" }, "Consultando las identidades visuales…"),
      );
      renderBranding();
      return;
    }
    controls = {};
    fields.replaceChildren();
    fields.className = "form-grid grow";
    fields.style.gridTemplateRows = ["editorial", "advanced"].includes(section)
      ? "minmax(0, 1fr)"
      : "";
    if (section === "advanced") {
      const text = h("textarea", {
        value: JSON.stringify(snapshot.settings, null, 2),
        spellcheck: false,
        style: "height:100%;resize:none;font-family:ui-monospace,monospace",
      });
      controls.json = text;
      fields.append(
        field(
          "Valores completos de channel.json",
          text,
          "Se validan todos los campos antes de sustituir el fichero.",
          true,
        ),
      );
    } else if (section === "editorial") {
      const text = h("textarea", {
        value: editorial?.text || "",
        maxLength: 6000,
        style: "height:100%;resize:none",
      });
      controls.text = text;
      fields.append(
        field(
          "Cómo debe contar la noticia la IA",
          text,
          "Se aplica a las próximas redacciones. La atribución de la fuente se añade automáticamente.",
          true,
        ),
      );
    } else
      for (const [key, label, type, min, max, hint] of definitions[section]) {
        let input;
        if (type === "bool")
          input = select(
            [
              ["true", "Sí"],
              ["false", "No"],
            ],
            String(snapshot.settings[key]),
          );
        else if (type === "schedule")
          input = select(
            (
              snapshot.schedule?.options || [
                { seconds: 43200, label: "Cada 12 horas" },
                { seconds: 21600, label: "Cada 6 horas" },
                { seconds: 3600, label: "Cada hora en punto" },
                { seconds: 1800, label: "Cada media hora" },
              ]
            ).map((option) => [option.seconds, option.label]),
            snapshot.settings[key],
          );
        else if (type === "language")
          input = select(
            [
              "Spanish",
              "English",
              "French",
              "German",
              "Italian",
              "Portuguese",
              "Chinese",
              "Japanese",
              "Korean",
              "Russian",
            ].map((x) => [x, x]),
            snapshot.settings[key],
          );
        else
          input = h("input", {
            type: ["number", "decimal"].includes(type) ? "number" : "text",
            value: snapshot.settings[key],
            min,
            max,
            step: type === "decimal" ? 0.1 : 1,
            maxLength: type === "text" ? 200 : null,
          });
        controls[key] = input;
        fields.append(
          field(
            label,
            input,
            type === "schedule"
              ? `Horarios de ${snapshot.settings.schedule_timezone || "Europe/Madrid"}. Se aplica sin reiniciar.`
              : hint || "",
          ),
        );
      }
    Object.values(controls).forEach(
      (input) =>
        (input.oninput = () => {
          dirty = true;
          save.disabled = saving;
          note.textContent = "Hay cambios sin guardar.";
          note.className = "hint dirty";
        }),
    );
    note.textContent =
      "Los ajustes se guardan en su fichero y se releen sin reiniciar Docker.";
    note.className = "hint";
    save.disabled = saving || !dirty;
    footer.replaceChildren(
      note,
      h("div", { class: "actions" }, btn("Recargar / cancelar", load), save),
    );
    content.replaceChildren(fields, footer);
  }
  async function renderBranding() {
    const value = await perform(() => api("/api/branding"));
    if (!value || section !== "branding") return;
    const size = pageSize(),
      cards = h("div", { class: "cards" });
    value.brands
      .slice((brandingPage - 1) * size, brandingPage * size)
      .forEach((brand) => {
        const card = h(
          "article",
          { class: "news-card" },
          h("h3", {}, brand.name),
        );
        if (brand.logo_url)
          card.append(
            h("img", {
              src: brand.logo_url,
              alt: `Logo de ${brand.name}`,
              style:
                "height:60px;max-width:100%;object-fit:contain;background:white;border-radius:7px;padding:8px;align-self:start",
            }),
          );
        card.append(
          h("div", {
            style: `height:8px;border-radius:4px;background:${brand.accent}`,
          }),
          h("p", { class: "hint" }, brand.accent),
          h("p", { class: "summary" }, brand.domains.join(" · ")),
        );
        cards.append(card);
      });
    content.replaceChildren(
      h(
        "div",
        { class: "row" },
        badge(`${value.brands.length} identidades`),
        h(
          "p",
          { class: "hint" },
          "Los fondos y logotipos actuales se mantienen en las tarjetas de las noticias.",
        ),
      ),
      cards,
      pager(brandingPage, value.brands.length, size, (p) => {
        brandingPage = p;
        renderBranding();
      }),
    );
  }
  root.append(bar, content);
  load();
  return {
    update() {},
    show() {
      if (!dirty) load();
    },
    canLeave() {
      return !dirty;
    },
  };
}
