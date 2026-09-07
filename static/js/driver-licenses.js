(() => {
    "use strict";

    const enhance = (form) => {
        if (!form || form.dataset.driverLicensesReady === "true") return;
        const list = form.querySelector("[data-license-list]");
        const template = form.querySelector("template[data-license-empty-form]");
        const totalInput = form.querySelector("input[name='licenses-TOTAL_FORMS']");
        if (!list || !template || !totalInput) return;
        form.dataset.driverLicensesReady = "true";

        const currentInputs = () => Array.from(
            list.querySelectorAll("input[name^='licenses-'][name$='-is_current']")
        );
        const chooseCurrent = (selected) => {
            if (selected.checked) {
                currentInputs().forEach((input) => {
                    if (input !== selected) input.checked = false;
                    input.closest("[data-license-form]")?.classList.toggle(
                        "is-current", input.checked
                    );
                });
            } else {
                selected.closest("[data-license-form]")?.classList.remove("is-current");
            }
        };

        form.addEventListener("change", (event) => {
            if (event.target.matches("input[name^='licenses-'][name$='-is_current']")) {
                chooseCurrent(event.target);
            }
        });

        form.addEventListener("input", (event) => {
            if (!event.target.matches("input[name^='licenses-'][name$='-number']")) return;
            const row = event.target.closest("[data-license-form]");
            if (!row || row.dataset.currentChosen === "true") return;
            const idInput = row.querySelector("input[name$='-id']");
            if (idInput?.value || !event.target.value.trim()) return;
            row.dataset.currentChosen = "true";
            const current = row.querySelector("input[name$='-is_current']");
            if (current) {
                current.checked = true;
                chooseCurrent(current);
            }
        });

        form.querySelector("[data-license-add]")?.addEventListener("click", () => {
            const index = Number.parseInt(totalInput.value, 10);
            list.insertAdjacentHTML(
                "beforeend",
                template.innerHTML.replaceAll("__prefix__", String(index))
            );
            totalInput.value = String(index + 1);
            const added = list.lastElementChild;
            window.CRMDateInputs?.enhanceWithin?.(added);
            added?.querySelector("input[name$='-number']")?.focus();
        });
    };

    const enhanceWithin = (root = document) => {
        if (root.matches?.("[data-driver-form]")) enhance(root);
        root.querySelectorAll?.("[data-driver-form]").forEach(enhance);
    };

    document.addEventListener("DOMContentLoaded", () => enhanceWithin(document));
    window.CRMDriverLicenses = {enhance, enhanceWithin};
})();
