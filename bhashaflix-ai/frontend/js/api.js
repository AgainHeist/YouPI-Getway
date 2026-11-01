/* API client. All keys stay on the server — the browser only ever holds an
   optional access token that the operator created. */
(function () {
  const store = {
    get backend() { return (localStorage.getItem("bflix.backend") || "").replace(/\/$/, ""); },
    set backend(value) { localStorage.setItem("bflix.backend", value || ""); },
    get token() { return localStorage.getItem("bflix.token") || ""; },
    set token(value) { localStorage.setItem("bflix.token", value || ""); },
    get target() { return localStorage.getItem("bflix.target") || "hi"; },
    set target(value) { localStorage.setItem("bflix.target", value); },
    get mode() { return localStorage.getItem("bflix.mode") || "auto"; },
    set mode(value) { localStorage.setItem("bflix.mode", value); }
  };

  function base() {
    return store.backend || "";
  }

  function url(path, params) {
    const full = base() + path;
    if (!params) return full;
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v != null && v !== "") qs.set(k, v); });
    const s = qs.toString();
    return s ? `${full}?${s}` : full;
  }

  function withToken(path, params) {
    const merged = Object.assign({}, params || {});
    if (store.token) merged.token = store.token;
    return url(path, merged);
  }

  async function request(method, path, body, options) {
    const opts = options || {};
    const headers = { Accept: "application/json" };
    if (store.token) headers["X-API-Token"] = store.token;
    let payload;
    if (body instanceof FormData) payload = body;
    else if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(url(path, opts.params), { method, headers, body: payload });
    } catch (networkError) {
      const error = new Error("NETWORK");
      error.code = "NETWORK";
      error.detail = networkError.message;
      throw error;
    }
    const contentType = response.headers.get("content-type") || "";
    const data = contentType.includes("application/json") ? await response.json().catch(() => null) : await response.text();
    if (!response.ok) {
      const error = new Error("HTTP_" + response.status);
      error.status = response.status;
      const payloadError = data && data.error ? data.error : null;
      error.code = (payloadError && payloadError.code) || `HTTP_${response.status}`;
      error.detail = payloadError
        ? payloadError.detail || payloadError.message
        : typeof data === "string" ? data : response.statusText;
      error.hint = payloadError ? payloadError.hint : null;
      error.payload = payloadError;
      throw error;
    }
    return data;
  }

  const get = (path, params) => request("GET", path, undefined, { params });
  const post = (path, body, params) => request("POST", path, body === undefined ? {} : body, { params });
  const patch = (path, body) => request("PATCH", path, body);
  const put = (path, body) => request("PUT", path, body);
  const del = (path) => request("DELETE", path);

  /** Upload with real progress (fetch cannot report upload progress). */
  function upload(formData, { onProgress, signal } = {}) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", url("/api/upload"));
      if (store.token) xhr.setRequestHeader("X-API-Token", store.token);
      xhr.responseType = "json";
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total);
      };
      xhr.onload = () => {
        const data = xhr.response;
        if (xhr.status >= 200 && xhr.status < 300) return resolve(data);
        const payloadError = data && data.error ? data.error : {};
        const error = new Error("HTTP_" + xhr.status);
        error.status = xhr.status;
        error.code = payloadError.code || `HTTP_${xhr.status}`;
        error.detail = payloadError.detail || payloadError.message || xhr.statusText;
        error.hint = payloadError.hint;
        error.payload = payloadError;
        reject(error);
      };
      xhr.onerror = () => {
        const error = new Error("NETWORK");
        error.code = "NETWORK";
        reject(error);
      };
      xhr.onabort = () => {
        const error = new Error("ABORTED");
        error.code = "ABORTED";
        reject(error);
      };
      if (signal) signal.addEventListener("abort", () => xhr.abort());
      xhr.send(formData);
    });
  }

  /** Server-sent events with an automatic polling fallback. */
  function watch(jobId, { onProgress, onLog, onDone, onError } = {}) {
    let closed = false;
    let source = null;
    let pollTimer = null;

    const stop = () => {
      closed = true;
      if (source) source.close();
      if (pollTimer) clearTimeout(pollTimer);
    };

    const poll = async () => {
      if (closed) return;
      try {
        const job = await get(`/api/status/${jobId}`);
        if (onProgress) onProgress(job);
        (job.events || []).forEach((event) => onLog && onLog(event));
        if (["completed", "failed", "cancelled"].includes(job.status)) {
          if (onDone) onDone(job);
          return stop();
        }
      } catch (error) {
        if (onError) onError(error);
        return stop();
      }
      pollTimer = setTimeout(poll, 2000);
    };

    try {
      source = new EventSource(withToken(`/api/jobs/${jobId}/events`));
      source.addEventListener("progress", (event) => onProgress && onProgress(JSON.parse(event.data)));
      source.addEventListener("log", (event) => onLog && onLog(JSON.parse(event.data)));
      source.addEventListener("done", (event) => {
        const job = JSON.parse(event.data);
        if (onDone) onDone(job);
        stop();
      });
      source.addEventListener("gone", () => { if (onError) onError(new Error("gone")); stop(); });
      source.onerror = () => {
        if (closed) return;
        stop();
        poll();
      };
    } catch (error) {
      poll();
    }
    return { stop };
  }

  const mediaUrl = (jobId, track) => withToken(`/api/media/${jobId}`, { track: track || "dubbed" });
  const downloadUrl = (jobId, kind) => withToken(`/api/download/${jobId}`, { kind: kind || "dubbed" });
  const subtitleUrl = (jobId, kind) =>
    withToken(`/api/jobs/${jobId}/subtitles/${kind || "translated"}.vtt`);

  function errorText(error, lang) {
    if (!error) return window.BF_I18N.t("common.unknown");
    if (error.code === "NETWORK") {
      return window.BF_I18N.lang === "hi"
        ? "सर्वर से संपर्क नहीं हो सका। बैकएंड URL जाँचें।"
        : "Could not reach the backend. Check the backend URL in Settings.";
    }
    const payload = error.payload || {};
    const isHi = (lang || window.BF_I18N.lang) === "hi";
    if (isHi && payload.message_hi) return payload.message_hi;
    if (payload.message) return payload.message;
    return error.detail || error.message || "Error";
  }

  function errorHint(error) {
    const payload = error && error.payload ? error.payload : {};
    return error && (error.hint || payload.hint) ? error.hint || payload.hint : null;
  }

  window.BF_API = {
    store, get, post, patch, put, del, upload, watch, url, withToken,
    mediaUrl, downloadUrl, subtitleUrl, errorText, errorHint
  };
})();
