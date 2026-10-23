import {
  h,
  btn,
  badge,
  title,
  duration,
  api,
  perform,
  pager,
  pageSize,
  empty,
  previewJob,
  notify,
  modal,
  select,
} from "./core.js";
import { fitTableRows } from "./table-layout.js";
export function mount(root, ctx) {
  let draft = null,
    dirty = false,
    page = 1,
    rowsPerPage = pageSize("rows"),
    currentData,
    dragId;
  root.classList.add("playlist-view");
  const body = h("div", { class: "panel playlist-body" }),
    tableSpace = h("div", { class: "playlist-table" }),
    status = h("p", { class: "hint" }),
    foot = h("div", { class: "form-footer playlist-footer" }),
    mode = badge("Orden automático"),
    count = badge("—");
  const scheduleFit = fitTableRows(tableSpace, (fitted) => {
    if (fitted !== rowsPerPage) {
      rowsPerPage = fitted;
      render();
    }
  });
  const save = btn(
    "Guardar cambios",
    async () => {
      if (!draft) return;
      const result = await perform(
        () =>
          api("/api/dashboard/playlist", {
            revision: draft.revision,
            ids: draft.jobs.map((j) => j.id),
            pinned: draft.jobs.filter((j) => j.pinned).map((j) => j.id),
            mode: draft.mode,
            next_id: draft.next_id || null,
          }),
        "Parrilla guardada. La noticia actual terminará antes del cambio.",
      );
      if (result) {
        draft = result;
        dirty = false;
        render();
        ctx.refresh();
      }
    },
    "primary",
  );
  const mark = () => {
    dirty = true;
    draft.mode = "manual";
    render();
  };
  const reload = async () => {
    const value = await perform(() => api("/api/dashboard/playlist"));
    if (value) {
      draft = value;
      dirty = false;
      render();
    }
  };
  root.append(
    h(
      "div",
      { class: "toolbar" },
      h("div", { class: "actions" }, mode, count),
      h(
        "div",
        { class: "actions" },
        btn("Añadir noticia", () => addDialog()),
        btn("Orden automático", () => {
          if (draft) {
            draft.mode = "automatic";
            dirty = true;
            render();
          }
        }),
      ),
    ),
    body,
    foot,
  );
  function move(id, to) {
    const from = draft.jobs.findIndex((j) => j.id === id);
    if (from < 0) return;
    const [job] = draft.jobs.splice(from, 1);
    draft.jobs.splice(Math.max(0, Math.min(to, draft.jobs.length)), 0, job);
    mark();
  }
  function render() {
    if (!draft) return;
    const size = rowsPerPage,
      total = draft.jobs.length;
    page = Math.max(1, Math.min(page, Math.ceil(total / size) || 1));
    mode.textContent =
      draft.mode === "manual" ? "Orden manual" : "Orden automático";
    count.textContent = `${total} / ${currentData?.settings.max_playlist ?? "—"} noticias`;
    status.textContent = dirty
      ? "Cambios sin guardar. Se aplicarán al guardar y terminar la noticia actual."
      : "Arrastra una fila o usa las flechas. Cada vídeo nuevo sustituye a la noticia que lleve más tiempo en parrilla, salvo las fijadas.";
    status.className = dirty ? "hint dirty" : "hint";
    if (
      total &&
      total >= (currentData?.settings.max_playlist || Infinity) &&
      draft.jobs.every((j) => j.pinned)
    ) {
      status.textContent +=
        " Toda la parrilla está fijada: no hay plazas para renovación automática.";
      status.className = "hint dirty";
    }
    const table = h(
        "table",
        { class: "data-table" },
        h(
          "thead",
          {},
          h(
            "tr",
            {},
            h("th", { style: "width:42px" }, "#"),
            h("th", {}, "Noticia"),
            h("th", { class: "optional", style: "width:75px" }, "Duración"),
            h("th", { style: "width:215px" }, "Orden y acciones"),
          ),
        ),
      ),
      tbody = h("tbody");
    draft.jobs.slice((page - 1) * size, page * size).forEach((job, i) => {
      const position = (page - 1) * size + i;
      const playing = job.id === currentData?.broadcast.job_id;
      const row = h("tr", { draggable: true, class: playing ? "playing" : "" });
      row.ondragstart = (e) => {
        dragId = job.id;
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", job.id);
      };
      row.ondragover = (e) => {
        e.preventDefault();
      };
      row.ondrop = (e) => {
        e.preventDefault();
        if (dragId) move(dragId, position);
        dragId = null;
      };
      row.append(
        h("td", {}, String(position + 1).padStart(2, "0")),
        h(
          "td",
          { class: "title-cell" },
          h("strong", { title: title(job) }, title(job)),
          h(
            "small",
            {},
            `${playing ? "● En el emisor · " : ""}${draft.next_id === job.id ? "Próxima · " : ""}${job.pinned ? "Fijada · " : ""}${job.article.source_name}`,
          ),
        ),
        h("td", { class: "optional" }, duration(job.result?.duration_seconds)),
        h(
          "td",
          {},
          h(
            "div",
            { class: "controls" },
            btn("↑", () => move(job.id, position - 1), "", {
              disabled: position === 0,
              "aria-label": "Subir noticia",
              title: "Subir",
            }),
            btn("↓", () => move(job.id, position + 1), "", {
              disabled: position === total - 1,
              "aria-label": "Bajar noticia",
              title: "Bajar",
            }),
            btn(
              job.pinned ? "◆" : "◇",
              () => {
                job.pinned = !job.pinned;
                dirty = true;
                render();
              },
              job.pinned ? "flag" : "",
              {
                title: job.pinned ? "Desfijar" : "Fijar para conservar",
                "aria-label": job.pinned ? "Desfijar noticia" : "Fijar noticia",
              },
            ),
            btn("⋯", () => options(job), "", {
              title: "Más acciones",
              "aria-label": "Más acciones de la noticia",
            }),
          ),
        ),
      );
      tbody.append(row);
    });
    table.append(tbody);
    tableSpace.replaceChildren(table);
    body.replaceChildren(
      status,
      tableSpace,
      pager(page, total, size, (p) => {
        page = p;
        render();
      }),
    );
    scheduleFit();
    if (!total)
      body.replaceChildren(
        status,
        empty(
          "Añade noticias terminadas o espera a que termine la producción.",
        ),
      );
    save.disabled = !dirty;
    foot.replaceChildren(
      h(
        "p",
        { class: "hint" },
        "Retirar una noticia evita su reincorporación automática y libera sus archivos al finalizar su uso.",
      ),
      h(
        "div",
        { class: "actions" },
        btn("Cancelar", reload, "", { disabled: !dirty }),
        save,
      ),
    );
  }
  function options(job) {
    const actions = h("div", { class: "compact-list" });
    const m = modal(title(job), actions);
    const pos = h("input", {
      type: "number",
      min: 1,
      max: draft.jobs.length,
      value: draft.jobs.findIndex((j) => j.id === job.id) + 1,
    });
    actions.append(
      btn("Leer / previsualizar", () => {
        m.close();
        previewJob(job);
      }),
      btn("Emitir a continuación", () => {
        draft.next_id = job.id;
        dirty = true;
        m.close();
        render();
      }),
      h(
        "div",
        { class: "row" },
        h("label", {}, "Mover a la posición"),
        pos,
        btn("Mover", () => {
          const n = Number(pos.value);
          if (!Number.isInteger(n) || n < 1 || n > draft.jobs.length)
            return notify("Indica una posición válida.", true);
          move(job.id, n - 1);
          m.close();
        }),
      ),
      h(
        "p",
        { class: "hint" },
        "La noticia que está sonando terminará. El cambio se aplica al guardar.",
      ),
      btn(
        "Retirar de la parrilla",
        () => {
          draft.jobs = draft.jobs.filter((j) => j.id !== job.id);
          if (draft.next_id === job.id) draft.next_id = null;
          dirty = true;
          m.close();
          render();
        },
        "danger",
      ),
    );
  }
  async function addDialog() {
    if (!draft) return;
    let p = 1;
    const choice = select(
        [
          ["ready", "Vídeos disponibles"],
          ["pending", "En producción / pendientes"],
          ["waiting", "Reserva de candidatas"],
        ],
        "ready",
      ),
      list = h("div", { class: "compact-list" }),
      paging = h("div");
    const m = modal(
      "Añadir material al canal",
      h(
        "div",
        { class: "compact-list" },
        h(
          "p",
          { class: "hint" },
          "Un vídeo terminado se incorpora al borrador. Una candidata se solicita para producción y entrará al terminar, según las plazas disponibles.",
        ),
        choice,
        list,
        paging,
      ),
    );
    const load = async () => {
      const value = await perform(() =>
        api(`/api/dashboard/library?filter=${choice.value}&page=${p}&limit=4`),
      );
      if (!value) return;
      list.replaceChildren(
        ...value.jobs.map((job) =>
          h(
            "div",
            { class: "compact-item" },
            h("strong", {}, title(job)),
            h("small", {}, job.article.source_name),
            h(
              "div",
              { class: "actions" },
              btn(
                choice.value === "ready"
                  ? "Añadir al borrador"
                  : job.requested
                    ? "Solicitada"
                    : "Solicitar producción",
                async () => {
                  if (choice.value === "ready") {
                    if (draft.jobs.length >= currentData.settings.max_playlist)
                      return notify(
                        "La parrilla está llena. Retira una noticia del borrador antes de añadir otra.",
                        true,
                      );
                    draft.jobs.push(job);
                    dirty = true;
                    render();
                    load();
                  } else {
                    const r = await perform(
                      () => api("/api/dashboard/request", { id: job.id }),
                      "Solicitud guardada; no se altera el límite de noticias nuevas por hora.",
                    );
                    if (r) load();
                  }
                },
                "",
                {
                  disabled:
                    choice.value === "ready"
                      ? draft.jobs.some((j) => j.id === job.id)
                      : !!job.requested,
                },
              ),
            ),
          ),
        ),
      );
      if (!value.jobs.length)
        list.append(empty("No hay material disponible en esta categoría."));
      paging.replaceChildren(
        pager(p, value.total, 4, (n) => {
          p = n;
          load();
        }),
      );
    };
    choice.onchange = () => {
      p = 1;
      load();
    };
    load();
  }
  reload();
  return {
    update(data) {
      currentData = data;
      if (!draft) return;
      const old = draft.jobs.map((j) => j.id).join();
      const actual = data.playlist.map((j) => j.id).join();
      if (
        !dirty &&
        (old !== actual ||
          draft.mode !== data.schedule?.mode ||
          (draft.next_id || null) !== (data.schedule?.next_id || null) ||
          draft.jobs.some(
            (job) =>
              !!job.pinned !==
              !!data.playlist.find((j) => j.id === job.id)?.pinned,
          ))
      )
        reload();
      else render();
    },
    show() {
      if (!dirty) reload();
    },
    canLeave() {
      return !dirty;
    },
  };
}
