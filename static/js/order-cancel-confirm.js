(() => {
    "use strict";

    const form = document.querySelector("[data-order-form]");
    const cancelButtons = document.querySelectorAll("[data-order-cancel]");
    const modal = document.querySelector("[data-order-cancel-modal]");
    if (!form || !cancelButtons.length || !modal) return;

    const confirmLink = modal.querySelector("[data-order-cancel-confirm]");
    const saveButton = document.querySelector("[data-order-save]");
    const modalSaveButton = modal.querySelector("[data-order-cancel-save]");
    const snapshot = new Map();
    const routeDeletionSnapshot = new Map();

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

    const rememberInitialValues = () => {
        form.querySelectorAll("input, select, textarea").forEach((field) => {
            if (isTrackable(field)) snapshot.set(field, valueOf(field));
        });
        form.querySelectorAll("input[name$='-DELETE']").forEach((field) => routeDeletionSnapshot.set(field, field.checked));
    };

    const hasUnsavedChanges = () => {
        let changed = false;
        form.querySelectorAll("input, select, textarea").forEach((field) => {
            if (isTrackable(field) && (!snapshot.has(field) || snapshot.get(field) !== valueOf(field))) changed = true;
        });
        form.querySelectorAll("input[name$='-DELETE']").forEach((field) => {
            if (!routeDeletionSnapshot.has(field) || routeDeletionSnapshot.get(field) !== field.checked) changed = true;
        });
        return changed;
    };

    const isEmptyOrder = () => {
        const client = form.querySelector("#id_client");
        const cargoName = form.querySelector("#id_cargo_name");
        return !client?.value.trim() && !cargoName?.value.trim();
    };

    const closeModal = () => { modal.hidden = true; };

    const requestLeave = (url) => {
        if (isEmptyOrder() || !hasUnsavedChanges()) {
            window.location.assign(url);
            return;
        }
        confirmLink.href = url;
        modal.hidden = false;
    };

    cancelButtons.forEach((cancelButton) => cancelButton.addEventListener("click", (event) => {
        event.preventDefault();
        requestLeave(cancelButton.dataset.orderCancelUrl);
    }));

    document.querySelectorAll(".crm-topnav a[href]").forEach((link) => {
        link.addEventListener("click", (event) => {
            const url = link.href;
            if (!url || link.getAttribute("href") === "#" || url === window.location.href) return;
            event.preventDefault();
            requestLeave(url);
        });
    });

    modal.querySelectorAll("[data-order-cancel-dismiss]").forEach((button) => button.addEventListener("click", closeModal));
    modalSaveButton?.addEventListener("click", () => {
        closeModal();
        if (form.requestSubmit && saveButton) form.requestSubmit(saveButton);
        else form.submit();
    });
    rememberInitialValues();
})();
