(() => {
    "use strict";

    const enhance = (form) => {
        if (!form || form.dataset.driverPassportsReady === "true") return;
        form.dataset.driverPassportsReady = "true";

        const list = form.querySelector("[data-passport-list]");
        const template = form.querySelector("template[data-passport-empty-form]");
        const totalInput = form.querySelector("input[name='passports-TOTAL_FORMS']");
        if (!list || !template || !totalInput) return;

        const isRussia = (row) => (
            row?.querySelector("[data-driver-document-country]")?.value || "RU"
        ) === "RU";

        const formatPassportRow = (row) => {
            if (!row) return;
            const russian = isRussia(row);
            const series = row.querySelector("[data-driver-passport-series]");
            const number = row.querySelector("[data-driver-passport-number]");
            if (series) {
                series.inputMode = russian ? "numeric" : "text";
                series.placeholder = russian ? "0000" : "Серия / ID";
                series.maxLength = russian ? 4 : 30;
                series.value = russian
                    ? series.value.replace(/\D/g, "").slice(0, 4)
                    : series.value.toUpperCase();
            }
            if (number) {
                number.inputMode = russian ? "numeric" : "text";
                number.placeholder = russian ? "000000" : "Номер документа";
                number.maxLength = russian ? 6 : 30;
                number.value = russian
                    ? number.value.replace(/\D/g, "").slice(0, 6)
                    : number.value.toUpperCase();
            }
        };

        const formatAllRows = () => {
            list.querySelectorAll("[data-passport-form]").forEach(formatPassportRow);
        };

        const currentInputs = () => Array.from(
            list.querySelectorAll("input[name$='-is_current']")
        );

        const chooseCurrent = (selected) => {
            if (!selected.checked) return;
            currentInputs().forEach((input) => {
                if (input !== selected) input.checked = false;
                input.closest("[data-passport-form]")?.classList.toggle(
                    "is-current", input.checked
                );
            });
            selected.closest("[data-passport-form]")?.classList.add("is-current");
        };

        form.addEventListener("change", (event) => {
            if (event.target.matches("input[name$='-is_current']")) {
                chooseCurrent(event.target);
            }
            if (event.target.matches("[data-driver-document-country]")) {
                formatPassportRow(event.target.closest("[data-passport-form]"));
            }
        });

        form.addEventListener("input", (event) => {
            if (event.target.matches("[data-driver-passport-series], [data-driver-passport-number]")) {
                formatPassportRow(event.target.closest("[data-passport-form]"));
            }
            if (event.target.matches("[data-uppercase]")) {
                event.target.value = event.target.value.toUpperCase();
            }
            if (!event.target.matches("input[name$='-series'], input[name$='-number']")) return;
            const passportForm = event.target.closest("[data-passport-form]");
            if (!passportForm || passportForm.dataset.currentChosen === "true") return;
            const idInput = passportForm.querySelector("input[name$='-id']");
            if (idInput?.value || !event.target.value.trim()) return;
            passportForm.dataset.currentChosen = "true";
            const current = passportForm.querySelector("input[name$='-is_current']");
            if (current) {
                current.checked = true;
                chooseCurrent(current);
            }
        });

        form.querySelector("[data-passport-add]")?.addEventListener("click", () => {
            const index = Number.parseInt(totalInput.value, 10);
            const html = template.innerHTML.replaceAll("__prefix__", String(index));
            list.insertAdjacentHTML("beforeend", html);
            totalInput.value = String(index + 1);
            const added = list.lastElementChild;
            window.CRMDriverSuggestions?.enhanceWithin(added);
            formatPassportRow(added);
            added?.querySelector("input[name$='-series']")?.focus();
        });

        formatAllRows();
    };

    const enhanceWithin = (root = document) => {
        if (root.matches?.("[data-driver-form]")) enhance(root);
        root.querySelectorAll?.("[data-driver-form]").forEach(enhance);
    };

    document.addEventListener("DOMContentLoaded", () => enhanceWithin(document));
    window.CRMDriverPassports = {enhance, enhanceWithin};
})();
