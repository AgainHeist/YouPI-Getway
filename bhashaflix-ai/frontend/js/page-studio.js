/* Studio: edit dialogue, fix speakers, pick and preview voices, run stages. */
(function () {
  const { el, toast, fmtClock, esc } = window.BF_UI;
  const api = window.BF_API;
  const t = (k, f) => window.BF_I18N.t(k, f);
  const $ = (id) => document.getElementById(id);

  let jobId = null;
  let job = null;
  let segments = [];
  let voicesByLang = {};
  let pollTimer = null;
  let audioPlayer = null;

  function speakerVoices() {
    const speakers = (job && job.speakers) || [];
    const map = {};
    speakers.forEach((s) => { map[s.id] = s; });
    segments.forEach((s) => {
      if (!map[s.speaker]) map[s.speaker] = { id: s.speaker, label: s.speaker, gender: "unknown", voice: "" };
    });
    return Object.values(map).sort((a, b) => a.id.localeCompare(b.id));
  }

  function notices() {
    const host = $("notices");
    host.innerHTML = "";
    const items = [];
    const artifacts = (job && job.artifacts) || {};
    if (artifacts.diarization && artifacts.diarization.warnings) {
      artifacts.diarization.warnings.forEach((message) => items.push({ level: "warn", message }));
    }
    if (artifacts.sync && artifacts.sync.warnings) {
      artifacts.sync.warnings.forEach((message) => items.push({ level: "warn", message }));
    }
    if (artifacts.render && artifacts.render.warnings) {
      artifacts.render.warnings.forEach((message) => items.push({ level: "warn", message }));
    }
    ((job && job.notes) || []).forEach((note) => {
      if (note && note.message) items.push({ level: note.kind === "warning" ? "warn" : "info", message: note.message });
    });
    if (job && job.error) {
      items.push({ level: "err", message: `${job.error.code}: ${job.error.message}${job.error.hint ? " — " + job.error.hint : ""}` });
    }
    const seen = new Set();
    items.filter((item) => {
      if (seen.has(item.message)) return false;
      seen.add(item.message);
      return true;
    }).slice(0, 8).forEach((item) => {
      const color = item.level === "err" ? "rgba(255,84,112,.45)" : item.level === "warn" ? "rgba(255,194,71,.4)" : "var(--line)";
      host.appendChild(el("div", { class: "pill-note", style: `border-color:${color}` }, [
        el("span", { class: "tiny", text: item.message })
      ]));
    });
  }

  function renderHeader() {
    $("studio-job-name").textContent = job.source_name || job.id;
    const media = job.media || {};
    $("studio-job-meta").textContent = [
      `${job.source_lang || "auto"} → ${job.target_lang}`,
      media.duration ? `${Math.round(media.duration)}s` : null,
      fmtClock(job.created_at)
    ].filter(Boolean).join(" · ");
    const badge = $("studio-badge");
    badge.className = "badge " + (job.status === "completed" ? "ok" : job.status === "failed" ? "err" : "warn");
    badge.textContent = job.status === "awaiting_input" ? "awaiting review" : job.status;
    $("studio-progress").style.width = Math.max(0, Math.min(100, job.progress || 0)) + "%";
    $("line-count").textContent = `${segments.length} ${t("studio.lines")}`;
    $("speaker-count").textContent = `${speakerVoices().length} speakers`;
  }

  function renderSpeakers() {
    const host = $("speakers");
    host.innerHTML = "";
    const speakers = speakerVoices();
    if (!speakers.length) {
      host.appendChild(el("p", { class: "tiny muted", text: "Run speaker identification, or set a speaker on any line." }));
      return;
    }
    const allVoices = voicesByLang[job.target_lang] || [];
    speakers.forEach((speaker) => {
      const select = el("select", { style: "max-width:280px" });
      allVoices.forEach((voice) => {
        const option = el("option", {
          value: voice.id,
          text: `${voice.label} · ${voice.gender} (${voice.engine})`
        });
        if (voice.id === speaker.voice) option.selected = true;
        select.appendChild(option);
      });
      if (!allVoices.length) select.appendChild(el("option", { text: "no voices installed for this language" }));
      select.addEventListener("change", () => setVoice(speaker.id, select.value));
      const preview = el("button", { class: "btn sm ghost", text: "▶ " + t("lang.preview") });
      preview.addEventListener("click", () => previewVoice(select.value, sampleTextFor(speaker.id)));
      host.appendChild(
        el("div", { class: "row between", style: "border-bottom:1px solid var(--line-soft);padding-bottom:10px" }, [
          el("div", {}, [
            el("div", { class: "speaker-chip", text: speaker.label || speaker.id }),
            el("div", { class: "tiny muted", text: `${segments.filter((s) => s.speaker === speaker.id).length} lines · ${speaker.gender || "unknown"}${speaker.pitch_hz ? " · " + speaker.pitch_hz + " Hz" : ""}` })
          ]),
          el("div", { class: "row" }, [select, preview])
        ])
      );
    });
  }

  function sampleTextFor(speakerId) {
    const line = segments.find((s) => s.speaker === speakerId && (s.translated_text || "").trim());
    return (line && line.translated_text.slice(0, 160)) || "नमस्ते, यह आवाज़ का नमूना है।";
  }

  function renderSegments() {
    const host = $("segments");
    host.innerHTML = "";
    if (!segments.length) {
      host.appendChild(el("div", { class: "pill-note" }, [
        el("span", { text: "No dialogue yet. Import subtitles, type your own lines, or run speech recognition." }),
        el("button", { class: "btn sm", text: "Add line", onclick: () => addLine() })
      ]));
      return;
    }
    segments.forEach((segment, index) => {
      const textarea = el("textarea", { rows: "2", spellcheck: "false" });
      textarea.value = segment.translated_text || "";
      textarea.placeholder = segment.text || "—";
      textarea.addEventListener("input", () => { segment.translated_text = textarea.value; segment.dirty = true; });
      const speakerSelect = el("select", { style: "margin-top:6px" });
      speakerVoices().forEach((speaker) => {
        const option = el("option", { value: speaker.id, text: speaker.label || speaker.id });
        if (speaker.id === segment.speaker) option.selected = true;
        speakerSelect.appendChild(option);
      });
      speakerSelect.addEventListener("change", () => { segment.speaker = speakerSelect.value; segment.dirty = true; });
      const flags = (segment.flags || []).filter((flag) => !flag.startsWith("voice:"));
      const wrapper = el("div", { class: `seg ${flags.length ? "flagged" : ""}` }, [
        el("div", { class: "time" }, [
          el("div", { text: `${segment.start.toFixed(2)}s` }),
          el("div", { text: `${segment.end.toFixed(2)}s` }),
          el("div", { style: "opacity:.7", text: `#${index + 1}` })
        ]),
        el("div", {}, [
          textarea,
          el("div", { class: "orig", text: segment.text || "—" }),
          flags.length ? el("div", { class: "flags" }, flags.map((flag) => el("span", { class: "flag", text: flag }))) : null
        ]),
        el("div", {}, [
          speakerSelect,
          segment.tts_duration
            ? el("div", { class: "tiny muted", style: "margin-top:6px", text: `voice ${segment.tts_duration.toFixed(2)}s → ${segment.start.toFixed(2)}–${segment.end.toFixed(2)}s (${(segment.tempo || 1).toFixed(2)}×)` })
            : el("div", { class: "tiny muted", style: "margin-top:6px", text: "no audio yet" })
        ])
      ]);
      host.appendChild(wrapper);
    });
    host.appendChild(el("div", { class: "row" }, [
      el("button", { class: "btn sm ghost", text: "+ Add line", onclick: () => addLine() })
    ]));
  }

  function addLine() {
    const last = segments[segments.length - 1];
    const start = last ? last.end + 0.2 : 0.2;
    segments.push({
      id: segments.length,
      start: Number(start.toFixed(2)),
      end: Number((start + 1.6).toFixed(2)),
      text: "",
      translated_text: "",
      speaker: last ? last.speaker : "SPEAKER_01",
      flags: [],
      dirty: true
    });
    renderSegments();
    renderHeader();
  }

  async function setVoice(speakerId, voice) {
    try {
      const speakers = await api.post(`/api/jobs/${jobId}/voices`, [{ speaker: speakerId, voice }]);
      job.speakers = speakers.speakers;
      toast(`${t("studio.voiceFor")} ${speakerId}: ${voice}`, "ok", 2600);
      renderSpeakers();
    } catch (error) {
      toast(api.errorText(error), "err");
    }
  }

  async function previewVoice(voice, text) {
    if (!voice) {
      toast("No voice installed for this language.", "warn");
      return;
    }
    try {
      const headers = { "Content-Type": "application/json" };
      if (api.store.token) headers["X-API-Token"] = api.store.token;
      const response = await fetch(api.url("/api/voice-preview"), {
        method: "POST",
        headers,
        body: JSON.stringify({ text: text.slice(0, 300), lang: job.target_lang, voice })
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw (payload && payload.error) || { message: "Preview failed" };
      }
      const blob = await response.blob();
      if (audioPlayer) { audioPlayer.pause(); }
      audioPlayer = new Audio(URL.createObjectURL(blob));
      await audioPlayer.play();
      toast("Playing preview…", "ok", 1800);
    } catch (error) {
      toast(api.errorText(error), "err");
    }
  }

  async function saveDialogue() {
    const payload = segments.map((segment, index) => ({
      start: segment.start,
      end: segment.end,
      text: segment.text || "",
      translated_text: segment.translated_text || "",
      speaker: segment.speaker || "SPEAKER_01",
      id: index
    }));
    try {
      const result = await api.put(`/api/jobs/${jobId}/segments`, { segments: payload });
      segments = result.segments.map((segment) => Object.assign({}, segment, { dirty: false }));
      renderSegments();
      renderHeader();
      toast(t("studio.edited") + " — " + t("studio.regenerate"), "ok", 5000);
    } catch (error) {
      toast(api.errorText(error), "err");
    }
  }

  async function loadVoices(lang) {
    try {
      const data = await api.get("/api/voices", { lang });
      voicesByLang[lang] = (data.catalog && data.catalog[lang]) || [];
    } catch (error) {
      voicesByLang[lang] = [];
    }
    return voicesByLang[lang];
  }

  async function refresh() {
    try {
      job = await api.get(`/api/status/${jobId}`);
      const data = await api.get(`/api/jobs/${jobId}/segments`);
      segments = data.segments;
      if (!voicesByLang[job.target_lang]) await loadVoices(job.target_lang);
      $("empty-card").classList.add("hidden");
      $("studio").classList.remove("hidden");
      renderHeader();
      notices();
      renderSpeakers();
      renderSegments();
      if (["queued", "running"].includes(job.status)) {
        startPolling();
      } else {
        stopPolling();
      }
    } catch (error) {
      $("empty-card").classList.remove("hidden");
      $("studio").classList.add("hidden");
      toast(api.errorText(error), "err");
    }
  }

  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(async () => {
      try {
        const snapshot = await api.get(`/api/status/${jobId}`);
        job = Object.assign(job || {}, snapshot);
        $("studio-progress").style.width = Math.max(0, Math.min(100, job.progress || 0)) + "%";
        $("studio-badge").textContent = job.status;
        if (!["queued", "running"].includes(job.status)) {
          stopPolling();
          refresh();
          if (job.status === "failed") toast(api.errorText({ payload: job.error }), "err", 8000);
          if (job.status === "completed") toast(t("status.completed"), "ok");
        }
      } catch (error) {
        stopPolling();
      }
    }, 1800);
  }

  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }

  async function runStage(stage) {
    const hasUnsaved = segments.some((segment) => segment.dirty);
    if (hasUnsaved) await saveDialogue();
    const endpoint = {
      transcribe: "/api/transcribe",
      speakers: "/api/speakers",
      translate: "/api/translate",
      "generate-voice": "/api/generate-voice",
      render: "/api/render"
    }[stage];
    try {
      const needsForce = ["translate", "generate-voice", "render", "transcribe", "speakers"].includes(stage);
      await api.post(endpoint, { job_id: jobId, force: needsForce });
      toast(`${stage} queued…`, "ok", 2200);
      startPolling();
    } catch (error) {
      toast(api.errorText(error), "err");
    }
  }

  async function importSubtitles(file) {
    const text = await file.text();
    const cues = [];
    const blocks = text.replace(/\r\n/g, "\n").split(/\n{2,}/);
    const stamp = /(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})/;
    blocks.forEach((block) => {
      const match = block.match(stamp);
      if (!match) return;
      const toSec = (h, m, s, ms) => Number(h) * 3600 + Number(m) * 60 + Number(s) + Number(ms.padEnd(3, "0")) / 1000;
      const body = block.split("\n").filter((line) => !stamp.test(line) && !/^\d+$/.test(line.trim()) && !/^WEBVTT/.test(line)).join(" ").replace(/<[^>]+>/g, "").trim();
      if (!body) return;
      // Decide whether this file is a source or a translated transcript by script.
      const targetScript = /[\u0900-\u097F\u0980-\u09FF\u0A80-\u0BFF\u0C00-\u0CFF\u0D00-\u0D7F\u0600-\u06FF\u3040-\u30FF\uAC00-\uD7AF]/;
      const isTargetScript = targetScript.test(body);
      cues.push({
        start: toSec(match[1], match[2], match[3], match[4]),
        end: toSec(match[5], match[6], match[7], match[8]),
        text: isTargetScript ? "" : body,
        translated_text: isTargetScript ? body : "",
        speaker: "SPEAKER_01",
        flags: [],
        dirty: true
      });
    });
    if (!cues.length) {
      toast("No subtitle cues found in that file.", "warn");
      return;
    }
    segments = cues;
    renderSegments();
    renderHeader();
    toast(`${cues.length} lines loaded from ${file.name}. Review and save.`, "ok", 5000);
  }

  async function loadJobs() {
    const picker = $("job-picker");
    try {
      const data = await api.get("/api/jobs", { limit: 40 });
      picker.innerHTML = "";
      data.jobs.forEach((item) => {
        const option = el("option", { value: item.id, text: `${item.source_name || item.id} · ${item.target_lang} · ${item.status}` });
        picker.appendChild(option);
      });
      if (jobId) picker.value = jobId;
    } catch (error) {
      /* reported elsewhere */
    }
  }

  async function boot() {
    const params = new URLSearchParams(window.location.search);
    jobId = params.get("job") || localStorage.getItem("bflix.lastJob");
    await loadJobs();
    if (!jobId) {
      $("empty-card").classList.remove("hidden");
      return;
    }
    $("job-picker").value = jobId;
    $("job-picker").addEventListener("change", (event) => {
      window.location.href = `/studio.html?job=${event.target.value}`;
    });
    document.querySelectorAll("[data-run]").forEach((button) => {
      button.addEventListener("click", () => runStage(button.dataset.run));
    });
    $("save-dialogue").addEventListener("click", saveDialogue);
    $("load-subtitles").addEventListener("click", () => $("sub-import").click());
    $("sub-import").addEventListener("change", (event) => {
      const file = event.target.files[0];
      if (file) importSubtitles(file);
    });
    document.addEventListener("bflix:lang", async () => {
      if (job) {
        await loadVoices(job.target_lang);
        renderSpeakers();
        renderSegments();
        notices();
      }
    });
    await refresh();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
