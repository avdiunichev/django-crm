(() => {
    "use strict";

    const enhance = (form) => {
        if (!form || form.dataset.orderRouteReady === "true") return;
        const list = form.querySelector("[data-order-route-list]");
        const template = form.querySelector("template[data-order-route-empty-form]");
        const totalInput = form.querySelector("input[name='route_stops-TOTAL_FORMS']");
        if (!list || !template || !totalInput) return;
        const routeLocked = form.dataset.orderRouteLocked === "true";
        form.dataset.orderRouteReady = "true";

        const rows = () => Array.from(list.querySelectorAll("[data-order-route-stop]"));
        const updateRow = (row, index, activeKindCounts) => {
            const kind = row.querySelector("[name$='-kind']")?.value || "pickup";
            const deleted = row.querySelector("input[name$='-DELETE']")?.checked;
            const sequence = row.querySelector("input[name$='-sequence']");
            if (sequence && index !== null) sequence.value = String(index);
            const number = row.querySelector("[data-route-number]");
            if (number && index !== null) number.textContent = String(index);
            const title = row.querySelector("[data-route-title]");
            if (title) {
                title.textContent = kind === "delivery"
                    ? "Выгрузка"
                    : (kind === "intermediate" ? "Промежуточная точка" : "Погрузка");
            }
            const organization = row.querySelector("[name$='-organization']");
            const organizationLabel = organization
                ? row.querySelector(`label[for="${organization.id}"]`)
                : null;
            if (organizationLabel) {
                organizationLabel.textContent = kind === "delivery"
                    ? "Грузополучатель"
                    : (kind === "intermediate" ? "Контрагент точки" : "Грузоотправитель");
            }
            row.classList.toggle("is-delivery", kind === "delivery");
            row.classList.toggle("is-intermediate", kind === "intermediate");
            row.classList.toggle("is-deleted", Boolean(deleted));
            const deleteButton = row.querySelector("[data-route-delete]");
            if (deleteButton) {
                const requiredKind = kind === "pickup" || kind === "delivery";
                const canDelete = !routeLocked && !deleted
                    && (!requiredKind || activeKindCounts[kind] > 1);
                deleteButton.disabled = !canDelete;
                deleteButton.title = routeLocked
                    ? "Заказ назначен в рейс. Изменяйте маршрут в карточке рейса."
                    : canDelete
                    ? "Удалить точку маршрута"
                    : "В маршруте должна остаться хотя бы одна "
                        + (kind === "delivery" ? "выгрузка" : "погрузка");
            }
        };
        const refresh = () => {
            const activeKindCounts = {pickup: 0, delivery: 0, intermediate: 0};
            rows().forEach((row) => {
                const kind = row.querySelector("[name$='-kind']")?.value || "pickup";
                const deleted = row.querySelector("input[name$='-DELETE']")?.checked;
                if (!deleted && Object.hasOwn(activeKindCounts, kind)) activeKindCounts[kind] += 1;
            });
            let activeIndex = 0;
            rows().forEach((row) => {
                const deleted = row.querySelector("input[name$='-DELETE']")?.checked;
                updateRow(row, deleted ? null : ++activeIndex, activeKindCounts);
            });
        };

        const add = (kind) => {
            if (routeLocked) return;
            const index = Number.parseInt(totalInput.value, 10);
            list.insertAdjacentHTML(
                "beforeend",
                template.innerHTML.replaceAll("__prefix__", String(index))
            );
            totalInput.value = String(index + 1);
            const row = list.lastElementChild;
            const kindField = row?.querySelector("[name$='-kind']");
            if (kindField) kindField.value = kind;
            refresh();
            window.CRMUniversalSelects?.enhanceWithin(row);
            window.CRMAddressSuggestions?.enhanceWithin(row);
            window.CRMCitySuggestions?.enhanceWithin(row);
            row?.querySelector("select[name$='-organization'], input[name$='-address'], textarea[name$='-address']")?.focus();
        };

        form.addEventListener("click", (event) => {
            const button = event.target.closest("[data-route-delete]");
            if (!button || button.disabled) return;
            const row = button.closest("[data-order-route-stop]");
            const deleteInput = row?.querySelector("input[name$='-DELETE']");
            if (!deleteInput) return;
            deleteInput.checked = true;
            refresh();
        });
        form.addEventListener("submit", refresh);
        form.addEventListener("crm:route-refresh", refresh);
        form.querySelectorAll("[data-order-route-add]").forEach((button) => {
            button.addEventListener("click", () => add(button.dataset.orderRouteAdd));
        });
        refresh();
    };

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-order-form], [data-order-route-form]").forEach(enhance);
    });
})();
