(() => {
  const el = (id) => document.getElementById(id);
  let timer;
  let voiceSignature = "";
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

  function renderVoices(voices) {
    const signature = JSON.stringify(voices);
    if (signature === voiceSignature) return;
    voiceSignature = signature;
    const selected = el("speech-voice").value;
    el("speech-voice").replaceChildren(new Option("Selecciona una voz", ""));
    el("voice-list").replaceChildren();
    for (const voice of voices) {
      el("speech-voice").append(new Option(voice.name, voice.id));
      const item = node("article", "", "voice-item");
      item.append(node("h3", voice.name), node("p", `${voice.duration_seconds} s · ${voice.transcript}`, "hint"));
      const audio = document.createElement("audio");
      audio.controls = true;
      audio.preload = "none";
      audio.src = `/api/voices/${voice.id}/audio`;
      item.append(audio);
      el("voice-list").append(item);
    }
    if (voices.some((voice) => voice.id === selected)) el("speech-voice").value = selected;
    else if (voices.length) el("speech-voice").value = voices[0].id;
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
      el("speech-create").disabled = !status.model_ready || !voices.voices.length;
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

  el("voice-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = el("voice-file").files[0];
    if (!file) return;
    if (file.size > 12 * 1024 * 1024) { el("voice-message").textContent = "El archivo no puede superar 12 MiB."; return; }
    el("voice-save").disabled = true;
    el("voice-message").textContent = "Guardando la voz…";
    try {
      const encoded = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
      const voice = await api("/api/voices", { name: el("voice-name").value, transcript: el("voice-transcript").value, audio_base64: encoded });
      el("voice-message").textContent = `Voz «${voice.name}» guardada.`;
      el("voice-form").reset();
      await refresh();
      el("speech-voice").value = voice.id;
    } catch (error) { el("voice-message").textContent = error.message; }
    finally { el("voice-save").disabled = false; }
  });

  el("voice-import").addEventListener("click", async () => {
    el("voice-import").disabled = true;
    try {
      const result = await api("/api/voices/import", {});
      el("voice-message").textContent = `${result.imported.length} voces importadas. ${result.errors.join(" · ")}`;
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
