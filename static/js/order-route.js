(() => {
    "use strict";

    const enhance = (form) => {
        if (!form || form.dataset.orderRouteReady === "true") return;
        const list = form.querySelector("[data-order-route-list]");
        const template = form.querySelector("template[data-order-route-empty-form]");
        const totalInput = form.querySelector("input[name='route_stops-TOTAL_FORMS']");
        if (!list || !template || !totalInput) return;
        form.dataset.orderRouteReady = "true";

        const rows = () => Array.from(list.querySelectorAll("[data-order-route-stop]"));
        const updateRow = (row, index) => {
            const kind = row.querySelector("select[name$='-kind']")?.value || "pickup";
            const deleted = row.querySelector("input[name$='-DELETE']")?.checked;
            const sequence = row.querySelector("input[name$='-sequence']");
            if (sequence) sequence.value = String(index + 1);
            const number = row.querySelector("[data-route-number]");
            if (number) number.textContent = String(index + 1);
            const title = row.querySelector("[data-route-title]");
            if (title) title.textContent = kind === "delivery" ? "Выгрузка" : "Погрузка";
            row.classList.toggle("is-delivery", kind === "delivery");
            row.classList.toggle("is-deleted", Boolean(deleted));
        };
        const refresh = () => rows().forEach(updateRow);

        const add = (kind) => {
            const index = Number.parseInt(totalInput.value, 10);
            list.insertAdjacentHTML(
                "beforeend",
                template.innerHTML.replaceAll("__prefix__", String(index))
            );
            totalInput.value = String(index + 1);
            const row = list.lastElementChild;
            const kindSelect = row?.querySelector("select[name$='-kind']");
            if (kindSelect) kindSelect.value = kind;
            refresh();
            window.CRMUniversalSelects?.enhanceWithin(row);
            window.CRMAddressSuggestions?.enhanceWithin(row);
            row?.querySelector("input[name$='-city']")?.focus();
        };

        form.addEventListener("change", (event) => {
            if (event.target.matches("select[name^='route_stops-'][name$='-kind'], input[name^='route_stops-'][name$='-DELETE']")) {
                refresh();
            }
        });
        form.addEventListener("submit", refresh);
        form.querySelectorAll("[data-order-route-add]").forEach((button) => {
            button.addEventListener("click", () => add(button.dataset.orderRouteAdd));
        });
        refresh();
    };

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-order-form]").forEach(enhance);
    });
})();
