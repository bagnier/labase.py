// Deep-linkable daisyUI tabs — keep the open tab in the URL hash so a tab is shareable and
// survives a reload. Opt in by marking the `role="tablist"` with `data-hash-tabs` and giving
// each `<input role="tab">` a `data-tab="<slug>"`.
//
//   - On load, `#<slug>` selects the matching tab (a server-forced tab still wins when there is
//     no hash — e.g. the tab reopened to show a form error after a POST).
//   - Picking a tab rewrites the hash in place with `replaceState`, so it does NOT add a history
//     entry: the browser Back button leaves the page rather than cycling through tabs.
(function () {
  function init() {
    document.querySelectorAll("[data-hash-tabs]").forEach(function (list) {
      var radios = list.querySelectorAll('input[role="tab"][data-tab]');
      var hash = decodeURIComponent(location.hash.replace(/^#/, ""));
      radios.forEach(function (radio) {
        if (hash && radio.dataset.tab === hash) radio.checked = true;
        radio.addEventListener("change", function () {
          if (radio.checked) history.replaceState(null, "", "#" + radio.dataset.tab);
        });
      });
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
