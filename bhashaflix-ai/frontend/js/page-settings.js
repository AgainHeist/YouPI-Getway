/* Settings: browser-side preferences + live server capability report. */
(function () {
  const { el, toast, fmtBytes } = window.BF_UI;
  const api = window.BF_API;
  const t = (k, f) => window.BF_I18N.t(k, f);
  const $ = (id) => document.getElementById(id);

  async function loadLanguages() {
    try {
      const data = await api.get("/api/languages");
      const select = $("default-target");
      select.innerHTML = "";
      data.languages.filter((lang) => lang.target).forEach((lang) => {
        select.appendChild(el("option", { value: lang.code, text: `${lang.native} — ${lang.en}` }));
      });
      select.value = api.store.target || "hi";
    } catch (error) { /* server info shows the failure */ }
  }

  function engineLine(name, engines) {
    const ok = (engines || []).filter((engine) => engine.available);
    return el("div", { class: "row between" }, [
      el("span", { class: "muted", text: name }),
      el("span", { class: "badge " + (ok.length ? "ok" : "warn"), text: ok.length ? ok.map((e) => e.engine).join(", ") : "none" })
    ]);
  }

  async function loadServer() {
    const info = $("server-info");
    const caps = $("caps");
    try {
      const health = await api.get("/api/health");
      const config = await api.get("/api/config");
      info.innerHTML = "";
      info.appendChild(el("div", { class: "kv" }, [
        el("dt", { text: "Instance" }), el("dd", { class: "mono", text: health.instance }),
        el("dt", { text: "FFmpeg" }), el("dd", { class: "mono", text: health.ffmpeg ? "ready" : "missing" }),
        el("dt", { text: "Probe" }), el("dd", { text: health.ffprobe ? "ffprobe" : "PyAV fallback" }),
        el("dt", { text: "GPU" }), el("dd", { text: health.gpu ? "available" : "CPU only" }),
        el("dt", { text: "Upload limit" }), el("dd", { text: config.max_upload_mb + " MB" }),
        el("dt", { text: "Max duration" }), el("dd", { text: Math.round(config.max_duration_sec / 60) + " min" }),
        el("dt", { text: "Retention" }), el("dd", { text: config.retention_hours + " h" }),
        el("dt", { text: "Token required" }), el("dd", { text: config.auth_required ? t("common.yes") : t("common.no") }),
        el("dt", { text: "Queue" }), el("dd", { text: `${health.queue.active} active / ${health.queue.queued} waiting` }),
        el("dt", { text: "Storage" }), el("dd", { text: fmtBytes(health.queue.storage_bytes) })
      ]));
      const capabilities = await api.get("/api/capabilities");
      caps.innerHTML = "";
      caps.appendChild(engineLine("Speech recognition", capabilities.asr));
      caps.appendChild(engineLine("Speaker ID", capabilities.diarize));
      caps.appendChild(engineLine("Translation", capabilities.translate));
      caps.appendChild(engineLine("Voices", capabilities.tts));
      caps.appendChild(engineLine("Separation", capabilities.separate));
      (capabilities.notes || []).forEach((note) => {
        caps.appendChild(el("div", { class: "pill-note tiny", text: note }));
      });
    } catch (error) {
      info.innerHTML = "";
      info.appendChild(el("div", { class: "pill-note" }, [
        el("b", { text: api.errorText(error) }),
        el("div", { class: "tiny", text: "Set the backend URL above if the worker runs elsewhere." })
      ]));
    }
  }

  function save() {
    api.store.backend = $("backend").value.trim();
    api.store.token = $("token").value.trim();
    api.store.target = $("default-target").value;
    api.store.mode = $("default-mode").value;
    toast(t("common.saved"), "ok");
    loadServer();
  }

  function boot() {
    $("backend").value = api.store.backend;
    $("token").value = api.store.token;
    $("default-mode").value = api.store.mode;
    $("save-settings").addEventListener("click", save);
    document.querySelectorAll("[data-set-lang]").forEach((button) => {
      button.addEventListener("click", () => window.BF_I18N.setLang(button.dataset.setLang));
    });
    $("clear-data").addEventListener("click", () => {
      ["bflix.lang", "bflix.backend", "bflix.token", "bflix.target", "bflix.mode", "bflix.lastJob", "bflix.track", "bflix.subs"].forEach((key) => localStorage.removeItem(key));
      Object.keys(localStorage).filter((key) => key.startsWith("bflix.pos.")).forEach((key) => localStorage.removeItem(key));
      toast(t("settings.cleared"), "ok");
      setTimeout(() => window.location.reload(), 700);
    });
    loadLanguages();
    loadServer();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
