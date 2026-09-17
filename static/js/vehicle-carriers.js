(() => {
    "use strict";

    const enhance = (form) => {
        if (!form || form.dataset.vehicleCarriersReady === "true") return;
        const list = form.querySelector("[data-vehicle-carrier-list]");
        const template = form.querySelector("template[data-vehicle-carrier-empty-form]");
        const totalInput = form.querySelector("input[name='vehicle_carriers-TOTAL_FORMS']");
        if (!list || !template || !totalInput) return;
        form.dataset.vehicleCarriersReady = "true";

        const rows = () => Array.from(list.querySelectorAll("[data-vehicle-carrier-form]"));
        const deleted = (row) => row?.querySelector("input[name$='-DELETE']")?.checked;
        const primaryInputs = () => Array.from(
            list.querySelectorAll("input[name^='vehicle_carriers-'][name$='-is_primary']")
        );
        const activeRows = () => rows().filter((row) => !deleted(row));
        const refresh = () => {
            activeRows().forEach((row) => {
                const remove = row.querySelector("[data-vehicle-carrier-remove]");
                const disabled = activeRows().length <= 1;
                remove?.classList.toggle("is-disabled", disabled);
                remove?.setAttribute("aria-disabled", disabled ? "true" : "false");
                row.classList.toggle(
                    "is-current",
                    Boolean(row.querySelector("input[name$='-is_primary']")?.checked)
                );
            });
        };
        const choosePrimary = (input) => {
            if (input?.checked) {
                primaryInputs().forEach((candidate) => {
                    if (candidate !== input) candidate.checked = false;
                });
            }
            refresh();
        };
        const ensurePrimary = (row) => {
            const hasPrimary = primaryInputs().some((input) => {
                return input.checked && !deleted(input.closest("[data-vehicle-carrier-form]"));
            });
            if (!hasPrimary) {
                const input = row?.querySelector("input[name$='-is_primary']");
                if (input) {
                    input.checked = true;
                    choosePrimary(input);
                }
            }
        };

        form.addEventListener("change", (event) => {
            if (event.target.matches("input[name^='vehicle_carriers-'][name$='-is_primary']")) {
                choosePrimary(event.target);
            } else if (event.target.matches("select[name^='vehicle_carriers-'][name$='-carrier']")) {
                if (event.target.value) ensurePrimary(event.target.closest("[data-vehicle-carrier-form]"));
            }
        });

        form.addEventListener("click", (event) => {
            const remove = event.target.closest("[data-vehicle-carrier-remove]");
            if (!remove) return;
            event.preventDefault();
            if (remove.getAttribute("aria-disabled") === "true") return;
            const row = remove.closest("[data-vehicle-carrier-form]");
            const deleteInput = row?.querySelector("input[name$='-DELETE']");
            const wasPrimary = row?.querySelector("input[name$='-is_primary']")?.checked;
            if (!row || !deleteInput) return;
            deleteInput.checked = true;
            row.hidden = true;
            if (wasPrimary) ensurePrimary(activeRows()[0]);
            refresh();
        });

        form.querySelector("[data-vehicle-carrier-add]")?.addEventListener("click", () => {
            const index = Number.parseInt(totalInput.value, 10);
            list.insertAdjacentHTML(
                "beforeend",
                template.innerHTML.replaceAll("__prefix__", String(index))
            );
            totalInput.value = String(index + 1);
            const added = list.lastElementChild;
            window.CRMUniversalSelects?.enhanceWithin(added);
            (added?.querySelector(".crm-smart-search") || added?.querySelector("select"))?.focus();
            refresh();
        });

        refresh();
    };

    const enhanceWithin = (root = document) => {
        if (root.matches?.("[data-vehicle-form]")) enhance(root);
        root.querySelectorAll?.("[data-vehicle-form]").forEach(enhance);
    };

    document.addEventListener("DOMContentLoaded", () => enhanceWithin(document));
    window.CRMVehicleCarriers = {enhance, enhanceWithin};
})();
