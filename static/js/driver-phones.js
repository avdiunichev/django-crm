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
        const updateRemoveState = () => {
            const activeRows = rows();
            activeRows.forEach((row) => {
                const remove = row.querySelector("[data-driver-phone-remove]");
                const disabled = activeRows.length <= 1;
                if (!remove) return;
                remove.classList.toggle("is-disabled", disabled);
                remove.setAttribute("aria-disabled", disabled ? "true" : "false");
                remove.disabled = disabled;
            });
        };
        const choosePrimary = (selected) => {
            rows().forEach((row) => {
                const radio = row.querySelector("[data-driver-phone-primary]");
                const value = row.querySelector("input[name$='-is_primary']");
                const selectedRow = radio === selected;
                if (radio) radio.checked = selectedRow;
                if (value) value.value = selectedRow ? "on" : "";
                row.classList.toggle("is-current", selectedRow);
            });
            updateRemoveState();
        };
        const ensurePrimary = () => {
            const current = rows().find((row) => row.querySelector("[data-driver-phone-primary]")?.checked);
            if (current) choosePrimary(current.querySelector("[data-driver-phone-primary]"));
            else if (rows()[0]) choosePrimary(rows()[0].querySelector("[data-driver-phone-primary]"));
        };
        const addPhoneRow = ({focus = true} = {}) => {
            const index = Number.parseInt(totalInput.value, 10);
            list.insertAdjacentHTML("beforeend", template.innerHTML.replaceAll("__prefix__", String(index)));
            totalInput.value = String(index + 1);
            const added = list.lastElementChild;
            window.CRMPhoneInputs?.enhanceWithin(added);
            if (!rows().some((row) => row.querySelector("[data-driver-phone-primary]")?.checked)) {
                choosePrimary(added.querySelector("[data-driver-phone-primary]"));
            }
            updateRemoveState();
            if (focus) added?.querySelector("input[name$='-phone']")?.focus();
            return added;
        };

        form.addEventListener("change", (event) => {
            if (event.target.matches("[data-driver-phone-primary]")) choosePrimary(event.target);
        });
        form.addEventListener("click", (event) => {
            const remove = event.target.closest("[data-driver-phone-remove]");
            if (!remove) return;
            event.preventDefault();
            if (remove.getAttribute("aria-disabled") === "true" || rows().length <= 1) {
                updateRemoveState();
                return;
            }
            const row = remove.closest("[data-driver-phone-form]");
            const deleted = row?.querySelector("input[name$='-DELETE']");
            if (deleted) deleted.checked = true;
            if (row) row.hidden = true;
            ensurePrimary();
            updateRemoveState();
        });
        form.querySelector("[data-driver-phone-add]")?.addEventListener("click", () => {
            addPhoneRow();
        });
        if (rows().length === 0) addPhoneRow({focus: false});
        ensurePrimary();
        updateRemoveState();
    };

    const enhanceWithin = (root = document) => {
        if (root.matches?.("[data-driver-form]")) enhance(root);
        root.querySelectorAll?.("[data-driver-form]").forEach(enhance);
    };

    document.addEventListener("DOMContentLoaded", () => enhanceWithin(document));
    window.CRMDriverPhones = {enhance, enhanceWithin};
})();
