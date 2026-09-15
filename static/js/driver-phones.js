(() => {
    "use strict";

    const enhance = (form) => {
        if (!form || form.dataset.driverPhonesReady === "true") return;
        const list = form.querySelector("[data-driver-phone-list]");
        const template = form.querySelector("template[data-driver-phone-empty-form]");
        const totalInput = form.querySelector("input[name='phones-TOTAL_FORMS']");
        if (!list || !template || !totalInput) return;
        form.dataset.driverPhonesReady = "true";

        const rows = () => Array.from(list.querySelectorAll("[data-driver-phone-form]")).filter((row) => !row.hidden);
        const choosePrimary = (selected) => {
            rows().forEach((row) => {
                const radio = row.querySelector("[data-driver-phone-primary]");
                const value = row.querySelector("input[name$='-is_primary']");
                const selectedRow = radio === selected;
                if (radio) radio.checked = selectedRow;
                if (value) value.value = selectedRow ? "on" : "";
                row.classList.toggle("is-current", selectedRow);
            });
        };
        const ensurePrimary = () => {
            const current = rows().find((row) => row.querySelector("[data-driver-phone-primary]")?.checked);
            if (current) choosePrimary(current.querySelector("[data-driver-phone-primary]"));
            else if (rows()[0]) choosePrimary(rows()[0].querySelector("[data-driver-phone-primary]"));
        };

        form.addEventListener("change", (event) => {
            if (event.target.matches("[data-driver-phone-primary]")) choosePrimary(event.target);
        });
        form.addEventListener("click", (event) => {
            const remove = event.target.closest("[data-driver-phone-remove]");
            if (!remove) return;
            event.preventDefault();
            const row = remove.closest("[data-driver-phone-form]");
            const deleted = row?.querySelector("input[name$='-DELETE']");
            if (deleted) deleted.checked = true;
            if (row) row.hidden = true;
            ensurePrimary();
        });
        form.querySelector("[data-driver-phone-add]")?.addEventListener("click", () => {
            const index = Number.parseInt(totalInput.value, 10);
            list.insertAdjacentHTML("beforeend", template.innerHTML.replaceAll("__prefix__", String(index)));
            totalInput.value = String(index + 1);
            const added = list.lastElementChild;
            window.CRMPhoneInputs?.enhanceWithin(added);
            if (!rows().some((row) => row.querySelector("[data-driver-phone-primary]")?.checked)) {
                choosePrimary(added.querySelector("[data-driver-phone-primary]"));
            }
            added?.querySelector("input[name$='-phone']")?.focus();
        });
        ensurePrimary();
    };

    const enhanceWithin = (root = document) => {
        if (root.matches?.("[data-driver-form]")) enhance(root);
        root.querySelectorAll?.("[data-driver-form]").forEach(enhance);
    };

    document.addEventListener("DOMContentLoaded", () => enhanceWithin(document));
    window.CRMDriverPhones = {enhance, enhanceWithin};
})();
