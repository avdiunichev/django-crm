(() => {
    "use strict";

    const FILTER_SELECTOR = 'form.filters[method="get"], form[data-dynamic-filter]';
    const TEXT_DELAY = 450;
    const FOCUS_KEY = "crm-dynamic-filter-focus";
    const FILTER_STATE_PREFIX = "crm-filter-state:";

    const storageKey = (form) => {
        const action = new URL(form.getAttribute("action") || window.location.href, window.location.href);
        return `${FILTER_STATE_PREFIX}${action.pathname}`;
    };

    const normalizedParams = (params) => {
        const normalized = new URLSearchParams();
        for (const [name, value] of params.entries()) {
            if (!name || name === "page" || value === "") continue;
            normalized.append(name, value);
        }
        normalized.sort?.();
        return normalized;
    };

    const saveFilterState = (form, params) => {
        try {
            const normalized = normalizedParams(params);
            const value = normalized.toString();
            if (value) localStorage.setItem(storageKey(form), value);
            else localStorage.removeItem(storageKey(form));
        } catch (_error) {
            // Фильтры работают и без localStorage, просто не будут помнить состояние.
        }
    };

    const clearFilterState = (form) => {
        try {
            localStorage.removeItem(storageKey(form));
        } catch (_error) {
            // Нечего очищать — продолжаем переход по ссылке.
        }
    };

    const restoreFilterState = (form) => {
        if (window.location.search) {
            saveFilterState(form, new URLSearchParams(window.location.search));
            return;
        }
        let saved = "";
        try {
            saved = localStorage.getItem(storageKey(form)) || "";
        } catch (_error) {
            return;
        }
        if (!saved) return;
        const url = new URL(form.getAttribute("action") || window.location.href, window.location.href);
        url.search = saved;
        if (`${url.pathname}${url.search}` !== `${window.location.pathname}${window.location.search}`) {
            window.location.replace(url.href);
        }
    };

    const buildFilterUrl = (form) => {
        const url = new URL(form.getAttribute("action") || window.location.href, window.location.href);
        url.search = "";
        const params = new URLSearchParams();
        for (const [name, value] of new FormData(form).entries()) {
            if (typeof value === "string" && value !== "") params.append(name, value);
        }
        url.search = params.toString();
        return url;
    };

    const rememberFocus = (url, field) => {
        if (!field?.name || !field.matches('input[type="search"], input[type="text"]')) return;
        try {
            sessionStorage.setItem(FOCUS_KEY, JSON.stringify({path: url.pathname, name: field.name}));
        } catch (_error) {
            // Фильтрация продолжит работать, даже если хранилище браузера недоступно.
        }
    };

    const submitFilter = (form, field) => {
        const url = buildFilterUrl(form);
        const current = `${window.location.pathname}${window.location.search}`;
        const next = `${url.pathname}${url.search}`;
        if (current === next) return;
        rememberFocus(url, field);
        form.classList.add("is-auto-submitting");
        form.setAttribute("aria-busy", "true");
        saveFilterState(form, url.searchParams);
        window.location.assign(url.href);
    };

    const enhanceFilter = (form) => {
        if (form.dataset.dynamicFilterReady === "true") return;
        form.dataset.dynamicFilterReady = "true";
        let timer;
        let composing = false;

        form.addEventListener("submit", () => {
            const url = buildFilterUrl(form);
            saveFilterState(form, url.searchParams);
        });

        form.querySelectorAll('.clear-link, [data-reset-filters]').forEach((link) => {
            link.addEventListener("click", () => clearFilterState(form));
        });

        form.querySelectorAll('input[type="search"], input[type="text"]:not([data-crm-date])').forEach((field) => {
            field.addEventListener("compositionstart", () => { composing = true; });
            field.addEventListener("compositionend", () => {
                composing = false;
                clearTimeout(timer);
                timer = setTimeout(() => submitFilter(form, field), TEXT_DELAY);
            });
            field.addEventListener("input", () => {
                if (composing) return;
                clearTimeout(timer);
                timer = setTimeout(() => submitFilter(form, field), TEXT_DELAY);
            });
        });

        form.querySelectorAll("select, input[type=checkbox], input[type=radio], input[type=date], [data-crm-date]").forEach((field) => {
            field.addEventListener("change", () => submitFilter(form, field));
        });
    };

    const restoreSearchFocus = () => {
        let saved;
        try {
            saved = JSON.parse(sessionStorage.getItem(FOCUS_KEY) || "null");
            sessionStorage.removeItem(FOCUS_KEY);
        } catch (_error) {
            return;
        }
        if (!saved || saved.path !== window.location.pathname) return;
        const field = Array.from(document.querySelectorAll(FILTER_SELECTOR))
            .map((form) => form.elements.namedItem(saved.name))
            .find(Boolean);
        if (!field || typeof field.focus !== "function") return;
        field.focus({preventScroll: true});
        if (typeof field.setSelectionRange === "function") {
            const end = field.value.length;
            field.setSelectionRange(end, end);
        }
    };

    document.addEventListener("DOMContentLoaded", () => {
        const filterForms = Array.from(document.querySelectorAll(FILTER_SELECTOR));
        filterForms.forEach((form) => {
            restoreFilterState(form);
            enhanceFilter(form);
        });
        document.querySelectorAll('.active-filter a, a[data-reset-filters]').forEach((link) => {
            link.addEventListener("click", () => {
                filterForms.forEach(clearFilterState);
            });
        });
        restoreSearchFocus();
    });
})();
