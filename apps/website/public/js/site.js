/**
 * Progressive enhancements for the public site. Everything here is optional — the pages
 * render fully without JavaScript, so this file stays tiny and CSP-friendly (`script-src 'self'`).
 */
(function () {
  'use strict';

  // Copy-to-clipboard for the integration snippet.
  document.addEventListener('click', function (event) {
    var button = event.target.closest('[data-copy-target]');
    if (!button) return;

    var target = document.getElementById(button.getAttribute('data-copy-target'));
    if (!target) return;

    var text = target.textContent || '';
    var done = function () {
      var original = button.textContent;
      button.textContent = 'Copied';
      setTimeout(function () { button.textContent = original; }, 1600);
    };

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(function () {});
    }
  });

  // Highlight the section currently in view in the header nav.
  var sections = Array.prototype.slice.call(document.querySelectorAll('section[id]'));
  if (!sections.length || !('IntersectionObserver' in window)) return;

  var links = Array.prototype.slice.call(document.querySelectorAll('.nav-links a[href^="/#"]'));
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      links.forEach(function (link) {
        var matches = link.getAttribute('href') === '#' + entry.target.id ||
          link.getAttribute('href') === '/#' + entry.target.id;
        link.style.color = matches ? '#fff' : '';
      });
    });
  }, { rootMargin: '-45% 0px -50% 0px' });

  sections.forEach(function (section) { observer.observe(section); });
})();
