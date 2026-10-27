"use strict";

(() => {
  const storageKey = "agentos.theme";
  const root = document.documentElement;
  const system = window.matchMedia("(prefers-color-scheme: dark)");
  const valid = (value) => value === "light" || value === "dark";
  let preference = null;
  try {
    const stored = window.localStorage.getItem(storageKey);
    if (valid(stored)) preference = stored;
  } catch { /* Theme selection still works when browser storage is unavailable. */ }

  function syncControls() {
    const dark = root.dataset.theme === "dark";
    const toggle = document.getElementById("theme-toggle");
    const label = document.getElementById("theme-label");
    if (toggle) {
      toggle.setAttribute("aria-label", "Dark mode");
      toggle.setAttribute("aria-pressed", String(dark));
      toggle.title = dark ? "Switch to light mode" : "Switch to dark mode";
    }
    if (label) label.textContent = "Dark mode";
    const themeColor = document.querySelector('meta[name="theme-color"]');
    if (themeColor) {
      const color = getComputedStyle(root).getPropertyValue("--theme-color").trim();
      themeColor.content = color || (dark ? "#101112" : "#f3f7f8");
    }
  }

  function applyTheme() {
    root.dataset.theme = preference || (system.matches ? "dark" : "light");
    syncControls();
  }

  // This script runs before the stylesheet, so the first paint uses the right theme.
  applyTheme();

  function connectToggle() {
    syncControls();
    document.getElementById("theme-toggle")?.addEventListener("click", () => {
      preference = root.dataset.theme === "dark" ? "light" : "dark";
      try { window.localStorage.setItem(storageKey, preference); } catch { /* Keep the choice in memory. */ }
      applyTheme();
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", connectToggle, { once: true });
  else connectToggle();

  system.addEventListener("change", () => { if (preference === null) applyTheme(); });
  window.addEventListener("storage", (event) => {
    if (event.key !== storageKey && event.key !== null) return;
    preference = valid(event.newValue) ? event.newValue : null;
    applyTheme();
  });
})();
