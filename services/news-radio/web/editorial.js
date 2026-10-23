/* Manual editing only: opening the editor never downloads articles or runs a model. */
(() => {
  const el = (id) => document.getElementById(id);
  const dialog = el("editorial-dialog");
  const labels = { generating: "Redactando", ready: "Pendiente de revisión", reviewed: "Revisado", error: "Error" };
  let articleId = null;
  let draftId = null;
  let pollTimer;
  let context = 0;
  let pending = false;

  async function api(path, body) {
    const response = await fetch(path, body === undefined
      ? { headers: { Accept: "application/json" } }
      : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Error HTTP ${response.status}`);
    return data;
  }

  function message(text, kind = "info") {
    el("editorial-message").className = `status ${kind}`;
    el("editorial-message").textContent = text;
  }

  function safeLink(element, url) {
    try {
      const parsed = new URL(url);
      if (!["http:", "https:"].includes(parsed.protocol)) throw new Error("scheme");
      element.href = parsed.href;
      element.hidden = false;
    } catch {
      element.removeAttribute("href");
      element.hidden = true;
    }
  }

  function busy(value, generating = false) {
    pending = value;
    el("editorial-fetch").disabled = value;
    el("editorial-generate").disabled = value;
    el("editorial-text").disabled = value;
    el("editorial-generate").textContent = generating ? "Redactando con Ollama…" : "Generar borrador en español";
  }

  function showMaterial(material) {
    el("editorial-text").value = material.text;
    const kind = { excerpt: "Extracto del feed", extracted: "Texto extraído", manual: "Texto manual" }[material.kind] || "Texto de origen";
    el("material-note").textContent = `${kind}${material.truncated ? " · limitado o incompleto" : ""}. ${material.note}`;
    safeLink(el("material-link"), material.url);
  }

  function showArticle(article) {
    articleId = article.id;
    el("editorial-dialog-title").textContent = article.title;
    el("editorial-origin").textContent = `${(article.sources || []).join(" · ")} · ${article.author || "Autor no indicado"} · ${article.published_at ? new Date(article.published_at).toLocaleString("es-ES") : "Fecha sin verificar"}`;
    safeLink(el("editorial-link"), article.url);
  }

  function reset() {
    context += 1;
    clearTimeout(pollTimer);
    articleId = null;
    draftId = null;
    el("draft-output").hidden = true;
    el("editorial-text").value = "";
    el("draft-meta").textContent = "El resumen aparecerá aquí. Se guarda automáticamente; puedes cerrar el panel mientras se genera.";
    busy(true);
    if (!dialog.open) dialog.showModal();
    message("Leyendo la noticia guardada…");
    return context;
  }

  async function loadInfo() {
    try {
      const data = await api("/api/editorial");
      el("editorial-instructions").textContent = data.instructions;
      const list = el("editorial-drafts");
      list.replaceChildren();
      if (!data.drafts.length) list.textContent = "Todavía no hay borradores. Selecciona una noticia para empezar.";
      for (const draft of data.drafts) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "draft-item secondary";
        button.textContent = `${labels[draft.status] || draft.status} · ${draft.title} · ${new Date(draft.created_at).toLocaleString("es-ES")}`;
        button.addEventListener("click", () => openDraft(draft.id));
        list.append(button);
      }
      return data;
    } catch (error) {
      el("ollama-status").textContent = error.message;
      return null;
    }
  }

  async function checkConnection() {
    el("ollama-check").disabled = true;
    el("ollama-status").textContent = "Comprobando Ollama local…";
    try {
      const data = await api("/api/editorial/connection");
      el("ollama-status").textContent = data.model_available
        ? `Ollama conectado · ${data.model} · Razonamiento desactivado`
        : `Ollama conectado, pero no está instalado el modelo configurado: ${data.model}`;
    } catch (error) {
      el("ollama-status").textContent = error.message;
    } finally {
      el("ollama-check").disabled = false;
    }
  }

  function showDraft(draft, token) {
    if (context !== token || !dialog.open) return;
    draftId = draft.id;
    if (draft.status === "generating") {
      busy(true, true);
      message("Ollama está resumiendo y redactando en español, sin razonamiento. Puedes cerrar este panel; el borrador seguirá guardándose.");
      pollTimer = setTimeout(() => poll(draft.id, token), 2000);
      return;
    }
    busy(false);
    if (draft.status === "error") {
      message(draft.error, "error");
      el("draft-meta").textContent = "La generación falló. El texto de origen se conserva y puedes reintentar.";
      loadInfo();
      return;
    }
    el("draft-output").hidden = false;
    el("draft-title").value = draft.edited_title ?? draft.result.title;
    el("draft-script").value = draft.edited_script ?? draft.result.script;
    el("draft-notes").replaceChildren();
    const notes = [draft.snapshot.material.note, ...draft.result.notes];
    for (const note of [...new Set(notes.filter(Boolean))]) {
      const item = document.createElement("li");
      item.textContent = note;
      el("draft-notes").append(item);
    }
    el("draft-meta").textContent = `${labels[draft.status]} · ${draft.result.duration_seconds} s · ${draft.result.word_count} palabras en el borrador · ${draft.snapshot.model}`;
    message(draft.status === "reviewed" ? "Revisión guardada. El borrador original también se conserva." : "Borrador guardado. Compara cifras, atribuciones y límites con el texto de origen.");
    loadInfo();
  }

  async function poll(id, token) {
    try {
      const draft = await api(`/api/editorial/drafts/${id}`);
      showDraft(draft, token);
    } catch (error) {
      if (context !== token || !dialog.open) return;
      message(`${error.message} Puedes cerrar y volver a abrir el borrador para consultar su estado.`, "error");
      busy(false);
    }
  }

  async function openDraft(id) {
    const token = reset();
    try {
      const draft = await api(`/api/editorial/drafts/${id}`);
      if (context !== token || !dialog.open) return;
      showArticle(draft.snapshot.article);
      showMaterial(draft.snapshot.material);
      showDraft(draft, token);
    } catch (error) {
      if (context === token) message(error.message, "error");
    }
  }

  document.addEventListener("editorial:open", async (event) => {
    const token = reset();
    try {
      const data = await api(`/api/editorial/article?id=${encodeURIComponent(event.detail.articleId)}`);
      if (context !== token || !dialog.open) return;
      showArticle(data.article);
      showMaterial(data.material);
      busy(false);
      message("Revisa el material. Puedes descargar el texto de la fuente, editarlo o generar directamente con el extracto disponible.");
      if (data.drafts.length) {
        const draft = await api(`/api/editorial/drafts/${data.drafts[0].id}`);
        if (context !== token || !dialog.open) return;
        // Reopen the exact material that produced this draft, rather than a newer copy.
        showMaterial(draft.snapshot.material);
        showDraft(draft, token);
      }
    } catch (error) {
      if (context === token) message(error.message, "error");
    }
  });

  el("editorial-fetch").addEventListener("click", async () => {
    if (!articleId || pending) return;
    const token = context;
    busy(true);
    message("Descargando y extrayendo el texto de la fuente elegida…");
    try {
      const data = await api("/api/editorial/prepare", { article_id: articleId });
      if (context !== token || !dialog.open) return;
      showMaterial(data.material);
      message(data.material.note, data.material.kind === "excerpt" ? "warning" : "info");
    } catch (error) {
      if (context === token) message(error.message, "error");
    } finally {
      if (context === token && dialog.open) busy(false);
    }
  });

  el("editorial-generate").addEventListener("click", async () => {
    if (!articleId || pending) return;
    const token = context;
    busy(true, true);
    el("draft-output").hidden = true;
    message("Enviando el texto a Ollama local…");
    try {
      const draft = await api("/api/editorial/generate", { article_id: articleId, text: el("editorial-text").value });
      if (context !== token || !dialog.open) return;
      showDraft(draft, token);
      loadInfo();
    } catch (error) {
      if (context === token && dialog.open) {
        message(error.message, "error");
        busy(false);
      }
    }
  });

  el("draft-save").addEventListener("click", async () => {
    if (!draftId) return;
    const token = context;
    el("draft-save").disabled = true;
    try {
      const draft = await api(`/api/editorial/drafts/${draftId}/review`, { title: el("draft-title").value, script: el("draft-script").value });
      showDraft(draft, token);
    } catch (error) {
      if (context === token) message(error.message, "error");
    } finally {
      el("draft-save").disabled = false;
    }
  });

  el("draft-copy").addEventListener("click", async () => {
    const text = `${el("draft-title").value}\n\n${el("draft-script").value}`;
    try {
      await navigator.clipboard.writeText(text);
      message("Texto copiado.");
    } catch {
      el("draft-script").focus();
      el("draft-script").select();
      message("El navegador no permite copiar automáticamente en esta conexión. El guion está seleccionado: usa Ctrl+C.", "warning");
    }
  });

  el("editorial-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => { context += 1; clearTimeout(pollTimer); loadInfo(); });
  el("ollama-check").addEventListener("click", () => { loadInfo(); checkConnection(); });
  loadInfo();
  checkConnection();
  const initialDraft = new URLSearchParams(window.location.search).get("draft");
  if (initialDraft && /^[a-f0-9]{32}$/.test(initialDraft)) openDraft(initialDraft);
})();
