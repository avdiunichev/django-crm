(() => {
    "use strict";

    const enhance = (form) => {
        if (!form || form.dataset.driverCarriersReady === "true") return;
        const list = form.querySelector("[data-employment-list]");
        const template = form.querySelector("template[data-employment-empty-form]");
        const totalInput = form.querySelector("input[name='employments-TOTAL_FORMS']");
        if (!list || !template || !totalInput) return;
        form.dataset.driverCarriersReady = "true";

        const primaryInputs = () => Array.from(
            list.querySelectorAll("input[name^='employments-'][name$='-is_primary']")
        );
        const isDeleted = (row) => row?.querySelector("input[name$='-DELETE']")?.checked;
        const refreshCards = () => {
            primaryInputs().forEach((input) => {
                const row = input.closest("[data-employment-form]");
                row?.classList.toggle("is-current", input.checked && !isDeleted(row));
            });
        };
        const choosePrimary = (selected) => {
            if (selected.checked) {
                primaryInputs().forEach((input) => {
                    if (input !== selected) input.checked = false;
                });
            }
            refreshCards();
        };
        const hasPrimary = () => primaryInputs().some((input) => {
            const row = input.closest("[data-employment-form]");
            return input.checked && !isDeleted(row);
        });

        form.addEventListener("change", (event) => {
            if (event.target.matches("input[name^='employments-'][name$='-is_primary']")) {
                choosePrimary(event.target);
                return;
            }
            if (event.target.matches("select[name^='employments-'][name$='-carrier']")) {
                const row = event.target.closest("[data-employment-form]");
                const primary = row?.querySelector("input[name$='-is_primary']");
                if (event.target.value && primary && !hasPrimary()) {
                    primary.checked = true;
                    choosePrimary(primary);
                }
                return;
            }
            if (event.target.matches("input[name^='employments-'][name$='-DELETE']")) {
                refreshCards();
            }
        });

        form.querySelector("[data-employment-add]")?.addEventListener("click", () => {
            const index = Number.parseInt(totalInput.value, 10);
            list.insertAdjacentHTML(
                "beforeend",
                template.innerHTML.replaceAll("__prefix__", String(index))
            );
            totalInput.value = String(index + 1);
            const added = list.lastElementChild;
            window.CRMUniversalSelects?.enhanceWithin(added);
            const search = added?.querySelector(".crm-smart-search");
            const select = added?.querySelector("select[name$='-carrier']");
            (search || select)?.focus();
        });

        refreshCards();
    };

    const enhanceWithin = (root = document) => {
        if (root.matches?.("[data-driver-form]")) enhance(root);
        root.querySelectorAll?.("[data-driver-form]").forEach(enhance);
    };

    document.addEventListener("DOMContentLoaded", () => enhanceWithin(document));
    window.CRMDriverCarriers = {enhance, enhanceWithin};
})();
