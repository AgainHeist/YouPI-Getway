/* Home page: honest capability report + recent projects. */
(function () {
  const { el, icon, toast, esc, fmtClock } = window.BF_UI;
  const api = window.BF_API;
  const t = (k, f) => window.BF_I18N.t(k, f);

  const STAGES = [
    ["uploading", "Upload stored, original never modified"],
    ["extracting_audio", "FFprobe/FFmpeg inspect the file and extract audio"],
    ["transcribing", "Whisper-class speech recognition with timestamps"],
    ["identifying_speakers", "Speaker diarization, consistent IDs across the movie"],
    ["translating", "Meaning, emotion and timing preserved"],
    ["generating_voices", "One consistent voice per speaker, previewable"],
    ["synchronizing_audio", "Dialogue fitted to original timestamps, no overlap"],
    ["rendering", "Original video stream copied, new audio muxed"],
    ["completed", "Fingerprint check + playback + download"]
  ];

  function renderStages() {
    const host = document.getElementById("stage-list");
    if (!host) return;
    host.innerHTML = "";
    STAGES.forEach(([key, detail], index) => {
      host.appendChild(
        el("div", { class: "step" }, [
          el("div", { class: "n", text: String(index + 1) }),
          el("div", {}, [
            el("div", { class: "t", text: t(`stage.${key}`, key.replace(/_/g, " ")) }),
            el("div", { class: "d", text: detail })
          ])
        ])
      );
    });
  }

  function engineRow(title, engines) {
    const installed = (engines || []).filter((e) => e.available);
    const missing = (engines || []).filter((e) => !e.available);
    return el("div", {}, [
      el("div", { class: "row between", style: "margin-bottom:6px" }, [
        el("span", { class: "tiny muted", text: title }),
        el("span", {
          class: `badge ${installed.length ? "ok" : "warn"}`,
          text: installed.length ? installed.map((e) => e.engine).join(", ") : "not installed"
        })
      ]),
      missing.length
        ? el("div", {
            class: "tiny",
            style: "color: var(--muted-2)",
            text: missing.map((e) => `${e.engine}: ${e.reason}`).join(" · ")
          })
        : null
    ]);
  }

  async function loadCapabilities() {
    const host = document.getElementById("capabilities");
    try {
      const caps = await api.get("/api/capabilities");
      host.innerHTML = "";
      host.appendChild(engineRow("Speech recognition", caps.asr));
      host.appendChild(engineRow("Speaker ID", caps.diarize));
      host.appendChild(engineRow("Translation", caps.translate));
      host.appendChild(engineRow("Voices (TTS)", caps.tts));
      host.appendChild(engineRow("Background separation", caps.separate));
      host.appendChild(
        el("div", { class: "pill-note tiny", style: "margin-top:8px" }, [
          el("span", { html: icon("shield", "ic-inline") + " " }),
          el("span", { text: "Missing a model? Every step either works or tells you why — no fake success." })
        ])
      );
      if (caps.gpu) {
        host.appendChild(el("span", { class: "badge info", text: "GPU available" }));
      } else {
        host.appendChild(el("span", { class: "badge", text: "CPU only" }));
      }
    } catch (error) {
      host.innerHTML = "";
      host.appendChild(el("div", { class: "pill-note tiny" }, [
        el("b", { text: "Backend unreachable. " }),
        el("span", { text: api.errorText(error) })
      ]));
    }
  }

  async function loadRecent() {
    const host = document.getElementById("recent");
    try {
      const data = await api.get("/api/jobs", { limit: 6 });
      host.innerHTML = "";
      if (!data.jobs.length) {
        host.appendChild(el("div", { class: "pill-note" }, [
          el("span", { text: t("home.recent.empty") }),
          el("a", { href: "/upload.html", text: t("nav.upload"), style: "margin-left:auto" })
        ]));
        return;
      }
      data.jobs.slice(0, 5).forEach((job) => {
        const badge = job.status === "completed" ? "ok" : job.status === "failed" ? "err" : job.status === "awaiting_input" ? "info" : "warn";
        host.appendChild(
          el("div", { class: "job-card" }, [
            el("div", {}, [
              el("div", { class: "title", text: job.source_name || job.id }),
              el("div", { class: "meta" }, [
                el("span", { text: fmtClock(job.created_at) }),
                el("span", { text: `${job.source_lang || "auto"} → ${job.target_lang}` }),
                el("span", { text: `${Math.round(job.progress)}%` })
              ])
            ]),
            el("div", { class: "row" }, [
              el("span", { class: `badge ${badge}`, text: (job.stage_label && job.stage_label[window.BF_I18N.lang]) || job.stage }),
              el("a", { class: "btn sm", href: job.status === "completed" ? `/player.html?job=${job.id}` : `/status.html?job=${job.id}`, text: job.status === "completed" ? "Play" : "Open" })
            ])
          ])
        );
      });
    } catch (error) {
      host.innerHTML = "";
      host.appendChild(el("div", { class: "pill-note", text: api.errorText(error) }));
    }
  }

  async function loadConfig() {
    try {
      const config = await api.get("/api/config");
      const note = document.getElementById("retention-note");
      if (note) {
        note.textContent = `Uploads up to ${config.max_upload_mb} MB · ${Math.round(config.max_duration_sec / 60)} min per job · deleted after ${config.retention_hours}h`;
      }
    } catch (error) {
      /* the capabilities card already shows the connection error */
    }
  }

  function boot() {
    document.getElementById("ic-video").innerHTML = icon("film");
    document.getElementById("ic-audio").innerHTML = icon("mic");
    document.getElementById("ic-budget").innerHTML = icon("warn");
    renderStages();
    loadCapabilities();
    loadRecent();
    loadConfig();
    window.BF_I18N.apply();
    document.addEventListener("bflix:lang", () => {
      renderStages();
      loadCapabilities();
      loadRecent();
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
