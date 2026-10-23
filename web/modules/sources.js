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
  badge,
  empty,
  date,
} from "./core.js";
import { fitTableRows } from "./table-layout.js";
import { mount as mountRelevance } from "./relevance.js";
export function mount(root, ctx) {
  root.classList.add("sources-view");
  let searchDirty = false;
  let catalog = null,
    status = null,
    data = null,
    tab = "catalog",
    page = 1,
    filter = "",
    rowsPerPage = pageSize("rows");
  const weightDrafts = new Map();
  let relevance;
  const relevanceRoot = h("div");
  const bar = h("div"),
    body = h("section", { class: "panel table-panel" }),
    tableSpace = h("div", { class: "sources-table" }),
    search = h("input", {
      class: "search-input",
      placeholder: "Filtrar fuentes",
      type: "search",
      "aria-label": "Filtrar fuentes",
    });
  const scheduleFit = fitTableRows(tableSpace, (fitted) => {
    if (rowsPerPage !== fitted) {
      rowsPerPage = fitted;
      render();
    }
  });
  search.oninput = () => {
    filter = search.value.toLowerCase();
    page = 1;
    render();
  };
  async function load() {
    const value = await perform(() => api("/api/dashboard/sources"));
    if (value) {
      catalog = { catalog: value.catalog, revision: value.revision };
      status = value.status;
      render();
    }
  }
  async function saveCatalog(value) {
    const result = await perform(
      () => api("/api/dashboard/sources", value),
      "Catálogo guardado. Se aplicará en las próximas consultas, respetando las pausas de cada fuente.",
    );
    if (result) {
      catalog = result;
      load();
    }
    return result;
  }
  async function configChange(change) {
    const snapshot = await api("/api/dashboard/config");
    return api("/api/dashboard/config", {
      revision: snapshot.revision,
      changes: change(snapshot.settings),
    });
  }
  function render() {
    const searchFocused = document.activeElement === search;
    const caret = search.selectionStart;
    bar.replaceChildren(
      tabs(
        [
          ["catalog", "Catálogo de fuentes"],
          ["balance", "Pesos y balance"],
          ["search", "Sistema de búsqueda"],
          ["relevance", "Relevancia IA"],
        ],
        tab,
        (t) => {
          if (searchDirty)
            return notify(
              "Guarda los criterios de búsqueda antes de cambiar de apartado.",
              true,
            );
          if (relevance?.canLeave() === false)
            return notify(
              "Guarda o cancela los ajustes de relevancia antes de cambiar de apartado.",
              true,
            );
          tab = t;
          page = 1;
          render();
        },
      ),
    );
    if (tab === "relevance") {
      body.className = "panel table-panel";
      body.replaceChildren(relevanceRoot);
      if (!relevance) relevance = mountRelevance(relevanceRoot, ctx);
      else relevance.show();
      return;
    }
    if (!catalog) {
      body.replaceChildren(empty("Consultando el servicio de noticias…"));
      return;
    }
    if (tab === "search") {
      body.className = "panel table-panel";
      renderSearch();
      return;
    }
    body.className = "panel sources-list";
    const all = catalog.catalog.sources.filter(
      (s) =>
        !filter ||
        `${s.name} ${s.id} ${s.platform || "web"}`
          .toLowerCase()
          .includes(filter),
    );
    const size = rowsPerPage;
    page = Math.min(page, Math.max(1, Math.ceil(all.length / size)));
    const controls = h(
      "div",
      { class: "toolbar" },
      h(
        "div",
        { class: "actions" },
        search,
        badge(
          `${catalog.catalog.sources.filter((s) => s.enabled).length} activas`,
        ),
      ),
      h(
        "div",
        { class: "actions" },
        btn("Actualizar estado", load),
        tab === "catalog"
          ? btn("Añadir fuente", () => editSource(), "primary")
          : null,
      ),
    );
    const table = h("table", { class: "data-table" }),
      head = h("thead"),
      rows = h("tbody");
    const headings =
      tab === "catalog"
        ? ["Fuente / sistema", "Estado", "Frecuencia", "Acciones"]
        : ["Fuente", "Publicadas", "Parrilla", "Pendientes", "Peso"];
    head.append(
      h(
        "tr",
        {},
        ...headings.map((label, i) =>
          h(
            "th",
            {
              style: i === 0 ? "width:40%" : null,
              class: tab === "catalog" && i === 2 ? "optional" : "",
            },
            label,
          ),
        ),
      ),
    );
    all.slice((page - 1) * size, page * size).forEach((source) => {
      const row = h("tr"),
        info = status?.sources?.find((s) => s.id === source.id),
        balance = data?.source_balance?.sources.find((s) => s.id === source.id);
      row.append(
        h(
          "td",
          { class: "title-cell" },
          h("strong", { title: source.name }, source.name),
          h(
            "small",
            {},
            `${source.platform || "web"} · ${source.connector || "rss"}`,
          ),
        ),
      );
      if (tab === "catalog") {
        const label = !source.enabled
          ? "Desactivada"
          : info?.state === "rate_limited"
            ? "En pausa por límite"
            : info?.error
              ? "Con incidencia"
              : info?.available
                ? "Disponible"
                : "Sin recogida activa";
        const detail = () => {
          const content = h(
            "div",
            { class: "compact-list" },
            h("p", { class: "hint" }, source.notes || "Sin notas."),
            h(
              "p",
              { class: "hint" },
              `Última lectura: ${date(info?.last_checked_at || info?.last_success_at)} · Próxima lectura: ${date(info?.next_check_at)}`,
            ),
            h("p", { class: "error" }, info?.error || ""),
          );
          const m = modal(source.name, content);
          content.append(
            btn(source.enabled ? "Desactivar" : "Activar", async () => {
              const value = structuredClone(catalog);
              value.catalog.sources.find((s) => s.id === source.id).enabled =
                !source.enabled;
              if (await saveCatalog(value)) m.close();
            }),
          );
        };
        const remove = () =>
          confirmAction(
            `Eliminar «${source.name}» del catálogo. Las noticias ya producidas se conservarán hasta su retirada normal.`,
            async () => {
              const value = structuredClone(catalog);
              value.catalog.sources = value.catalog.sources.filter(
                (s) => s.id !== source.id,
              );
              await saveCatalog(value);
            },
          );
        row.append(
          h(
            "td",
            {},
            badge(
              label,
              source.enabled && info?.available && !info?.error
                ? "good"
                : "warn",
            ),
          ),
          h(
            "td",
            { class: "optional" },
            `${Math.round((info?.refresh_seconds || source.refresh_seconds || 1800) / 60)} min`,
          ),
          h(
            "td",
            {},
            h(
              "div",
              { class: "controls" },
              btn("Editar", () => editSource(source)),
              btn("Detalle", detail),
              btn("×", remove, "danger", { "aria-label": "Eliminar fuente" }),
            ),
          ),
        );
      } else {
        const weight = h("input", {
          class: "weight",
          type: "number",
          min: 0.01,
          max: 100,
          step: 0.1,
          value:
            weightDrafts.get(source.id) ??
            balance?.weight ??
            data?.settings.balancing.weights[source.id] ??
            1,
          "aria-label": `Peso de ${source.name}`,
        });
        weight.oninput = () => weightDrafts.set(source.id, weight.value);
        row.append(
          ...[
            balance?.published || 0,
            balance?.on_air || 0,
            balance?.pending || 0,
          ].map((v) => h("td", {}, String(v))),
          h(
            "td",
            {},
            h(
              "div",
              { class: "actions" },
              weight,
              btn("Guardar", async () => {
                const value = Number(weight.value);
                const result = await perform(
                  () =>
                    configChange((s) => ({
                      balancing: {
                        ...s.balancing,
                        weights: { ...s.balancing.weights, [source.id]: value },
                      },
                    })),
                  "Peso actualizado. Una fuente sin material cede su turno a las demás.",
                );
                if (result) {
                  weightDrafts.delete(source.id);
                  searchDirty = false;
                  ctx.refresh();
                }
              }),
            ),
          ),
        );
      }
      rows.append(row);
    });
    table.append(head, rows);
    tableSpace.replaceChildren(
      all.length ? table : empty("No hay fuentes con este filtro."),
    );
    body.replaceChildren(
      controls,
      tableSpace,
      pager(page, all.length, size, (p) => {
        page = p;
        render();
      }),
    );
    scheduleFit();
    if (searchFocused) {
      search.focus();
      search.setSelectionRange(caret, caret);
    }
  }
  function renderSearch() {
    if (searchDirty) return;
    const s = data?.settings;
    if (!s) return;
    const query = h("input", {
        value: s.query,
        maxLength: 300,
        placeholder: "Vacío: todas las noticias de las fuentes seleccionadas",
      }),
      platform = select(
        [
          ["all", "Todas las plataformas"],
          ["web", "Web y fuentes oficiales"],
          ["social", "Redes sociales"],
          ["reddit", "Reddit"],
          ["mastodon", "Mastodon"],
          ["bluesky", "Bluesky"],
        ],
        s.platform,
      ),
      language = select(
        [
          ["all", "Todos"],
          ["es", "Español"],
          ["en", "Inglés"],
        ],
        s.language,
      ),
      strategy = select(
        [
          ["fair", "Balancear fuentes por su peso"],
          ["latest", "Priorizar las más recientes"],
        ],
        s.balancing.strategy,
      ),
      scope = h(
        "select",
        { multiple: true, size: 5 },
        ...catalog.catalog.sources.map((source) =>
          h(
            "option",
            { value: source.id, selected: s.source_ids.includes(source.id) },
            source.name,
          ),
        ),
      );
    [query, platform, language, strategy, scope].forEach(
      (control) =>
        (control.oninput = () => {
          searchDirty = true;
        }),
    );
    body.replaceChildren(
      h(
        "div",
        { class: "form-grid grow" },
        field(
          "Filtro de palabras clave",
          query,
          "Filtra las candidatas guardadas; las consultas de SearXNG se editan en su fuente.",
        ),
        field("Plataformas del canal", platform),
        field("Idioma de las fuentes", language),
        field("Política de selección", strategy),
        field(
          "Fuentes permitidas en este canal",
          scope,
          "Sin selección: todas las fuentes activas del catálogo.",
          true,
        ),
      ),
      h(
        "div",
        { class: "form-footer" },
        h(
          "p",
          { class: "hint" },
          "Las fuentes directas son la base. SearXNG aporta descubrimiento complementario, con sus propias consultas.",
        ),
        btn("Cancelar cambios", () => {
          searchDirty = false;
          renderSearch();
        }),
        btn("Revisar fuentes ahora", async () => {
          if (searchDirty)
            return notify(
              "Guarda los criterios antes de revisar las fuentes.",
              true,
            );
          await perform(
            () => api("/api/scan", {}),
            "Revisión solicitada. Se respetan los intervalos de las fuentes.",
          );
        }),
        btn(
          "Guardar selección",
          async () => {
            const result = await perform(
              () =>
                configChange((s) => ({
                  query: query.value,
                  platform: platform.value,
                  language: language.value,
                  source_ids: [...scope.selectedOptions].map((o) => o.value),
                  balancing: { ...s.balancing, strategy: strategy.value },
                })),
              "Selección de búsqueda guardada.",
            );
            if (result) {
              searchDirty = false;
              ctx.refresh();
            }
          },
          "primary",
        ),
      ),
    );
  }
  function editSource(original) {
    let base = original
      ? structuredClone(original)
      : {
          id: "",
          name: "",
          url: "",
          feed_url: null,
          enabled: true,
          platform: "web",
          language: "en",
          type: "secondary",
          topics: [],
          connector: "rss",
          refresh_seconds: 3600,
        };
    const input = {};
    const fields = h("div", { class: "form-grid" });
    const schema = [
      ["id", "Identificador", "text"],
      ["name", "Nombre visible", "text"],
      ["url", "Página de la fuente", "url"],
      ["connector", "Sistema de recogida", "connector"],
      ["platform", "Plataforma", "platform"],
      ["language", "Idioma", "language"],
      ["refresh_seconds", "Intervalo mínimo (segundos)", "number"],
      ["enabled", "Fuente activa", "bool"],
    ];
    for (const [key, label, type] of schema) {
      let control;
      if (type === "connector")
        control = select(
          [
            ["rss", "RSS / Atom"],
            ["newsroom", "Newsroom con tarjetas"],
            ["bluesky_author", "Autor de Bluesky"],
            ["bluesky_feed", "Feed de Bluesky"],
            ["searxng", "SearXNG"],
          ],
          base[key] || "rss",
        );
      else if (type === "platform")
        control = select(
          ["web", "reddit", "mastodon", "bluesky"].map((x) => [x, x]),
          base[key] || "web",
        );
      else if (type === "language")
        control = select(
          [
            ["en", "Inglés"],
            ["es", "Español"],
            ["all", "Todos"],
          ],
          base[key] || "all",
        );
      else if (type === "bool")
        control = select(
          [
            ["true", "Sí"],
            ["false", "No"],
          ],
          String(base[key]),
        );
      else
        control = h("input", {
          type,
          value: base[key] ?? "",
          required: true,
          min: type === "number" ? 60 : null,
          disabled: key === "id" && !!original,
        });
      input[key] = control;
      fields.append(field(label, control));
    }
    const connectorFields = h("div", { class: "form-grid" });
    let extra = {};
    function extras() {
      extra = {};
      connectorFields.replaceChildren();
      const definitions = {
        rss: [["feed_url", "URL del feed RSS / Atom"]],
        newsroom: [["article_path", "Ruta de artículos (por ejemplo /news/)"]],
        bluesky_author: [["actor", "Usuario o DID de Bluesky"]],
        bluesky_feed: [["feed", "URI del feed de Bluesky"]],
        searxng: [
          ["queries", "Consultas (una por línea, máximo 4)"],
          ["category", "Categoría: news o general"],
          ["time_range", "Periodo: day, week o month"],
        ],
      };
      for (const [key, label] of definitions[input.connector.value]) {
        const control =
          key === "queries"
            ? h("textarea", { value: (base.queries || []).join("\n") })
            : h("input", {
                value:
                  base[key] ||
                  { category: "news", time_range: "week" }[key] ||
                  "",
              });
        extra[key] = control;
        connectorFields.append(field(label, control, "", key === "queries"));
      }
    }
    input.connector.onchange = extras;
    extras();
    const notes = h("textarea", { value: base.notes || "", rows: 2 });
    const content = h(
      "div",
      { class: "compact-list" },
      fields,
      connectorFields,
      field("Notas", notes),
    );
    const m = modal(original ? "Editar fuente" : "Añadir fuente", content);
    content.append(
      h(
        "div",
        { class: "actions" },
        btn(
          "Guardar fuente",
          async () => {
            const source = { ...base };
            for (const [key, , type] of schema)
              source[key] =
                type === "number"
                  ? Number(input[key].value)
                  : type === "bool"
                    ? input[key].value === "true"
                    : input[key].value.trim();
            for (const [key, control] of Object.entries(extra))
              source[key] =
                key === "queries"
                  ? control.value
                      .split("\n")
                      .map((s) => s.trim())
                      .filter(Boolean)
                  : control.value.trim();
            source.notes = notes.value;
            if (source.connector !== "rss") source.feed_url = null;
            const value = structuredClone(catalog);
            if (original)
              value.catalog.sources = value.catalog.sources.map((s) =>
                s.id === original.id ? source : s,
              );
            else value.catalog.sources.push(source);
            const result = await saveCatalog(value);
            if (result) m.close();
          },
          "primary",
        ),
      ),
    );
  }
  root.append(bar, body);
  load();
  return {
    update(value) {
      data = value;
      if (tab === "relevance") relevance?.update();
      else if (tab !== "search" && !body.contains(document.activeElement))
        render();
    },
    show() {
      load();
    },
    canLeave() {
      return !searchDirty && relevance?.canLeave() !== false;
    },
  };
}
