(() => {
  const el = (id) => document.getElementById(id);
  let timer;
  let voiceSignature = "";
  let library = [];
  let editingVoice = null;
  let deletingVoice = null;
  let previewUrl = null;
  let savingVoice = false;
  const jobSignatures = new Map();
  const states = { preparing: "Preparando", queued: "En cola", waiting: "Esperando turno de IA", running: "Generando", ready: "Terminado", cancelled: "Cancelado", error: "Error", purged: "Archivos eliminados · Noticia retirada de la parrilla" };
  const languages = { Spanish: "Español", English: "Inglés", French: "Francés", German: "Alemán", Italian: "Italiano", Portuguese: "Portugués", Chinese: "Chino", Japanese: "Japonés", Korean: "Coreano", Russian: "Ruso" };

  async function api(path, body) {
    const response = await fetch(path, body === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function node(tag, text, className) {
    const value = document.createElement(tag);
    value.textContent = text;
    if (className) value.className = className;
    return value;
  }

  function renderVoices(voices, force = false) {
    const signature = JSON.stringify(voices);
    library = voices;
    if (!force && signature === voiceSignature) return;
    voiceSignature = signature;
    const active = voices.filter((voice) => voice.enabled !== false);
    el("voice-count").textContent = `${voices.length} voces · ${active.length} activas · ${voices.length - active.length} desactivadas`;
    const selected = el("speech-voice").value;
    el("speech-voice").replaceChildren(new Option("Selecciona una voz", ""));
    for (const voice of active) el("speech-voice").append(new Option(voice.name, voice.id));
    if (active.some((voice) => voice.id === selected)) el("speech-voice").value = selected;
    else if (active.length) el("speech-voice").value = active[0].id;
    const query = el("voice-search").value.trim().toLocaleLowerCase("es");
    const filter = el("voice-filter").value;
    const visible = voices.filter((voice) => voice.name.toLocaleLowerCase("es").includes(query)
      && (filter === "all" || (filter === "active") === (voice.enabled !== false)));
    el("voice-list").replaceChildren();
    if (!visible.length) el("voice-list").append(node("p", voices.length ? "No hay voces que coincidan con el filtro." : "Tu biblioteca está vacía. Pulsa «Añadir voz» para subir tu primera referencia.", "hint"));
    for (const voice of visible) {
      const enabled = voice.enabled !== false;
      const item = node("article", "", `voice-item${enabled ? "" : " inactive"}`);
      const heading = node("div", "", "heading");
      heading.append(node("h3", voice.name), node("span", enabled ? "Activa" : "Desactivada", "badge"));
      item.append(heading, node("p", `${voice.duration_seconds} s · Referencia para clonación`, "hint"));
      const audio = document.createElement("audio");
      audio.controls = true;
      audio.preload = "none";
      audio.src = `/api/voices/${voice.id}/audio?v=${encodeURIComponent(voice.updated_at || "original")}`;
      const details = node("details", "");
      details.append(node("summary", "Ver transcripción"), node("p", voice.transcript, "hint"));
      const actions = node("div", "", "actions");
      const edit = node("button", "Editar", "secondary");
      edit.type = "button"; edit.addEventListener("click", () => openEditor(voice));
      const toggle = node("button", enabled ? "Desactivar" : "Activar", "secondary");
      toggle.type = "button";
      toggle.addEventListener("click", async () => {
        toggle.disabled = true;
        try {
          await api(`/api/voices/${voice.id}/update`, { enabled: !enabled });
          el("voice-message").textContent = `Voz «${voice.name}» ${enabled ? "desactivada" : "activada"}. Se aplicará a las nuevas locuciones de Qwen.`;
          await refresh();
        } catch (error) { el("voice-message").textContent = error.message; toggle.disabled = false; }
      });
      const remove = node("button", "Eliminar", "danger");
      remove.type = "button";
      remove.addEventListener("click", () => {
        deletingVoice = voice;
        el("voice-delete-description").textContent = `¿Eliminar la voz «${voice.name}»? También puedes desactivarla para conservarla sin utilizarla.`;
        el("voice-delete-message").textContent = "";
        el("voice-delete-dialog").showModal();
      });
      actions.append(edit, toggle, remove);
      item.append(audio, details, actions);
      el("voice-list").append(item);
    }
  }

  function openEditor(voice = null) {
    editingVoice = voice;
    el("voice-form").reset();
    el("voice-editor-title").textContent = voice ? `Editar «${voice.name}»` : "Añadir voz";
    el("voice-name").value = voice?.name || "";
    el("voice-transcript").value = voice?.transcript || "";
    el("voice-file").required = !voice;
    el("voice-file-label").textContent = voice ? "Sustituir muestra (opcional, 3–30 segundos, máximo 12 MiB)" : "Muestra de audio (3–30 segundos, máximo 12 MiB)";
    el("voice-editor-message").textContent = "";
    el("voice-preview").hidden = !voice;
    if (voice) el("voice-preview").src = `/api/voices/${voice.id}/audio`;
    el("voice-editor").showModal();
    el("voice-name").focus();
  }

  async function encodeAudio(file) {
    if (file.size > 12 * 1024 * 1024) throw new Error("El archivo no puede superar 12 MiB.");
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
      reader.onerror = () => reject(new Error("No se pudo leer el archivo."));
      reader.readAsDataURL(file);
    });
  }

  function renderJobs(jobs) {
    if (!jobs.length) {
      el("jobs").textContent = "Todavía no hay locuciones.";
      return;
    }
    if (!el("jobs").querySelector(".job")) el("jobs").replaceChildren();
    const visible = new Set(jobs.map((job) => `job-${job.id}`));
    for (const item of el("jobs").querySelectorAll(".job")) {
      if (!visible.has(item.id)) {
        jobSignatures.delete(item.id.slice(4));
        item.remove();
      }
    }
    for (const job of [...jobs].reverse()) {
      // Keep finished audio elements mounted while polling, so playback is uninterrupted.
      const elapsed = job.status === "running" ? Math.max(0, Math.floor((Date.now() - Date.parse(job.updated_at)) / 5000) * 5) : 0;
      const signature = JSON.stringify({ status: job.status, progress: job.progress, result: job.result, error: job.error, elapsed });
      if (jobSignatures.get(job.id) === signature) continue;
      jobSignatures.set(job.id, signature);
      const previous = document.getElementById(`job-${job.id}`);
      const item = node("article", "", "job");
      item.id = `job-${job.id}`;
      item.append(node("h3", `${job.request.voice.name} · ${new Date(job.created_at).toLocaleString("es-ES")}`));
      item.append(node("p", states[job.status] || job.status, "job-status"));
      item.append(node("p", job.request.text.slice(0, 260) + (job.request.text.length > 260 ? "…" : ""), "job-text"));
      if (job.progress && job.status === "running") item.append(node("p", `${job.progress.message || job.progress.phase} · ${elapsed} s transcurridos`, "progress"));
      if (job.error) item.append(node("p", job.error, "error hint"));
      if (job.status === "ready") {
        const result = job.result;
        item.append(node("p", `Audio: ${result.audio_seconds} s · Generación: ${result.elapsed_seconds} s · ${result.chunks || 1} fragmentos · Pico del proceso: ${result.peak_rss_mib} MiB · ${result.dtype}`, "hint"));
        const audio = document.createElement("audio");
        audio.controls = true;
        audio.preload = "none";
        audio.src = `/api/jobs/${job.id}/audio.mp3`;
        const links = node("div", "", "links");
        for (const format of ["mp3", "wav"]) {
          const link = node("a", `Descargar ${format.toUpperCase()}`);
          link.href = `/api/jobs/${job.id}/audio.${format}`;
          link.download = `locucion-${job.id}.${format}`;
          links.append(link);
        }
        item.append(audio, links);
      } else if (["queued", "waiting", "running"].includes(job.status)) {
        const button = node("button", "Cancelar", "secondary");
        button.type = "button";
        button.addEventListener("click", async () => {
          button.disabled = true;
          try { await api(`/api/jobs/${job.id}/cancel`, {}); await refresh(); }
          catch (error) { el("speech-message").textContent = error.message; button.disabled = false; }
        });
        item.append(button);
      }
      if (previous) previous.replaceWith(item);
      else el("jobs").prepend(item);
    }
  }

  async function refresh() {
    clearTimeout(timer);
    let busy = false;
    try {
      const [status, voices, jobs] = await Promise.all([api("/api/status"), api("/api/voices"), api("/api/jobs")]);
      el("service-status").textContent = status.model_ready
        ? `Modelo disponible · CPU · ${status.dtype} · ${status.threads} hilos`
        : "Modelo pendiente de descargar. Puedes preparar tus voces mientras termina la instalación.";
      el("resource-status").textContent = `${status.inference_busy ? "Turno de IA ocupado" : "Turno de IA disponible"}${status.memory_mib !== null ? ` · Servicio: ${Math.round(status.memory_mib)} MiB / ${Math.round(status.memory_limit_mib)} MiB` : ""}`;
      el("speech-create").disabled = !status.model_ready || !voices.voices.some((voice) => voice.enabled !== false);
      const selection = el("speech-language").value || "Spanish";
      el("speech-language").replaceChildren(...status.languages.map((language) => new Option(languages[language] || language, language)));
      el("speech-language").value = selection;
      renderVoices(voices.voices);
      renderJobs(jobs.jobs);
      busy = jobs.jobs.some((job) => ["queued", "waiting", "running"].includes(job.status));
    } catch (error) {
      el("service-status").textContent = error.message;
    }
    timer = setTimeout(refresh, busy ? 2500 : 15000);
  }

  el("voice-add").addEventListener("click", () => openEditor());
  el("voice-cancel").addEventListener("click", () => { if (!savingVoice) el("voice-editor").close(); });
  el("voice-editor").addEventListener("cancel", (event) => { if (savingVoice) event.preventDefault(); });
  el("voice-editor").addEventListener("close", () => {
    el("voice-preview").pause();
    el("voice-preview").removeAttribute("src");
    if (previewUrl) { URL.revokeObjectURL(previewUrl); previewUrl = null; }
  });
  el("voice-file").addEventListener("change", () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    const file = el("voice-file").files[0];
    previewUrl = file ? URL.createObjectURL(file) : null;
    el("voice-preview").hidden = !file && !editingVoice;
    el("voice-preview").src = previewUrl || (editingVoice ? `/api/voices/${editingVoice.id}/audio` : "");
  });
  for (const id of ["voice-search", "voice-filter"]) el(id).addEventListener("input", () => renderVoices(library, true));
  el("voice-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (savingVoice) return;
    savingVoice = true;
    el("voice-save").disabled = true;
    el("voice-cancel").disabled = true;
    el("voice-editor-message").textContent = "Guardando la voz…";
    try {
      const file = el("voice-file").files[0];
      const data = { name: el("voice-name").value, transcript: el("voice-transcript").value };
      if (file) data.audio_base64 = await encodeAudio(file);
      const voice = await api(editingVoice ? `/api/voices/${editingVoice.id}/update` : "/api/voices", data);
      el("voice-message").textContent = `Voz «${voice.name}» guardada.`;
      el("voice-editor").close();
      await refresh();
      if (voice.enabled !== false) el("speech-voice").value = voice.id;
    } catch (error) { el("voice-editor-message").textContent = error.message; }
    finally { savingVoice = false; el("voice-save").disabled = false; el("voice-cancel").disabled = false; }
  });
  el("voice-delete-cancel").addEventListener("click", () => el("voice-delete-dialog").close());
  el("voice-delete-dialog").addEventListener("cancel", (event) => { if (el("voice-delete-confirm").disabled) event.preventDefault(); });
  el("voice-delete-confirm").addEventListener("click", async () => {
    el("voice-delete-confirm").disabled = true;
    el("voice-delete-cancel").disabled = true;
    try {
      await api(`/api/voices/${deletingVoice.id}/delete`, {});
      el("voice-message").textContent = `Voz «${deletingVoice.name}» eliminada de la biblioteca.`;
      el("voice-delete-dialog").close();
      await refresh();
    } catch (error) { el("voice-delete-message").textContent = error.message; }
    finally { el("voice-delete-confirm").disabled = false; el("voice-delete-cancel").disabled = false; }
  });

  el("voice-import").addEventListener("click", async () => {
    el("voice-import").disabled = true;
    try {
      const result = await api("/api/voices/import", { restore_deleted: el("voice-restore").checked });
      el("voice-restore").checked = false;
      el("voice-message").textContent = `${result.imported.length} voces importadas. ${result.skipped_deleted || 0} eliminadas omitidas. ${result.errors.join(" · ")}`;
      await refresh();
    } catch (error) { el("voice-message").textContent = error.message; }
    finally { el("voice-import").disabled = false; }
  });

  el("speech-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    el("speech-create").disabled = true;
    try {
      await api("/api/jobs", { text: el("speech-text").value, voice_id: el("speech-voice").value, language: el("speech-language").value });
      el("speech-message").textContent = "Locución añadida a la cola. El resultado aparecerá debajo.";
      await refresh();
    } catch (error) { el("speech-message").textContent = error.message; }
    finally { el("speech-create").disabled = false; }
  });
  el("refresh").addEventListener("click", refresh);
  refresh();
})();
