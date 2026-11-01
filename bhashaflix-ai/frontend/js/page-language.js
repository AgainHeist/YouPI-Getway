/* Language selection with live voice availability + previews. */
(function () {
  const { el, toast } = window.BF_UI;
  const api = window.BF_API;
  const t = (k, f) => window.BF_I18N.t(k, f);
  const $ = (id) => document.getElementById(id);

  let languages = [];
  let target = api.store.target || "hi";
  let source = localStorage.getItem("bflix.source") || "auto";
  let player = null;

  function card(lang, selected, onclick) {
    return el("button", {
      class: "lang-card " + (selected ? "on" : ""),
      type: "button",
      onclick
    }, [
      el("div", { class: "native", text: lang.native }),
      el("div", { class: "name", text: lang.en }),
      el("span", { class: "flag", text: lang.script })
    ]);
  }

  function render() {
    const targets = $("targets");
    const sources = $("sources");
    targets.innerHTML = "";
    sources.innerHTML = "";
    languages.filter((lang) => lang.target).forEach((lang) => {
      targets.appendChild(card(lang, lang.code === target, () => { target = lang.code; api.store.target = target; render(); loadVoices(); }));
    });
    const auto = { code: "auto", native: t("upload.autoDetect"), en: "auto-detect", script: "whisper / text" };
    sources.appendChild(card(auto, source === "auto", () => { source = "auto"; localStorage.setItem("bflix.source", source); render(); }));
    languages.filter((lang) => lang.source).forEach((lang) => {
      sources.appendChild(card(lang, lang.code === source, () => { source = lang.code; localStorage.setItem("bflix.source", source); render(); }));
    });
  }

  function preview(voice, sample) {
    return async () => {
      try {
        const headers = { "Content-Type": "application/json" };
        if (api.store.token) headers["X-API-Token"] = api.store.token;
        const response = await fetch(api.url("/api/voice-preview"), {
          method: "POST",
          headers,
          body: JSON.stringify({ text: sample, lang: target, voice })
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          throw (payload && payload.error) || { message: "preview failed" };
        }
        const blob = await response.blob();
        if (player) player.pause();
        player = new Audio(URL.createObjectURL(blob));
        await player.play();
      } catch (error) {
        toast(api.errorText(error), "err");
      }
    };
  }

  async function loadVoices() {
    const host = $("voices");
    host.innerHTML = '<div class="skeleton" style="height:60px"></div>';
    try {
      const data = await api.get("/api/voices", { lang: target });
      const list = (data.catalog && data.catalog[target]) || [];
      host.innerHTML = "";
      if (!list.length) {
        host.appendChild(el("div", { class: "pill-note" }, [
          el("b", { text: t("lang.noVoices") }),
          el("div", { class: "tiny", text: (data.engines || []).length ? `installed engines: ${data.engines.join(", ")}` : "no TTS engine installed on this backend" })
        ]));
        return;
      }
      list.forEach((voice) => {
        const sample = target === "hi" ? "नमस्ते, यह मेरी आवाज़ है।" : "Hello, this is my voice sample.";
        host.appendChild(
          el("div", { class: "row between", style: "border-bottom:1px solid var(--line-soft);padding-bottom:8px" }, [
            el("div", {}, [
              el("div", { style: "font-weight:650", text: voice.label }),
              el("div", { class: "tiny muted", text: `${voice.engine} · ${voice.gender} · ${voice.sample_rate} Hz · ${voice.quality}` })
            ]),
            el("button", { class: "btn sm ghost", text: "▶ " + t("lang.preview"), onclick: preview(voice.id, sample) })
          ])
        );
      });
    } catch (error) {
      host.innerHTML = "";
      host.appendChild(el("div", { class: "pill-note", text: api.errorText(error) }));
    }
  }

  async function boot() {
    try {
      const data = await api.get("/api/languages");
      languages = data.languages;
    } catch (error) {
      toast(api.errorText(error), "err");
      languages = [];
    }
    render();
    loadVoices();
    $("reload-voices").addEventListener("click", loadVoices);
    $("save-pref").addEventListener("click", () => {
      api.store.target = target;
      localStorage.setItem("bflix.source", source);
      toast(t("common.saved"), "ok");
    });
    document.addEventListener("bflix:lang", () => { render(); loadVoices(); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
