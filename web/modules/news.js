import {
  h,
  btn,
  select,
  badge,
  title,
  stage,
  date,
  duration,
  api,
  perform,
  pager,
  pageSize,
  empty,
  previewJob,
  notify,
} from "./core.js";
export function mount(root, ctx) {
  let page = 1,
    seq = 0,
    last = 0,
    filter = "on_air",
    q = "";
  const cards = h("div", { class: "cards" }),
    paging = h("div"),
    search = h("input", {
      class: "search-input",
      placeholder: "Buscar título o fuente",
      type: "search",
      "aria-label": "Buscar noticias",
    }),
    choice = select(
      [
        ["on_air", "En parrilla"],
        ["pending", "Pendientes"],
        ["waiting", "Reserva de candidatas"],
        ["ready", "Con vídeo disponible"],
        ["discarded", "Descartadas"],
        ["all", "Historial completo"],
      ],
      filter,
    );
  choice.onchange = () => {
    filter = choice.value;
    page = 1;
    load();
  };
  let debounce;
  search.oninput = () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => {
      q = search.value;
      page = 1;
      load();
    }, 300);
  };
  root.append(
    h(
      "div",
      { class: "toolbar" },
      h("div", { class: "actions" }, choice, search),
      btn("Actualizar", () => load()),
    ),
    cards,
    paging,
  );
  async function load() {
    const request = ++seq;
    try {
      const size = pageSize();
      const value = await api(
        `/api/dashboard/library?filter=${filter}&page=${page}&limit=${size}&q=${encodeURIComponent(q)}`,
      );
      if (request !== seq) return;
      if (page > 1 && !value.jobs.length) {
        page--;
        return load();
      }
      cards.replaceChildren(
        ...value.jobs.map((job) => {
          const card = h(
            "article",
            { class: "news-card" },
            h(
              "div",
              { class: "source-line" },
              h("span", {}, job.article.source_name),
              h(
                "span",
                {},
                new Date(job.published_at).toLocaleDateString("es-ES"),
              ),
            ),
            h("h3", {}, title(job)),
            h(
              "div",
              { class: "row" },
              badge(
                stage(job),
                job.active ? "good" : job.status === "running" ? "warn" : "",
              ),
              job.pinned ? badge("Fijada") : null,
            ),
            h(
              "p",
              { class: "summary" },
              job.result?.script ||
                job.work?.script ||
                job.article.content ||
                job.article.summary ||
                "",
            ),
          );
          const actions = h(
            "div",
            { class: "actions" },
            btn("Leer", () => previewJob(job)),
          );
          if (job.result && !job.artifacts_deleted_at)
            actions.append(
              btn("▶ Ver / escuchar", () => previewJob(job, "media")),
            );
          if (["waiting", "queued", "retry"].includes(job.status))
            actions.append(
              btn(
                job.requested ? "Solicitada" : "Producir",
                async () => {
                  const result = await perform(
                    () => api("/api/dashboard/request", { id: job.id }),
                    "Noticia solicitada para producción. Se mantienen el ritmo y los límites configurados.",
                  );
                  if (result) load();
                },
                "",
                { disabled: !!job.requested },
              ),
            );
          card.append(actions);
          return card;
        }),
      );
      if (!value.jobs.length)
        cards.append(empty("No hay noticias con este filtro."));
      paging.replaceChildren(
        pager(page, value.total, size, (p) => {
          page = p;
          load();
        }),
      );
      last = Date.now();
    } catch (e) {
      notify(e.message, true);
    }
  }
  load();
  return {
    update() {
      if (Date.now() - last > 12000) load();
    },
    show() {
      load();
    },
  };
}
