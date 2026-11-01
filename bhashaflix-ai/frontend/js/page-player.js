/* Player: dual-audio switching, subtitles, speed, volume, resume, fullscreen. */
(function () {
  const { el, toast, fmtClock } = window.BF_UI;
  const api = window.BF_API;
  const t = (k, f) => window.BF_I18N.t(k, f);
  const $ = (id) => document.getElementById(id);

  let jobId = null;
  let job = null;
  let track = localStorage.getItem("bflix.track") || "dubbed";
  let subtitlesOn = localStorage.getItem("bflix.subs") === "1";
  let trackElement = null;
  let lastSaved = 0;

  const video = () => $("video");

  function resumeKey() {
    return `bflix.pos.${jobId}.${track}`;
  }

  function setTrack(next, { keepTime = true } = {}) {
    track = next;
    localStorage.setItem("bflix.track", track);
    document.querySelectorAll("#track-toggle button").forEach((button) => {
      button.classList.toggle("on", button.dataset.track === track);
    });
    const node = video();
    const time = keepTime ? node.currentTime : 0;
    const playing = keepTime && !node.paused;
    node.src = api.mediaUrl(jobId, track === "original" ? "original" : "dubbed");
    node.load();
    node.addEventListener("loadedmetadata", function once() {
      node.removeEventListener("loadedmetadata", once);
      node.currentTime = time || 0;
      applySubtitles();
      if (playing) node.play().catch(() => {});
    });
  }

  function applySubtitles() {
    const node = video();
    node.querySelectorAll("track").forEach((trackNode) => trackNode.remove());
    if (!subtitlesOn) return;
    trackElement = el("track", {
      kind: "subtitles",
      label: job && job.target_lang ? `${job.target_lang} (AI dub)` : "AI dub",
      srclang: (job && job.target_lang) || "hi",
      src: api.subtitleUrl(jobId, "translated"),
      default: "default"
    });
    node.appendChild(trackElement);
    const tracks = node.textTracks;
    if (tracks && tracks.length) {
      for (let i = 0; i < tracks.length; i++) tracks[i].mode = "showing";
    }
  }

  function notices() {
    const host = $("player-notices");
    host.innerHTML = "";
    const verification = (job && job.verification) || {};
    if (verification.video_identical) {
      host.appendChild(el("div", { class: "pill-note", style: "border-color:rgba(53,208,127,.4)" }, [
        el("div", {}, [
          el("b", { text: t("status.verified") }),
          el("div", { class: "tiny mono", style: "word-break:break-all", text: `md5 ${verification.original_video_md5}` })
        ])
      ]));
    }
    const sync = (job && job.artifacts && job.artifacts.sync) || {};
    (sync.warnings || []).slice(0, 3).forEach((message) => {
      host.appendChild(el("div", { class: "pill-note", style: "border-color:rgba(255,194,71,.4)" }, [
        el("span", { class: "tiny", text: message })
      ]));
    });
    const renderWarnings = (job && job.artifacts && job.artifacts.render && job.artifacts.render.warnings) || [];
    renderWarnings.slice(0, 2).forEach((message) => {
      host.appendChild(el("div", { class: "pill-note" }, [el("span", { class: "tiny", text: message })]));
    });
  }

  async function loadJobs() {
    const picker = $("job-picker");
    try {
      const data = await api.get("/api/jobs", { limit: 50, status_filter: "completed" });
      picker.innerHTML = "";
      if (!data.jobs.length) return;
      data.jobs.forEach((item) => {
        const option = el("option", { value: item.id, text: `${item.source_name || item.id} · ${item.target_lang}` });
        picker.appendChild(option);
      });
      if (jobId) picker.value = jobId;
    } catch (error) { /* handled by caller */ }
  }

  async function boot() {
    const params = new URLSearchParams(window.location.search);
    jobId = params.get("job") || localStorage.getItem("bflix.lastJob");
    await loadJobs();
    if (!jobId) {
      $("empty-card").classList.remove("hidden");
      return;
    }
    $("job-picker").addEventListener("change", (event) => {
      window.location.href = `/player.html?job=${event.target.value}`;
    });
    try {
      job = await api.get(`/api/status/${jobId}`);
    } catch (error) {
      toast(api.errorText(error), "err");
      $("empty-card").classList.remove("hidden");
      return;
    }
    if (!job.artifacts || !job.artifacts.render || !job.artifacts.render.has_dubbed) {
      $("empty-card").classList.remove("hidden");
      $("empty-card").innerHTML = "";
      $("empty-card").append(
        el("p", { text: t("player.noJob") }),
        el("a", { class: "btn primary", href: `/status.html?job=${jobId}`, text: t("nav.status") })
      );
      return;
    }

    $("empty-card").classList.add("hidden");
    $("player-wrap").classList.remove("hidden");
    $("player-title").textContent = job.source_name || job.id;
    const media = job.media || {};
    $("player-meta").textContent = [
      `${job.source_lang || "auto"} → ${job.target_lang}`,
      media.duration ? `${Math.floor(media.duration / 60)}m ${Math.round(media.duration % 60)}s` : null,
      fmtClock(job.created_at)
    ].filter(Boolean).join(" · ");
    $("download-link").href = `/download.html?job=${jobId}`;
    notices();

    document.querySelectorAll("#track-toggle button").forEach((button) => {
      button.classList.toggle("on", button.dataset.track === track);
      button.addEventListener("click", () => setTrack(button.dataset.track));
    });

    $("subs-btn").addEventListener("click", () => {
      subtitlesOn = !subtitlesOn;
      localStorage.setItem("bflix.subs", subtitlesOn ? "1" : "0");
      applySubtitles();
      toast(subtitlesOn ? "Subtitles on" : "Subtitles off", "ok", 1500);
    });

    $("speed").addEventListener("change", (event) => {
      video().playbackRate = Number(event.target.value);
    });
    $("volume").addEventListener("input", (event) => {
      video().volume = Number(event.target.value);
    });
    $("fullscreen-btn").addEventListener("click", () => {
      const node = video();
      if (document.fullscreenElement) document.exitFullscreen();
      else if (node.requestFullscreen) node.requestFullscreen();
      else if (node.webkitEnterFullscreen) node.webkitEnterFullscreen();
    });

    const node = video();
    node.src = api.mediaUrl(jobId, track);
    node.addEventListener("error", () => {
      toast(t("player.missing"), "err", 9000);
    });
    node.addEventListener("loadedmetadata", () => {
      const saved = Number(localStorage.getItem(resumeKey()) || 0);
      if (saved > 3 && saved < (node.duration || Infinity) - 3) {
        node.currentTime = saved;
        toast(t("player.resume") + ` (${Math.floor(saved)}s)`, "ok", 3200);
      }
      applySubtitles();
    });
    node.addEventListener("timeupdate", () => {
      const now = Date.now();
      if (now - lastSaved > 4000) {
        lastSaved = now;
        if (node.currentTime > 0) localStorage.setItem(resumeKey(), String(node.currentTime));
      }
    });
    node.addEventListener("ended", () => localStorage.removeItem(resumeKey()));

    document.addEventListener("bflix:lang", notices);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
