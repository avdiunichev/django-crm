(() => {
    "use strict";

    const storageKey = "crm-color-theme";
    const root = document.documentElement;

    const currentTheme = () => root.dataset.theme === "dark" ? "dark" : "light";

    const updateControls = (theme) => {
        document.querySelectorAll("[data-theme-choice]").forEach((button) => {
            const isSelected = button.dataset.themeChoice === theme;
            button.setAttribute("aria-pressed", String(isSelected));
        });
    };

    const applyTheme = (theme, persist = true) => {
        const normalizedTheme = theme === "dark" ? "dark" : "light";
        root.dataset.theme = normalizedTheme;
        root.style.colorScheme = normalizedTheme;
        updateControls(normalizedTheme);

        if (persist) {
            try {
                window.localStorage.setItem(storageKey, normalizedTheme);
            } catch (error) {
                /* Тема продолжит работать до закрытия страницы. */
            }
        }
    };

    document.addEventListener("DOMContentLoaded", () => {
        updateControls(currentTheme());
        document.querySelectorAll("[data-theme-choice]").forEach((button) => {
            button.addEventListener("click", () => applyTheme(button.dataset.themeChoice));
        });
    });
})();
