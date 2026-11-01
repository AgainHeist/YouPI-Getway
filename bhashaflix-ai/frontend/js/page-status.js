/* Status page: live SSE progress, honest errors, real artifact links. */
(function () {
  const { el, fmtBytes, fmtClock, toast, esc } = window.BF_UI;
  const api = window.BF_API;
  const t = (k, f) => window.BF_I18N.t(k, f);

  const STAGES = ["uploading", "extracting_audio", "transcribing", "identifying_speakers", "translating", "generating_voices", "synchronizing_audio", "rendering", "completed"];
  const $ = (id) => document.getElementById(id);
  let jobId = null;
  let watcher = null;
  let startedAt = null;
  let currentJob = null;

  function stageLabel(stage) {
    return t("stage." + stage, stage.replace(/_/g, " "));
  }

  function renderStages(job) {
    const host = $("stage-list");
    host.innerHTML = "";
    const done = new Set(job.stages_done || []);
    const activeStage = job.stage;
    STAGES.forEach((stage, index) => {
      const isDone = stage === "completed" ? job.status === "completed" : done.has(stage);
      const isActive = stage === activeStage && job.status !== "completed";
      const row = el("div", { class: `step ${isDone ? "done" : ""} ${isActive ? "active" : ""}` }, [
        el("div", { class: "n", html: isDone ? "✓" : String(index + 1) }),
        el("div", {}, [
          el("div", { class: "t", text: stageLabel(stage) }),
          el("div", { class: "d", text: isActive ? `${Math.round(job.progress)}%` : isDone ? "done" : "waiting" })
        ])
      ]);
      host.appendChild(row);
    });
  }

  function renderJob(job) {
    currentJob = job;
    const badge = $("job-badge");
    const statusClass = job.status === "completed" ? "ok" : job.status === "failed" ? "err" : job.status === "awaiting_input" ? "info" : "warn";
    badge.className = "badge " + statusClass;
    badge.textContent = job.status;
    $("job-name").textContent = job.source_name || job.id;
    const media = job.media || {};
    const video = (media.video_streams || [])[0] || {};
    $("job-meta").textContent = [
      job.source_lang && job.source_lang !== "auto" ? `${job.source_lang} → ${job.target_lang}` : `auto → ${job.target_lang}`,
      video.height ? `${video.width}×${video.height}` : null,
      media.duration ? `${Math.round(media.duration)}s` : null,
      job.source_bytes ? fmtBytes(job.source_bytes) : null
    ].filter(Boolean).join(" · ");

    const pct = Math.max(0, Math.min(100, job.progress || 0));
    $("progress-value").textContent = Math.round(pct) + "%";
    $("progress-bar").style.width = pct + "%";
    $("stage-label").textContent = (job.stage_label && job.stage_label[window.BF_I18N.lang]) || stageLabel(job.stage);
    renderStages(job);

    if (job.queue) {
      $("queue-info").textContent = `${t("status.queue")}: ${job.queue.active} active · ${job.queue.queued} waiting`;
    }
    if (startedAt) {
      const secs = Math.max(0, Math.round(Date.now() / 1000 - startedAt));
      $("elapsed").textContent = `${t("status.elapsed")}: ${Math.floor(secs / 60)}m ${secs % 60}s`;
    }

    // errors
    const errorCard = $("error-card");
    if (job.status === "failed" && job.error) {
      errorCard.classList.remove("hidden");
      $("error-code").textContent = job.error.code || "ERROR";
      const isHi = window.BF_I18N.lang === "hi";
      $("error-message").textContent = (isHi && job.error.message_hi) || job.error.message || "";
      const hint = job.error.hint || "";
      $("error-hint-box").classList.toggle("hidden", !hint);
      $("error-hint").textContent = hint;
      $("fix-link").href = `/studio.html?job=${job.id}`;
    } else {
      errorCard.classList.add("hidden");
    }

    // completion
    const doneCard = $("done-card");
    if (job.status === "completed") {
      doneCard.classList.remove("hidden");
      $("player-link").href = `/player.html?job=${job.id}`;
      $("download-link").href = `/download.html?job=${job.id}`;
      renderVerification(job);
      if (watcher) { watcher.stop(); watcher = null; }
    } else {
      doneCard.classList.add("hidden");
    }
    if (job.status === "awaiting_input") {
      toast(t("status.awaiting"), "warn", 5000);
      setTimeout(() => { window.location.href = `/studio.html?job=${job.id}`; }, 1400);
    }
  }

  function renderVerification(job) {
    const host = $("verification");
    host.innerHTML = "";
    const verification = job.verification || {};
    const audio = verification.audio_level || {};
    const identical = verification.video_identical;
    host.appendChild(
      el("div", { class: "pill-note", style: identical ? "border-color:rgba(53,208,127,.4)" : "border-color:rgba(255,194,71,.4)" }, [
        el("div", {}, [
          el("b", { text: identical ? t("status.verified") : t("status.notVerified") }),
          verification.original_video_md5
            ? el("div", { class: "tiny mono", style: "margin-top:4px;word-break:break-all", text: `md5 ${verification.original_video_md5}` })
            : null
        ])
      ])
    );
    if (audio.available) {
      host.appendChild(el("div", { class: "kv tiny" }, [
        el("dt", { text: "Dialogue peak" }), el("dd", { text: `${audio.peak_db} dB` }),
        el("dt", { text: "Mean level" }), el("dd", { text: `${audio.mean_db} dB` })
      ]));
    }
    const render = (job.artifacts && job.artifacts.render) || {};
    if (render.has_dubbed) {
      host.appendChild(el("div", { class: "kv tiny" }, [
        el("dt", { text: t("download.size") }), el("dd", { text: fmtBytes(render.size_bytes) }),
        el("dt", { text: "Audio tracks" }), el("dd", { text: render.has_original_audio ? "dub + original" : "dub" })
      ]));
    }
  }

  function pushEvent(event) {
    const host = $("events");
    if (!host.dataset.rendered) { host.innerHTML = ""; host.dataset.rendered = "1"; }
    const level = event.level || "info";
    const color = level === "error" ? "var(--err)" : level === "warning" ? "var(--warn)" : "var(--muted)";
    host.appendChild(el("div", { class: "row", style: "gap:8px;align-items:flex-start;border-bottom:1px solid var(--line-soft);padding-bottom:6px" }, [
      el("span", { class: "mono", style: "color:var(--muted-2);flex:0 0 auto", text: new Date((event.ts || 0) * 1000).toLocaleTimeString() }),
      el("span", { style: `color:${color}`, text: event.message || "" })
    ]));
    if (host.childElementCount > 200) host.removeChild(host.firstChild);
    host.scrollTop = host.scrollHeight;
  }

  function renderAdvisories(job) {
    const raw = sessionStorage.getItem("bflix.advisories." + job.id);
    if (!raw) return;
    try {
      const list = JSON.parse(raw);
      list.forEach((message) => pushEvent({ message: `· ${message}`, level: "warning", ts: Date.now() / 1000 }));
    } catch (error) { /* ignore */ }
  }

  async function retry() {
    if (!jobId) return;
    try {
      const button = $("retry-btn");
      button.disabled = true;
      button.textContent = t("status.retrying");
      await api.post(`/api/jobs/${jobId}/retry`, { job_id: jobId });
      toast("Retry queued.", "ok");
      startWatch();
    } catch (error) {
      toast(api.errorText(error), "err");
    } finally {
      const button = $("retry-btn");
      button.disabled = false;
      button.textContent = t("common.retry");
    }
  }

  function startWatch() {
    if (watcher) watcher.stop();
    watcher = api.watch(jobId, {
      onProgress: (snapshot) => {
        if (snapshot.stages_done) renderJob(Object.assign({}, currentJob || {}, snapshot));
        else renderJob(snapshot);
      },
      onLog: pushEvent,
      onDone: (job) => {
        renderJob(job);
        if (job.status === "completed") toast(t("status.completed"), "ok");
        if (job.status === "failed") toast(t("status.failed"), "err");
        watcher = null;
      },
      onError: (error) => {
        if (String(error.message) === "gone") {
          toast("This project was deleted.", "warn");
          window.location.href = "/history.html";
        }
      }
    });
  }

  async function boot() {
    const params = new URLSearchParams(window.location.search);
    jobId = params.get("job") || localStorage.getItem("bflix.lastJob");
    if (!jobId) {
      window.location.href = "/upload.html";
      return;
    }
    $("copy-log").addEventListener("click", async () => {
      const text = Array.from(document.querySelectorAll("#events > div")).map((n) => n.textContent).join("\n");
      try {
        await navigator.clipboard.writeText(text);
        toast(t("common.copied"), "ok");
      } catch (error) {
        toast("Clipboard blocked by the browser.", "warn");
      }
    });
    $("retry-btn").addEventListener("click", retry);
    try {
      const job = await api.get(`/api/status/${jobId}`);
      if (job.created_at) startedAt = job.created_at;
      (job.events || []).forEach(pushEvent);
      renderAdvisories(job);
      renderJob(job);
      if (!["completed", "failed", "cancelled"].includes(job.status)) startWatch();
      if (job.status === "failed") {
        const hint = job.error && job.error.hint;
        if (hint) toast(hint, "warn", 9000);
      }
    } catch (error) {
      toast(api.errorText(error), "err", 8000);
      document.querySelector("main").appendChild(
        el("div", { class: "card", style: "margin-top:16px" }, [
          el("h3", { text: "Project not found" }),
          el("p", { class: "tiny", text: api.errorText(error) }),
          el("a", { class: "btn", href: "/history.html", text: t("nav.history") })
        ])
      );
    }
    setInterval(() => {
      if (!startedAt) return;
      const secs = Math.max(0, Math.round(Date.now() / 1000 - startedAt));
      $("elapsed").textContent = `${t("status.elapsed")}: ${Math.floor(secs / 60)}m ${secs % 60}s`;
    }, 1000);
    document.addEventListener("bflix:lang", () => currentJob && renderJob(currentJob));
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
