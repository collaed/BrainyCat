/* BrainyCat shared navigation — one nav for every page (see docs/ui-redesign/proposal.md).
   Usage: <div id="bc-nav"></div><script src="nav.js"></script>  (after api.js) */
(function () {
  const ITEMS = [
    { href: "index.html", label: "Library", match: ["index.html", ""] },
    { href: "catalog.html", label: "Discover", match: ["catalog.html", "recommendations.html"] },
    { href: "fix-library.html", label: "Fix Library", match: ["fix-library.html", "intelligence.html", "intel-quality.html", "intel-authors.html", "intel-dupes.html", "intel-content-dupes.html", "intel-series.html", "metadata-ops.html", "filename-history.html", "series.html", "authors.html"] },
    { href: "stats.html", label: "Insights", match: ["stats.html", "efficiency.html"] },
    { href: "settings.html", label: "Settings", match: ["settings.html", "rules.html"] },
  ];
  const here = location.pathname.split("/").pop() || "";
  const el = document.getElementById("bc-nav");
  if (!el) return;

  // Embedded as a Fix Library tab (fix-library.html's iframe): the outer page already provides nav
  // and a way back, so this page's own header/back-link/nav bar would just be confusing chrome-in-chrome.
  if (window.self !== window.top) {
    const chrome = el.closest("header, nav");
    if (chrome) chrome.style.display = "none";
    return;
  }

  el.innerHTML = `<a href="incoming.html" id="incoming-link"${here === "incoming.html" ? ' class="active"' : ""}>📥 Incoming</a>` +
    ITEMS.map(i => `<a href="${i.href}"${i.match.includes(here) ? ' class="active"' : ""}>${i.label}</a>`).join("") +
    `<a href="#" onclick="return BC_logout()">Logout</a>`;
  if (window.BC) BC.get("/incoming/status").then(d => { if (d.count) document.getElementById("incoming-link").textContent = `📥 ${d.count} incoming`; }).catch(() => {});
  const style = document.createElement("style");
  style.textContent = `
    #bc-nav{display:flex;gap:.3rem;align-items:center;flex-wrap:wrap}
    #bc-nav a{font-size:.85rem;text-decoration:none;padding:.35rem .7rem;border-radius:6px;color:inherit;opacity:.75}
    #bc-nav a:hover{opacity:1;background:rgba(128,128,128,.15)}
    #bc-nav a.active{opacity:1;font-weight:600;background:rgba(128,128,128,.2)}
  `;
  document.head.appendChild(style);
})();

function BC_logout() {
  document.cookie = "brainycat_session=;Max-Age=0;path=/";
  window.location = "/static/login.html";
  return false;
}
