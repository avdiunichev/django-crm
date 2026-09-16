(() => {
    "use strict";

    const enhance = (form) => {
        if (!form || form.dataset.driverLicensesReady === "true") return;
        const list = form.querySelector("[data-license-list]");
        const template = form.querySelector("template[data-license-empty-form]");
        const totalInput = form.querySelector("input[name='licenses-TOTAL_FORMS']");
        if (!list || !template || !totalInput) return;
        form.dataset.driverLicensesReady = "true";

        const isRussia = (row) => (
            row?.querySelector("[data-driver-document-country]")?.value || "RU"
        ) === "RU";

        const formatLicenseNumber = (input) => {
            const row = input?.closest("[data-license-form]");
            const russian = isRussia(row);
            if (!input) return;
            input.placeholder = russian ? "00 00 000000" : "Номер удостоверения";
            input.inputMode = russian ? "numeric" : "text";
            if (russian) {
                const digits = input.value.replace(/\D/g, "").slice(0, 10);
                input.value = [
                    digits.slice(0, 2),
                    digits.slice(2, 4),
                    digits.slice(4, 10),
                ].filter(Boolean).join(" ");
            } else {
                input.value = input.value.toUpperCase();
            }
        };

        const formatAllRows = () => {
            list.querySelectorAll("[data-driver-license-number]").forEach(formatLicenseNumber);
        };

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
            if (event.target.matches("[data-driver-document-country]")) {
                const input = event.target
                    .closest("[data-license-form]")
                    ?.querySelector("[data-driver-license-number]");
                formatLicenseNumber(input);
            }
        });

        form.addEventListener("input", (event) => {
            if (event.target.matches("[data-driver-license-number]")) {
                formatLicenseNumber(event.target);
            }
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
            formatLicenseNumber(added?.querySelector("[data-driver-license-number]"));
            added?.querySelector("input[name$='-number']")?.focus();
        });

        formatAllRows();
    };

    const enhanceWithin = (root = document) => {
        if (root.matches?.("[data-driver-form]")) enhance(root);
        root.querySelectorAll?.("[data-driver-form]").forEach(enhance);
    };

    document.addEventListener("DOMContentLoaded", () => enhanceWithin(document));
    window.CRMDriverLicenses = {enhance, enhanceWithin};
})();
