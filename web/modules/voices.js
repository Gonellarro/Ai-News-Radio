import {
  h,
  btn,
  field,
  select,
  tabs,
  api,
  perform,
  notify,
  modal,
  confirmAction,
  pager,
  pageSize,
  empty,
  badge,
  title,
  stage,
  previewJob,
  silenceOthers,
  duration,
} from "./core.js";
export function mount(root, ctx) {
  let tab = "voices",
    voices = [],
    info = null,
    data = null,
    page = 1,
    dirty = false;
  const bar = h("div"),
    enginePanel = h("section", { class: "panel" }),
    body = h("section", { class: "panel table-panel" });
  let qwenBase = "";
  async function load() {
    const result = await perform(() => api("/api/narration"));
    if (!result) return;
    info = result;
    try {
      const url = new URL(info.qwen_web_url);
      if (["localhost", "127.0.0.1", "[::1]"].includes(url.hostname))
        url.hostname = location.hostname;
      qwenBase = url.origin;
    } catch {}
    const library = await perform(() => api("/api/voices"));
    voices = library?.voices || [];
    render();
  }
  function render() {
    bar.replaceChildren(
      tabs(
        [
          ["voices", "Voces del canal"],
          ["production", "Producción y trabajos"],
        ],
        tab,
        (t) => {
          tab = t;
          page = 1;
          render();
        },
      ),
    );
    if (!info) {
      body.replaceChildren(empty("Consultando los servicios de locución…"));
      return;
    }
    if (!dirty) {
      const engine = select(
          [
            ["piper", "Piper · ligero"],
            ["qwen", "Qwen · voces clonadas"],
          ],
          info.tts_engine,
        ),
        piper = select(
          info.piper_voices.map((v) => [
            v.id,
            `${v.label}${v.ready ? "" : " · no descargada"}`,
          ]),
          info.piper_voice,
        ),
        mode = select(
          [
            ["random", "Al azar entre voces activas"],
            ["fixed", "Voz fija"],
          ],
          info.voice_mode,
        ),
        voice = select(
          [
            ["", "Selecciona una voz"],
            ...voices
              .filter((v) => v.enabled !== false)
              .map((v) => [v.id, v.name]),
          ],
          info.qwen_voice_id ||
            voices.find(
              (v) => v.name.toLowerCase() === info.voice_name?.toLowerCase(),
            )?.id ||
            "",
        );
      const piperField = field("Voz Piper", piper),
        modeField = field("Selección Qwen", mode),
        voiceField = field("Voz fija", voice);
      const toggle = () => {
        piperField.hidden = engine.value !== "piper";
        modeField.hidden = engine.value === "piper";
        voiceField.hidden = engine.value === "piper" || mode.value !== "fixed";
      };
      engine.onchange = mode.onchange = () => {
        dirty = true;
        toggle();
      };
      voice.onchange = piper.onchange = () => (dirty = true);
      toggle();
      enginePanel.replaceChildren(
        h(
          "div",
          { class: "toolbar" },
          h(
            "div",
            { class: "actions", style: "align-items:end" },
            field("Motor de locución", engine),
            piperField,
            modeField,
            voiceField,
          ),
          h(
            "div",
            { class: "actions" },
            btn("Cancelar", () => {
              dirty = false;
              load();
            }),
            btn(
              "Guardar motor y voz",
              async () => {
                const value = await perform(
                  () =>
                    api("/api/narration", {
                      tts_engine: engine.value,
                      piper_voice: piper.value,
                      voice_mode: mode.value,
                      qwen_voice_id: mode.value === "fixed" ? voice.value : "",
                    }),
                  "Motor y voz guardados para las próximas locuciones.",
                );
                if (value) {
                  dirty = false;
                  load();
                  ctx.refresh();
                }
              },
              "primary",
            ),
          ),
        ),
      );
    }
    if (tab === "production") {
      const jobs = (data?.jobs || []).filter((j) =>
        ["running", "queued", "retry"].includes(j.status),
      );
      const size = pageSize("rows");
      page = Math.min(page, Math.max(1, Math.ceil(jobs.length / size)));
      const table = h(
          "table",
          { class: "data-table" },
          h(
            "thead",
            {},
            h(
              "tr",
              {},
              ...["Noticia", "Estado", "Voz", "Acción"].map((x) =>
                h("th", {}, x),
              ),
            ),
          ),
        ),
        rows = h("tbody");
      jobs.slice((page - 1) * size, page * size).forEach((j) =>
        rows.append(
          h(
            "tr",
            {},
            h(
              "td",
              { class: "title-cell" },
              h("strong", {}, title(j)),
              h("small", {}, j.article.source_name),
            ),
            h(
              "td",
              {},
              badge(stage(j), j.status === "running" ? "good" : "warn"),
            ),
            h("td", {}, j.work?.voice_name || "Por asignar"),
            h(
              "td",
              {},
              btn("Ver detalle", () => previewJob(j, "history")),
            ),
          ),
        ),
      );
      table.append(rows);
      body.replaceChildren(
        h(
          "p",
          { class: "hint" },
          "Los trabajos ya iniciados conservan su voz y motor. La pausa impide nuevos trabajos; no interrumpe una locución en curso.",
        ),
        jobs.length ? table : empty("No hay trabajos pendientes."),
        h("div", { class: "spacer" }),
        pager(page, jobs.length, size, (p) => {
          page = p;
          render();
        }),
      );
      return;
    }
    const size = Math.min(4, pageSize()),
      list = h("div", { class: "cards voice-grid" });
    page = Math.min(page, Math.max(1, Math.ceil(voices.length / size)));
    voices.slice((page - 1) * size, page * size).forEach((v) =>
      list.append(
        h(
          "article",
          { class: "news-card" },
          h(
            "div",
            { class: "voice-card" },
            h("span", { class: "avatar" }, v.name.slice(0, 2).toUpperCase()),
            h(
              "div",
              {},
              h("h3", {}, v.name),
              h("small", {}, `${duration(v.duration_seconds)} de referencia`),
            ),
            badge(
              v.enabled !== false ? "Activa" : "Desactivada",
              v.enabled !== false ? "good" : "",
            ),
          ),
          h(
            "div",
            { class: "actions" },
            btn("▶ Escuchar", () => {
              const audio = h("audio", {
                controls: true,
                src: `${qwenBase}/api/voices/${v.id}/audio`,
              });
              audio.onplay = () => silenceOthers(audio);
              modal(v.name, audio);
            }),
            btn("Editar", () => edit(v)),
            btn(v.enabled !== false ? "Desactivar" : "Activar", () =>
              voiceAction(v, "update", { enabled: v.enabled === false }),
            ),
            btn(
              "Eliminar",
              () =>
                confirmAction(
                  `Eliminar la voz «${v.name}» de Qwen. Los audios de noticias ya generados se conservarán.`,
                  () => voiceAction(v, "delete", {}),
                ),
              "danger",
            ),
          ),
        ),
      ),
    );
    body.replaceChildren(
      h(
        "div",
        { class: "toolbar" },
        h(
          "p",
          { class: "hint" },
          `${voices.length} voces en Qwen · ${voices.filter((v) => v.enabled !== false).length} activas`,
        ),
        h(
          "div",
          { class: "actions" },
          btn("Actualizar biblioteca", () => {
            dirty = false;
            load();
          }),
          btn("Importar carpeta", async () => {
            const result = await perform(
              () => api("/api/dashboard/voices/import", {}),
              "Carpeta de voces revisada.",
            );
            if (result) {
              if (result.errors?.length)
                notify(result.errors.join(" · "), true);
              load();
            }
          }),
          btn("Añadir voz", () => edit(), "primary"),
        ),
      ),
      voices.length
        ? list
        : empty(
            "Añade una muestra de audio y su transcripción para clonar una voz.",
          ),
      pager(page, voices.length, size, (p) => {
        page = p;
        render();
      }),
    );
  }
  async function voiceAction(voice, action, payload) {
    const value = await perform(
      () => api(`/api/dashboard/voices/${voice.id}/${action}`, payload),
      "Biblioteca de voces actualizada.",
    );
    if (value) {
      dirty = false;
      load();
    }
  }
  function edit(voice) {
    const name = h("input", { value: voice?.name || "", maxLength: 80 }),
      transcript = h("textarea", {
        value: voice?.transcript || "",
        maxLength: 3000,
        rows: 5,
      }),
      audio = h("input", { type: "file", accept: "audio/*" }),
      content = h(
        "div",
        { class: "compact-list" },
        field("Nombre", name),
        field(
          "Audio de referencia",
          audio,
          voice
            ? "Opcional: selecciona un archivo solo si quieres sustituir la muestra."
            : "Archivo de hasta 12 MiB.",
        ),
        field(
          "Transcripción exacta de la muestra",
          transcript,
          "Debe coincidir con lo que se escucha en el audio.",
        ),
      );
    const m = modal(
      voice ? "Editar voz clonada" : "Añadir voz clonada",
      content,
    );
    const save = btn(
      "Guardar voz",
      async () => {
        save.disabled = true;
        try {
          const payload = { name: name.value, transcript: transcript.value };
          if (audio.files[0]) {
            if (audio.files[0].size > 12 * 1024 * 1024)
              throw new Error("El archivo no puede superar 12 MiB.");
            payload.audio_base64 = await new Promise((resolve, reject) => {
              const r = new FileReader();
              r.onload = () => resolve(r.result.split(",")[1]);
              r.onerror = reject;
              r.readAsDataURL(audio.files[0]);
            });
          }
          if (!voice && !payload.audio_base64)
            throw new Error("Selecciona el audio de referencia.");
          await api(
            voice
              ? `/api/dashboard/voices/${voice.id}/update`
              : "/api/dashboard/voices/add",
            payload,
          );
          m.close();
          dirty = false;
          notify("Voz guardada.");
          load();
        } catch (e) {
          notify(e.message, true);
        } finally {
          save.disabled = false;
        }
      },
      "primary",
    );
    content.append(save);
  }
  root.append(bar, enginePanel, body);
  load();
  return {
    update(value) {
      data = value;
      if (tab === "production") render();
    },
    show() {
      if (!dirty) load();
    },
    canLeave() {
      return !dirty;
    },
  };
}
