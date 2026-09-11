(() => {
    "use strict";

    const form = document.querySelector("[data-order-form]");
    const cancelButton = document.querySelector("[data-order-cancel]");
    const modal = document.querySelector("[data-order-cancel-modal]");
    if (!form || !cancelButton || !modal) return;

    const changesList = modal.querySelector("[data-order-cancel-changes]");
    const emptyState = modal.querySelector("[data-order-cancel-empty]");
    const confirmLink = modal.querySelector("[data-order-cancel-confirm]");
    const snapshot = new Map();

    const isTrackable = (field) => (
        field.matches("input, select, textarea")
        && field.type !== "hidden"
        && field.type !== "submit"
        && field.type !== "button"
        && !field.name.endsWith("-DELETE")
        && !field.name.endsWith("-sequence")
        && !field.name.endsWith("-kind")
    );

    const valueOf = (field) => {
        if (field.type === "checkbox" || field.type === "radio") return field.checked ? "1" : "0";
        return field.value.trim();
    };

    const labelFor = (field) => {
        const label = field.closest(".field")?.querySelector("label")?.textContent?.replace(/\*/g, "").trim();
        const routeStop = field.closest("[data-order-route-stop]");
        if (!routeStop) return label || "Поле формы";
        const routeTitle = routeStop.querySelector("[data-route-title]")?.textContent?.trim() || "Точка маршрута";
        const routeNumber = routeStop.querySelector("[data-route-number]")?.textContent?.trim();
        return `${routeTitle}${routeNumber ? ` №${routeNumber}` : ""}: ${label || "поле"}`;
    };

    const rememberInitialValues = () => {
        form.querySelectorAll("input, select, textarea").forEach((field) => {
            if (isTrackable(field)) snapshot.set(field, valueOf(field));
        });
    };

    const collectChanges = () => {
        const changes = [];
        form.querySelectorAll("input, select, textarea").forEach((field) => {
            if (!isTrackable(field)) return;
            if (!snapshot.has(field) || snapshot.get(field) !== valueOf(field)) {
                changes.push(`Изменено: ${labelFor(field)}`);
            }
        });
        form.querySelectorAll("[data-order-route-stop]").forEach((row) => {
            const deleteInput = row.querySelector("input[name$='-DELETE']");
            if (!deleteInput?.checked) return;
            const title = row.querySelector("[data-route-title]")?.textContent?.trim() || "Точка маршрута";
            const number = row.querySelector("[data-route-number]")?.textContent?.trim();
            changes.push(`Удалена: ${title}${number ? ` №${number}` : ""}`);
        });
        return [...new Set(changes)];
    };

    const closeModal = () => { modal.hidden = true; };

    cancelButton.addEventListener("click", (event) => {
        event.preventDefault();
        const changes = collectChanges();
        changesList.replaceChildren(...changes.map((change) => {
            const item = document.createElement("li");
            item.textContent = change;
            return item;
        }));
        emptyState.hidden = changes.length > 0;
        confirmLink.href = cancelButton.dataset.orderCancelUrl;
        modal.hidden = false;
    });

    modal.querySelectorAll("[data-order-cancel-dismiss]").forEach((button) => button.addEventListener("click", closeModal));
    rememberInitialValues();
})();
