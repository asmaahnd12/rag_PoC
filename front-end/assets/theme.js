(() => {
  const THEME_KEY = "sont_theme";
  const DEFAULT_THEME = "dark";

  function normalizeTheme(theme) {
    return theme === "light" ? "light" : "dark";
  }

  function getSavedTheme() {
    return normalizeTheme(localStorage.getItem(THEME_KEY) || DEFAULT_THEME);
  }

  function applyTheme(theme, persist = true) {
    const finalTheme = normalizeTheme(theme);
    document.documentElement.setAttribute("data-theme", finalTheme);

    if (persist) {
      localStorage.setItem(THEME_KEY, finalTheme);
    }

    const btn = document.getElementById("globalThemeToggle");
    if (!btn) return;

    const knobIcon = btn.querySelector(".theme-switch-knob");

    btn.classList.toggle("is-light", finalTheme === "light");
    btn.classList.toggle("is-dark", finalTheme === "dark");
    btn.setAttribute(
      "aria-label",
      finalTheme === "light"
        ? "Basculer vers le theme sombre"
        : "Basculer vers le theme clair",
    );
    btn.title =
      finalTheme === "light"
        ? "Basculer vers le theme sombre"
        : "Basculer vers le theme clair";

    if (knobIcon) {
      knobIcon.textContent = finalTheme === "light" ? "☀" : "☾";
    }
  }

  function toggleTheme() {
    const current =
      document.documentElement.getAttribute("data-theme") || DEFAULT_THEME;
    applyTheme(current === "light" ? "dark" : "light", true);
  }

  function ensureToggle() {
    if (document.getElementById("globalThemeToggle")) return;

    const button = document.createElement("button");
    button.id = "globalThemeToggle";
    button.className = "theme-switch";
    button.type = "button";
    button.innerHTML = `
      <span class="theme-switch-track-icon sun">☀</span>
      <span class="theme-switch-track-icon moon">☾</span>
      <span class="theme-switch-knob">☀</span>
    `;

    button.addEventListener("click", toggleTheme);
    document.body.appendChild(button);
  }

  function initThemeSystem() {
    ensureToggle();
    applyTheme(getSavedTheme(), false);

    window.addEventListener("storage", (event) => {
      if (event.key !== THEME_KEY) return;
      applyTheme(normalizeTheme(event.newValue || DEFAULT_THEME), false);
    });
  }

  window.SONTTheme = {
    applyTheme,
    toggleTheme,
    initThemeSystem,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initThemeSystem, {
      once: true,
    });
  } else {
    initThemeSystem();
  }
})();
