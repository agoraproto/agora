// Sprint 29b — Shared navigation (audit finding #4).
// Pages used to ship slightly different <nav> menus; this script
// rewrites them at load time so every page has the same canonical
// nav. Active page is auto-highlighted from the current URL path.
(function () {
  const items = [
    { href: "/#how",                       label: "Protocol",    pathPrefix: ["#how"] },
    { href: "/marketplace.html",           label: "Marketplace", pathPrefix: ["/marketplace"] },
    { href: "/sell.html",                  label: "Sell",        pathPrefix: ["/sell"] },
    { href: "/live.html",                  label: "Live",        pathPrefix: ["/live"] },
    { href: "https://api.agoraproto.org/docs", label: "API",     external: true },
    { href: "https://github.com/agoraproto/agora", label: "GitHub →", external: true },
  ];

  function currentPath() {
    return (location.pathname || "/").replace(/\/index\.html$/, "/");
  }

  function isActive(it) {
    if (it.external) return false;
    const p = currentPath();
    return it.pathPrefix && it.pathPrefix.some((pp) => p === pp || p.startsWith(pp));
  }

  function build() {
    // Try common containers in this order
    const ul =
      document.querySelector("nav .nav-links") ||
      document.querySelector("nav ul");
    if (!ul) return;

    // Preserve an existing #authSlot so the login button stays on
    // pages that have it.
    const authSlot = ul.querySelector("#authSlot");

    ul.innerHTML = "";
    for (const it of items) {
      const li = document.createElement("li");
      if (it.label === "Protocol" || it.label === "API")
        li.className = "hide-mobile";
      const a = document.createElement("a");
      a.href = it.href;
      a.textContent = it.label;
      if (isActive(it)) a.classList.add("active");
      if (it.external) {
        a.rel = "noopener";
      }
      li.appendChild(a);
      ul.appendChild(li);
    }
    if (authSlot) ul.appendChild(authSlot);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", build);
  } else {
    build();
  }
})();
