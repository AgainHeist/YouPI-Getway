/* Upload page: real validation, real progress, real errors. */
(function () {
  const { el, fmtBytes, toast, icon } = window.BF_UI;
  const api = window.BF_API;
  const t = (k, f) => window.BF_I18N.t(k, f);

  const ALLOWED = [".mp4", ".m4v", ".mkv", ".mov", ".webm"];
  let config = { max_upload_mb: 512, max_duration_sec: 900 };
  let selectedFile = null;
  let busy = false;

  const $ = (id) => document.getElementById(id);

  function ext(name) {
    const idx = String(name || "").lastIndexOf(".");
    return idx < 0 ? "" : name.slice(idx).toLowerCase();
  }

  function showError(error) {
    const host = $("upload-error");
    host.classList.remove("hidden");
    host.innerHTML = "";
    const box = el("div", { class: "pill-note", style: "border-color: rgba(255,84,112,.5); background: rgba(255,84,112,.07)" }, [
      el("div", {}, [
        el("b", { text: api.errorText(error) }),
        el("div", { class: "tiny", style: "margin-top:4px", text: error.detail && error.detail !== api.errorText(error) ? error.detail : "" }),
        api.errorHint(error) ? el("div", { class: "tiny muted", style: "margin-top:4px", text: api.errorHint(error) }) : null
      ])
    ]);
    host.appendChild(box);
  }

  function clearError() {
    const host = $("upload-error");
    host.classList.add("hidden");
    host.innerHTML = "";
  }

  function setFile(file) {
    clearError();
    selectedFile = file || null;
    const info = $("file-info");
    info.innerHTML = "";
    if (!file) {
      $("submit-btn").disabled = true;
      return;
    }
    $("submit-btn").disabled = false;
    const badExt = !ALLOWED.includes(ext(file.name));
    const tooBig = file.size > config.max_upload_mb * 1024 * 1024;
    const row = el("div", { class: "pill-note" }, [
      el("div", { style: "flex:1" }, [
        el("b", { text: file.name }),
        el("div", { class: "tiny muted", text: `${fmtBytes(file.size)} · ${ext(file.name) || "no extension"}` })
      ]),
      el("span", {
        class: `badge ${badExt || tooBig ? "err" : "ok"}`,
        text: badExt ? "unsupported" : tooBig ? "too large" : "ready"
      })
    ]);
    info.appendChild(row);
    if (badExt) {
      showError({ code: "UNSUPPORTED_FORMAT", detail: `Allowed: ${ALLOWED.join(", ")}` });
      $("submit-btn").disabled = true;
    }
    if (tooBig) {
      showError({ code: "FILE_TOO_LARGE", detail: `Limit is ${config.max_upload_mb} MB on this server.` });
      $("submit-btn").disabled = true;
    }
  }

  function updateModeFields() {
    const mode = $("mode").value;
    $("target-sub-field").classList.toggle("hidden", mode === "auto");
  }

  async function loadLanguages() {
    try {
      const data = await api.get("/api/languages");
      const target = $("target-lang");
      const source = $("source-lang");
      target.innerHTML = "";
      source.innerHTML = "";
      data.languages.filter((l) => l.target).forEach((lang) => {
        target.appendChild(el("option", { value: lang.code, text: `${lang.native} — ${lang.en}` }));
      });
      source.appendChild(el("option", { value: "auto", text: t("upload.autoDetect") }));
      data.languages.filter((l) => l.source).forEach((lang) => {
        source.appendChild(el("option", { value: lang.code, text: `${lang.native} — ${lang.en}` }));
      });
      target.value = api.store.target || "hi";
      $("mode").value = api.store.mode || "auto";
      updateModeFields();
    } catch (error) {
      toast(api.errorText(error), "err");
    }
  }

  async function loadConfig() {
    try {
      config = await api.get("/api/config");
      $("size-limit").textContent = `${t("upload.sizeLimit")}: ${config.max_upload_mb} MB · ${Math.round(config.max_duration_sec / 60)} min`;
      if (config.auth_required && !api.store.token) {
        toast("This server requires an access token. Add it in Settings.", "warn", 7000);
      }
    } catch (error) {
      /* ignore: languages load already reports connection issues */
    }
  }

  function wireDropzone() {
    const dz = $("dropzone");
    const input = $("file-input");
    $("dz-icon").innerHTML = icon("upload");
    dz.addEventListener("click", () => input.click());
    dz.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); input.click(); }
    });
    input.addEventListener("change", () => setFile(input.files[0]));
    ["dragenter", "dragover"].forEach((name) =>
      dz.addEventListener(name, (event) => { event.preventDefault(); dz.classList.add("drag"); })
    );
    ["dragleave", "drop"].forEach((name) =>
      dz.addEventListener(name, (event) => { event.preventDefault(); dz.classList.remove("drag"); })
    );
    dz.addEventListener("drop", (event) => {
      const file = event.dataTransfer.files && event.dataTransfer.files[0];
      if (file) { input.files = event.dataTransfer.files; setFile(file); }
    });
  }

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    clearError();
    if (!selectedFile) {
      showError({ code: "VALIDATION_ERROR", detail: t("upload.needFile") });
      return;
    }
    if (!$("consent").checked) {
      toast(t("upload.accept"), "warn", 6000);
      return;
    }
    busy = true;
    const button = $("submit-btn");
    button.disabled = true;
    const wrap = $("progress-wrap");
    wrap.classList.remove("hidden");
    const bar = $("progress-bar");
    const pct = $("progress-pct");

    const form = new FormData();
    form.append("file", selectedFile);
    const sub = $("sub-input").files[0];
    const tsub = $("tsub-input").files[0];
    if (sub) form.append("subtitle", sub);
    if (tsub) form.append("translated_subtitle", tsub);
    form.append("target_lang", $("target-lang").value);
    form.append("source_lang", $("source-lang").value);
    form.append("input_mode", $("mode").value);
    form.append("autostart", "true");
    form.append("stop_after", $("stop-after").value);
    form.append("options", JSON.stringify({ separate: $("separation").value }));

    api.store.target = $("target-lang").value;
    api.store.mode = $("mode").value;

    try {
      const result = await api.upload(form, {
        onProgress: (fraction) => {
          const value = Math.round(fraction * 100);
          bar.style.width = value + "%";
          pct.textContent = value + "%";
        }
      });
      bar.style.width = "100%";
      pct.textContent = "100%";
      const job = result.job;
      localStorage.setItem("bflix.lastJob", job.id);
      const advisories = (result.validation && result.validation.advisories) || [];
      if (advisories.length) sessionStorage.setItem("bflix.advisories." + job.id, JSON.stringify(advisories));
      toast("Upload complete — processing started.", "ok");
      if ($("mode").value === "manual") window.location.href = `/studio.html?job=${job.id}`;
      else window.location.href = `/status.html?job=${job.id}`;
    } catch (error) {
      showError(error);
      button.disabled = false;
      wrap.classList.add("hidden");
      bar.style.width = "0%";
      busy = false;
    }
  }

  function boot() {
    wireDropzone();
    $("submit-btn").disabled = true;
    $("mode").addEventListener("change", updateModeFields);
    $("upload-form").addEventListener("submit", submit);
    loadConfig();
    loadLanguages();
    document.addEventListener("bflix:lang", loadLanguages);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
