/* Download page: real artifacts only, with honest size and verification info. */
(function () {
  const { el, fmtBytes, fmtClock, toast } = window.BF_UI;
  const api = window.BF_API;
  const t = (k, f) => window.BF_I18N.t(k, f);
  const $ = (id) => document.getElementById(id);

  let jobId = null;
  let job = null;
  let config = null;

  const ITEMS = [
    { kind: "dubbed", label: "download.video", icon: "🎬", ext: ".mp4" },
    { kind: "original_audio", label: "download.originalAudio", icon: "🔊", ext: ".mp4" },
    { kind: "mkv", label: "download.multitrack", icon: "📦", ext: ".mkv" },
    { kind: "audio_only", label: "download.audio", icon: "🎧", ext: ".m4a" },
    { kind: "subtitle_translated", label: "download.subs", icon: "💬", ext: ".srt" },
    { kind: "subtitle_source", label: "download.subsSrc", icon: "📝", ext: ".srt" }
  ];

  function availability() {
    const render = (job && job.artifacts && job.artifacts.render) || {};
    return {
      dubbed: render.has_dubbed,
      original_audio: render.has_original_audio,
      mkv: render.has_mkv,
      audio_only: render.has_audio_only,
      subtitle_translated: render.has_subtitles,
      subtitle_source: render.has_subtitles
    };
  }

  function render() {
    $("empty-card").classList.add("hidden");
    $("download-wrap").classList.remove("hidden");
    $("dl-title").textContent = job.source_name || job.id;
    const media = job.media || {};
    $("dl-meta").textContent = [
      `${job.source_lang || "auto"} → ${job.target_lang}`,
      media.duration ? `${Math.round(media.duration)}s` : null,
      fmtClock(job.created_at)
    ].filter(Boolean).join(" · ");

    const verify = job.verification || {};
    const badge = $("dl-badge");
    badge.className = "badge " + (verify.video_identical ? "ok" : "warn");
    badge.textContent = verify.video_identical ? t("status.verified") : t("status.notVerified");

    const host = $("dl-items");
    host.innerHTML = "";
    const avail = availability();
    let count = 0;
    ITEMS.forEach((item) => {
      if (!avail[item.kind]) return;
      count += 1;
      const size = item.kind === "dubbed" ? fmtBytes(((job.artifacts.render || {}).size_bytes)) : null;
      host.appendChild(
        el("div", { class: "job-card" }, [
          el("div", { class: "row" }, [
            el("span", { text: item.icon, style: "font-size:1.3rem" }),
            el("div", {}, [
              el("div", { class: "title", text: t(item.label, item.label) }),
              el("div", { class: "meta", text: [item.ext, size].filter(Boolean).join(" · ") })
            ])
          ]),
          el("a", {
            class: "btn sm primary",
            href: api.downloadUrl(jobId, item.kind),
            text: t("common.download")
          })
        ])
      );
    });
    if (!count) {
      host.appendChild(el("div", { class: "pill-note" }, [
        el("span", { text: t("download.notReady") }),
        el("a", { class: "btn sm", href: `/status.html?job=${jobId}`, text: t("nav.status") })
      ]));
    }

    const verifyHost = $("dl-verify");
    verifyHost.innerHTML = "";
    verifyHost.appendChild(el("div", { class: "kv" }, [
      el("dt", { text: "Original video md5" }), el("dd", { class: "mono", text: verify.original_video_md5 || "—" }),
      el("dt", { text: "Rendered video md5" }), el("dd", { class: "mono", text: verify.rendered_video_md5 || "—" }),
      el("dt", { text: "Identical" }), el("dd", { text: verify.video_identical ? t("common.yes") : t("common.no") }),
      el("dt", { text: "Dialogue peak" }), el("dd", { text: ((verify.audio_level || {}).peak_db ?? "—") + " dB" })
    ]));

    const retention = config ? config.retention_hours : 24;
    $("retention-note").textContent = `${t("download.retention")} ${retention}h (${t("history.title")} → ${t("common.delete")}).`;
  }

  async function boot() {
    const params = new URLSearchParams(window.location.search);
    jobId = params.get("job") || localStorage.getItem("bflix.lastJob");
    try {
      config = await api.get("/api/config");
      const data = await api.get("/api/jobs", { limit: 50, status_filter: "completed" });
      const picker = $("job-picker");
      picker.innerHTML = "";
      data.jobs.forEach((item) => {
        const option = el("option", { value: item.id, text: `${item.source_name || item.id} · ${item.target_lang}` });
        picker.appendChild(option);
      });
      if (jobId) picker.value = jobId;
      picker.addEventListener("change", (event) => { window.location.href = `/download.html?job=${event.target.value}`; });
    } catch (error) {
      toast(api.errorText(error), "err");
    }
    if (!jobId) {
      $("empty-card").classList.remove("hidden");
      return;
    }
    try {
      job = await api.get(`/api/status/${jobId}`);
    } catch (error) {
      toast(api.errorText(error), "err");
      $("empty-card").classList.remove("hidden");
      return;
    }
    if (!job.artifacts || !job.artifacts.render) {
      $("download-wrap").classList.add("hidden");
      $("empty-card").classList.remove("hidden");
      return;
    }
    render();
    document.addEventListener("bflix:lang", render);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
