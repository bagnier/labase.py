// The open tab lives in the URL hash. Opt in with `data-hash-tabs` on the `role="tablist"` and
// `data-tab="<slug>"` on each `<input role="tab">`. Without a hash, the server's tab wins (e.g.
// the one showing a form error).
(() => {
  const currentHash = () => decodeURIComponent(location.hash.replace(/^#/, ""));

  const applyHash = () => {
    const hash = currentHash();
    if (!hash) return;
    for (const r of document.querySelectorAll('[data-hash-tabs] input[role="tab"][data-tab]')) {
      if (r.dataset.tab === hash && !r.checked) {
        r.checked = true;
        r.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }
  };

  const init = () => {
    for (const radio of document.querySelectorAll('[data-hash-tabs] input[role="tab"][data-tab]')) {
      radio.addEventListener("change", () => {
        // Rewrite in place (no history entry) so Back leaves the page, not cycles tabs.
        if (radio.checked) history.replaceState(null, "", `#${radio.dataset.tab}`);
      });
    }
    applyHash();
  };

  window.addEventListener("hashchange", applyHash);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
