(() => {
    "use strict";

    const form = document.querySelector("[data-order-form]");
    if (!form) return;

    const storageKey = `crm:order-draft:${window.location.pathname}`;
    const routeList = form.querySelector("[data-order-route-list]");
    const routeTemplate = form.querySelector("template[data-order-route-empty-form]");
    const totalForms = form.querySelector("input[name='route_stops-TOTAL_FORMS']");
    let saveTimer;

    const controlValues = () => {
        const values = {};
        form.querySelectorAll("input[name], select[name], textarea[name]").forEach((field) => {
            if (field.name === "csrfmiddlewaretoken" || field.type === "submit" || field.type === "button") return;
            if (field.name.endsWith("-INITIAL_FORMS") || field.name.endsWith("-MIN_NUM_FORMS") || field.name.endsWith("-MAX_NUM_FORMS")) return;
            values[field.name] = field.type === "checkbox" || field.type === "radio"
                ? {checked: field.checked}
                : {value: field.value};
        });
        return values;
    };

    const saveDraft = () => {
        window.clearTimeout(saveTimer);
        try {
            sessionStorage.setItem(storageKey, JSON.stringify({values: controlValues()}));
        } catch (error) {
            // Автосохранение — удобство, форма продолжает работать и без него.
        }
    };

    const scheduleSave = () => {
        window.clearTimeout(saveTimer);
        saveTimer = window.setTimeout(saveDraft, 250);
    };

    const clearDraft = () => {
        window.clearTimeout(saveTimer);
        try { sessionStorage.removeItem(storageKey); } catch (error) { /* no-op */ }
    };

    const appendRouteRows = (targetTotal) => {
        if (!routeList || !routeTemplate || !totalForms) return;
        let currentTotal = Number.parseInt(totalForms.value, 10) || 0;
        while (currentTotal < targetTotal) {
            routeList.insertAdjacentHTML("beforeend", routeTemplate.innerHTML.replaceAll("__prefix__", String(currentTotal)));
            currentTotal += 1;
        }
        totalForms.value = String(currentTotal);
        form.dispatchEvent(new Event("crm:route-refresh"));
    };

    const restoreDraft = () => {
        let draft;
        try { draft = JSON.parse(sessionStorage.getItem(storageKey) || "null"); } catch (error) { return; }
        if (!draft?.values) return;

        const savedTotal = Number.parseInt(draft.values["route_stops-TOTAL_FORMS"]?.value, 10);
        if (Number.isFinite(savedTotal)) appendRouteRows(savedTotal);

        Object.entries(draft.values).forEach(([name, saved]) => {
            if (name === "route_stops-TOTAL_FORMS") return;
            const field = form.elements.namedItem(name);
            if (!field || field instanceof RadioNodeList) return;
            if ("checked" in saved) field.checked = Boolean(saved.checked);
            else if ("value" in saved) field.value = saved.value;
            field.dispatchEvent(new Event("change", {bubbles: true}));
        });
        form.dispatchEvent(new Event("crm:route-refresh"));
    };

    restoreDraft();
    form.addEventListener("input", scheduleSave);
    form.addEventListener("change", scheduleSave);
    form.addEventListener("submit", clearDraft);
    form.addEventListener("click", (event) => {
        if (event.target.closest("[data-order-route-add], [data-route-delete]")) window.setTimeout(scheduleSave, 0);
    });
    document.querySelectorAll("[data-order-cancel-confirm]").forEach((control) => {
        control.addEventListener("click", clearDraft);
    });
    window.addEventListener("pagehide", saveDraft);
})();
