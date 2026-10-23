import {
  h,
  btn,
  field,
  select,
  api,
  perform,
  notify,
  modal,
  pager,
  badge,
  empty,
  date,
} from "./core.js";
import { fitTableRows } from "./table-layout.js";

const dimensions = {
  relevance: "Afinidad",
  impact: "Impacto",
  novelty: "Novedad",
  substance: "Información concreta",
};

export function mount(root, ctx) {
  root.className = "relevance-layout";
  let snapshot,
    data,
    dirty = false,
    page = 1,
    size = 5,
    last = 0,
    sequence = 0;
  const mode = select(
    [
      ["off", "Desactivado"],
      ["observe", "Observación"],
      ["rank", "Influir en la selección"],
    ],
    "observe",
  );
  const budget = h("input", { type: "number", min: 1, max: 100 });
  const influence = h("input", { type: "number", min: 0, max: 100, step: 5 });
  const controls = h("div", { class: "relevance-controls" });
  const status = h("p", { class: "hint", role: "status" });
  const tableSpace = h("div", { class: "sources-table" });
  const paging = h("div");
  const save = btn(
    "Guardar",
    async () => {
      const result = await perform(
        () =>
          api("/api/dashboard/config", {
            revision: snapshot.revision,
            changes: {
              relevance: {
                ...snapshot.settings.relevance,
                mode: mode.value,
                max_evaluations_per_hour: Number(budget.value),
                influence: Number(influence.value) / 100,
              },
            },
          }),
        "Valoración editorial configurada. Los cambios se aplican sin reiniciar.",
      );
      if (result) {
        snapshot = result;
        dirty = false;
        ctx.refresh();
        load();
      }
    },
    "primary",
  );
  const evaluate = btn("Valorar ahora", async () => {
    if (dirty)
      return notify(
        "Guarda los ajustes antes de solicitar valoraciones.",
        true,
      );
    evaluate.disabled = true;
    const result = await perform(() =>
      api("/api/dashboard/relevance/evaluate", {}),
    );
    if (result) notify(result.message || "Petición de valoración recibida.");
    await load();
  });
  controls.append(
    field("Modo", mode),
    field("Extractos automáticos / hora", budget),
    field("Influencia frente a actualidad (%)", influence),
    h(
      "div",
      { class: "actions" },
      btn("Criterios y pesos", editCriteria),
      btn("Recargar / cancelar", async () => {
        dirty = false;
        await load();
      }),
      save,
      evaluate,
    ),
  );
  [mode, budget, influence].forEach(
    (input) =>
      (input.oninput = () => {
        dirty = true;
        save.disabled = false;
      }),
  );
  root.append(controls, status, tableSpace, paging);
  const fit = fitTableRows(tableSpace, (fitted) => {
    const next = Math.min(50, fitted);
    if (size !== next) {
      size = next;
      load();
    }
  });

  function editCriteria() {
    if (!snapshot || dirty)
      return notify(
        "Guarda o cancela los ajustes antes de editar criterios.",
        true,
      );
    const base = structuredClone(snapshot);
    const text = h("textarea", {
      value: base.settings.relevance.criteria,
      maxLength: 6000,
      rows: 10,
    });
    const weights = {};
    const fields = h("div", { class: "form-grid" });
    for (const [key, name] of Object.entries(dimensions)) {
      weights[key] = h("input", {
        type: "number",
        min: 0,
        max: 100,
        step: 0.05,
        value: base.settings.relevance.weights[key],
      });
      fields.append(field(name, weights[key]));
    }
    const content = h(
      "div",
      { class: "compact-list" },
      h(
        "p",
        { class: "hint" },
        "Evalúa titulares y extractos. No contrasta los hechos ni lee el artículo completo. Los pesos se normalizan automáticamente.",
      ),
      field("Criterios editoriales", text),
      fields,
    );
    const dialog = modal("Relevancia · criterios y pesos", content);
    content.append(
      btn(
        "Guardar criterios",
        async () => {
          const result = await perform(
            () =>
              api("/api/dashboard/config", {
                revision: base.revision,
                changes: {
                  relevance: {
                    ...base.settings.relevance,
                    criteria: text.value,
                    weights: Object.fromEntries(
                      Object.entries(weights).map(([key, input]) => [
                        key,
                        Number(input.value),
                      ]),
                    ),
                  },
                },
              }),
            "Criterios guardados. Las notas antiguas se muestran desactualizadas. Valorar ahora recalcula la parrilla y los trabajos programados sin el límite horario automático.",
          );
          if (result) {
            dialog.close();
            snapshot = result;
            ctx.refresh();
            load();
          }
        },
        "primary",
      ),
    );
  }

  function detail(row) {
    const value =
      row.score == null && row.stale ? row.previous_evaluation : row.evaluation;
    const content = h(
      "div",
      { class: "compact-list" },
      h(
        "p",
        { class: "story-text" },
        value.reason ||
          value.error ||
          "Todavía no se ha valorado esta noticia.",
      ),
    );
    if (row.stale)
      content.prepend(
        h(
          "p",
          { class: "hint dirty" },
          "Valoración desactualizada: corresponde a criterios o material anteriores. Se conserva para consulta y no interviene en la selección.",
        ),
      );
    if (row.evaluation.error)
      content.append(h("p", { class: "error" }, row.evaluation.error));
    if (value.scores)
      content.append(
        h(
          "div",
          { class: "form-grid" },
          ...Object.entries(dimensions).map(([key, label]) =>
            h("p", {}, `${label}: ${value.scores[key]}/100`),
          ),
        ),
      );
    content.append(
      h(
        "p",
        { class: "hint" },
        `${value.model || "Modelo local"} · ${date(value.evaluated_at)}`,
      ),
      h(
        "p",
        { class: "hint" },
        "Es una estimación editorial basada en un extracto, no una verificación. El balance de fuentes y la actualidad también intervienen en la selección.",
      ),
    );
    modal(row.title, content);
  }

  function render() {
    if (!data) return;
    if (!dirty && !controls.contains(document.activeElement)) {
      mode.value = snapshot.settings.relevance.mode;
      budget.value = snapshot.settings.relevance.max_evaluations_per_hour;
      influence.value = Math.round(snapshot.settings.relevance.influence * 100);
    }
    save.disabled = !dirty;
    const manual = data.manual || {};
    const manualPending = [
      "queued",
      "waiting_production",
      "waiting_ai",
      "running",
    ].includes(manual.status);
    evaluate.disabled = data.mode === "off" || manualPending;
    const label =
      data.mode === "observe"
        ? "Observación: las puntuaciones no cambian la selección."
        : data.mode === "off"
          ? "Desactivado: no se consulta el modelo. Las valoraciones guardadas se conservan."
          : "Selección: combina relevancia y actualidad dentro del balance de fuentes; respeta noticias fijadas y peticiones manuales.";
    const completed =
      (manual.completed_ids?.length || 0) +
      (manual.failed_ids?.length || 0) +
      (manual.skipped_ids?.length || 0);
    const progress = manualPending
      ? ` Progreso manual: ${completed}/${manual.total} terminadas${manual.status === "running" ? `; lote de ${manual.batch_ids?.length || 0} en curso` : ""}.`
      : "";
    let activity = manualPending
      ? manual.message
      : data.active
        ? "Gemma está valorando extractos automáticamente."
        : manual.message || `Última valoración: ${date(data.last_at)}.`;
    if (manual.status === "waiting_production" && data.production) {
      const phase = {
        extracting: "extracción",
        drafting: "resumen",
        voicing: "generación de voz",
        downloading: "descarga del audio",
        rendering: "preparación del vídeo",
        packaging: "incorporación a parrilla",
      };
      activity += ` Fase actual: ${phase[data.production.stage] || data.production.stage}.`;
    }
    const availability =
      data.remaining_this_hour === 0 && data.automatic_available_at
        ? ` Próximo hueco automático: ${date(data.automatic_available_at)}.`
        : "";
    status.textContent = `${label} ${data.evaluated}/${data.total} vigentes · ${data.stale || 0} desactualizadas · ${data.remaining_this_hour} evaluaciones automáticas disponibles.${availability} ${activity}${progress}${data.error ? ` Incidencia: ${data.error}` : ""}`;
    const table = h("table", { class: "data-table" });
    table.append(
      h(
        "thead",
        {},
        h(
          "tr",
          {},
          ...["Noticia / fuente", "Ubicación", "Relevancia", "Detalle"].map(
            (t) => h("th", {}, t),
          ),
        ),
      ),
    );
    table.append(
      h(
        "tbody",
        {},
        ...data.rows.map((row) =>
          h(
            "tr",
            {},
            h(
              "td",
              { class: "title-cell", style: "width:55%" },
              h("strong", { title: row.title }, row.title),
              h("small", {}, row.source),
            ),
            h("td", {}, row.status),
            h(
              "td",
              {},
              badge(
                row.score == null && row.stale
                  ? `${row.previous_score}/100 · desactualizada`
                  : row.score == null
                    ? {
                        error: "Error",
                        evaluating: "Valorando…",
                        pending: "Pendiente",
                      }[row.evaluation.status] || "Pendiente"
                    : `${row.score}/100`,
                row.stale
                  ? "warn"
                  : row.score != null && row.score >= 70
                    ? "good"
                    : "",
              ),
            ),
            h(
              "td",
              {},
              btn("Motivo", () => detail(row)),
            ),
          ),
        ),
      ),
    );
    tableSpace.replaceChildren(
      data.rows.length
        ? table
        : empty("No hay noticias disponibles para valorar."),
    );
    paging.replaceChildren(
      pager(page, data.total, size, (p) => {
        page = p;
        load();
      }),
    );
    fit();
  }

  async function load() {
    const request = ++sequence;
    try {
      const [next, configuration] = await Promise.all([
        api(`/api/dashboard/relevance?page=${page}&limit=${size}`),
        api("/api/dashboard/config"),
      ]);
      if (request !== sequence) return;
      data = next;
      if (!dirty) snapshot = configuration;
      if (page > 1 && !data.rows.length) {
        page--;
        return load();
      }
      last = Date.now();
      render();
    } catch (error) {
      if (request === sequence) status.textContent = error.message;
    }
  }
  load();
  return {
    update() {
      if (Date.now() - last > 10000) load();
    },
    show: load,
    canLeave: () => !dirty,
  };
}
