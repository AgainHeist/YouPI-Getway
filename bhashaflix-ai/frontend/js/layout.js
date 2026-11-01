/* Shared shell: header, language switch, bottom navigation. */
(function () {
  const { t } = window.BF_I18N;
  const { el, icon } = window.BF_UI;

  const NAV = [
    { key: "home", href: "/index.html", icon: "home", label: "nav.home" },
    { key: "upload", href: "/upload.html", icon: "upload", label: "nav.upload" },
    { key: "studio", href: "/studio.html", icon: "studio", label: "nav.studio" },
    { key: "status", href: "/status.html", icon: "status", label: "nav.status" },
    { key: "history", href: "/history.html", icon: "history", label: "nav.history" }
  ];

  const TOP = [
    ...NAV,
    { key: "player", href: "/player.html", icon: "player", label: "nav.player" },
    { key: "download", href: "/download.html", icon: "download", label: "nav.download" },
    { key: "settings", href: "/settings.html", icon: "settings", label: "nav.settings" },
    { key: "privacy", href: "/privacy.html", icon: "privacy", label: "nav.privacy" }
  ];

  function mount(page) {
    const topHost = document.getElementById("topbar");
    if (topHost) {
      topHost.innerHTML = "";
      const brand = el("a", { class: "brand", href: "/index.html" }, [
        el("span", { class: "brand-mark", html: icon("film") }),
        el("span", {}, [
          document.createTextNode("BhashaFlix "),
          el("span", { class: "hero-title-grad", text: "AI" })
        ])
      ]);
      const nav = el("nav", { class: "top-nav" },
        TOP.map((item) => el("a", {
          href: item.href,
          class: item.key === page ? "active" : "",
          text: t(item.label)
        }))
      );
      const switcher = el("div", { class: "lang-switch" },
        window.BF_I18N.langs.map((code) => el("button", {
          type: "button",
          "data-lang": code,
          text: code === "hi" ? "हिं" : "EN",
          onclick: () => window.BF_I18N.setLang(code)
        }))
      );
      const actions = el("div", { class: "top-actions" }, [switcher]);
      topHost.append(brand, nav, actions);
    }

    const bottomHost = document.getElementById("bottomnav");
    if (bottomHost) {
      bottomHost.innerHTML = "";
      NAV.forEach((item) => {
        bottomHost.appendChild(el("a", {
          href: item.href,
          class: item.key === page ? "active" : "",
          html: `${icon(item.icon)}<span>${window.BF_UI.esc(t(item.label))}</span>`
        }));
      });
    }

    window.BF_I18N.apply();
    document.addEventListener("bflix:lang", () => {
      mount(page);
    });
  }

  window.BF_LAYOUT = { mount };
  document.addEventListener("DOMContentLoaded", () => {
    mount(document.body.dataset.page || "home");
  });
})();
