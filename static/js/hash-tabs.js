// Deep-linkable daisyUI tabs — keep the open tab in the URL hash so a tab is shareable and
// survives a reload. Opt in by marking the `role="tablist"` with `data-hash-tabs` and giving
// each `<input role="tab">` a `data-tab="<slug>"`.
//
//   - `#<slug>` selects the matching tab, on first load AND on later hashchange (so a link works
//     whether the page is opened fresh or already visible). With no hash, the server-rendered
//     default tab wins (e.g. the tab reopened to show a form error after a POST).
//   - Picking a tab rewrites the hash in place with `replaceState`, so it does NOT add a history
//     entry: the browser Back button leaves the page rather than cycling through tabs.
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
