/* History: dashboard of all projects with delete + download. */
(function () {
  const { el, toast, fmtBytes, fmtClock } = window.BF_UI;
  const api = window.BF_API;
  const t = (k, f) => window.BF_I18N.t(k, f);
  const $ = (id) => document.getElementById(id);

  let jobs = [];
  let retention = 24;

  function statusBadge(job) {
    const map = { completed: "ok", failed: "err", awaiting_input: "info", running: "warn", queued: "warn", cancelled: "" };
    const label = job.status === "awaiting_input" ? t("stage.awaiting_input") : (job.stage_label && job.stage_label[window.BF_I18N.lang]) || job.status;
    return el("span", { class: "badge " + (map[job.status] || ""), text: label });
  }

  function render() {
    const host = $("jobs");
    host.innerHTML = "";
    const filter = $("filter").value;
    const list = jobs.filter((job) => !filter || job.status === filter);
    $("history-count").textContent = `${list.length} / ${jobs.length}`;
    if (!list.length) {
      host.appendChild(el("div", { class: "pill-note" }, [
        el("span", { text: t("history.empty") }),
        el("a", { class: "btn sm", href: "/upload.html", text: t("nav.upload") })
      ]));
      return;
    }
    list.forEach((job) => {
      const media = job.media || {};
      const canPlay = job.status === "completed" && job.artifacts && job.artifacts.render && job.artifacts.render.has_dubbed;
      const actions = el("div", { class: "row" }, [
        canPlay ? el("a", { class: "btn sm", href: `/player.html?job=${job.id}`, text: t("nav.player") }) : null,
        canPlay ? el("a", { class: "btn sm", href: `/download.html?job=${job.id}`, text: t("common.download") }) : null,
        el("a", { class: "btn sm ghost", href: `/studio.html?job=${job.id}`, text: t("nav.studio") }),
        el("a", { class: "btn sm ghost", href: `/status.html?job=${job.id}`, text: t("nav.status") }),
        el("button", {
          class: "btn sm danger",
          text: t("common.delete"),
          onclick: () => removeJob(job)
        })
      ]);
      host.appendChild(
        el("div", { class: "job-card" }, [
          el("div", {}, [
            el("div", { class: "title", text: job.source_name || job.id }),
            el("div", { class: "meta" }, [
              el("span", { text: fmtClock(job.created_at) }),
              el("span", { text: `${job.source_lang || "auto"} → ${job.target_lang}` }),
              media.duration ? el("span", { text: `${Math.round(media.duration)}s` }) : null,
              job.source_bytes ? el("span", { text: fmtBytes(job.source_bytes) }) : null,
              el("span", { text: `${Math.round(job.progress)}%` })
            ]),
            job.error ? el("div", { class: "tiny", style: "color:var(--err);margin-top:6px", text: `${job.error.code}: ${job.error.message}` }) : null
          ]),
          el("div", { class: "row end", style: "gap:8px" }, [statusBadge(job), actions])
        ])
      );
    });
  }

  async function removeJob(job) {
    if (!window.confirm(t("history.deleteConfirm"))) return;
    try {
      await api.del(`/api/jobs/${job.id}`);
      jobs = jobs.filter((item) => item.id !== job.id);
      render();
      toast(t("history.deleted"), "ok");
      if (localStorage.getItem("bflix.lastJob") === job.id) localStorage.removeItem("bflix.lastJob");
    } catch (error) {
      toast(api.errorText(error), "err");
    }
  }

  async function load() {
    try {
      const data = await api.get("/api/jobs", { limit: 100 });
      jobs = data.jobs;
      retention = data.retention_hours;
      const queue = data.queue || {};
      $("storage-info").textContent = `queue ${queue.active || 0} active / ${queue.queued || 0} waiting · storage ${fmtBytes(queue.storage_bytes || 0)} · auto-delete ${retention}h`;
      render();
    } catch (error) {
      $("jobs").innerHTML = "";
      $("jobs").appendChild(el("div", { class: "pill-note" }, [
        el("b", { text: api.errorText(error) }),
        el("a", { class: "btn sm", href: "/settings.html", text: t("nav.settings") })
      ]));
    }
  }

  function boot() {
    $("refresh").addEventListener("click", load);
    $("filter").addEventListener("change", render);
    document.addEventListener("bflix:lang", render);
    load();
    setInterval(load, 15000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
