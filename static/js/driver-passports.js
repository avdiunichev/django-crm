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

        const visibleRows = () => Array.from(
            list.querySelectorAll("[data-passport-form]")
        ).filter((row) => !row.querySelector("input[name$='-DELETE']")?.checked);

        const parseDateValue = (value) => {
            const text = (value || "").trim();
            let match = text.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
            if (match) return Number(`${match[3]}${match[2]}${match[1]}`);
            match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
            if (match) return Number(`${match[1]}${match[2]}${match[3]}`);
            return 0;
        };

        const chooseCurrent = (selected, {manual = false} = {}) => {
            if (!selected) return;
            selected.checked = true;
            const selectedRow = selected.closest("[data-passport-form]");
            currentInputs().forEach((input) => {
                const row = input.closest("[data-passport-form]");
                input.checked = row === selectedRow;
                row?.classList.toggle("is-current", input.checked);
                const radio = row?.querySelector("[data-passport-current-radio]");
                if (radio) radio.checked = input.checked;
            });
            if (manual && selectedRow) selectedRow.dataset.currentManual = "true";
        };

        const autoChooseByIssueDate = () => {
            const manual = list.querySelector("[data-passport-form][data-current-manual='true'] input[name$='-is_current']");
            if (manual) {
                chooseCurrent(manual);
                return;
            }
            const rows = visibleRows();
            let best = null;
            rows.forEach((row) => {
                const hasIdentity = row.querySelector("input[name$='-series']")?.value.trim()
                    || row.querySelector("input[name$='-number']")?.value.trim();
                if (!hasIdentity) return;
                const dateScore = parseDateValue(row.querySelector("input[name$='-issue_date']")?.value);
                if (!best || dateScore > best.dateScore) {
                    best = {row, dateScore};
                }
            });
            const input = best?.row.querySelector("input[name$='-is_current']");
            if (input) chooseCurrent(input);
        };

        form.addEventListener("change", (event) => {
            if (event.target.matches("[data-passport-current-radio]")) {
                const current = event.target
                    .closest("[data-passport-form]")
                    ?.querySelector("input[name$='-is_current']");
                chooseCurrent(current, {manual: true});
            }
            if (event.target.matches("[data-driver-document-country]")) {
                formatPassportRow(event.target.closest("[data-passport-form]"));
            }
            if (event.target.matches("input[name$='-issue_date'], input[name$='-DELETE']")) {
                autoChooseByIssueDate();
            }
        });

        form.addEventListener("input", (event) => {
            if (event.target.matches("[data-driver-passport-series], [data-driver-passport-number]")) {
                formatPassportRow(event.target.closest("[data-passport-form]"));
            }
            if (event.target.matches("[data-uppercase]")) {
                event.target.value = event.target.value.toUpperCase();
            }
            if (!event.target.matches("input[name$='-series'], input[name$='-number'], input[name$='-issue_date']")) return;
            const passportForm = event.target.closest("[data-passport-form]");
            if (!passportForm || passportForm.dataset.currentManual === "true") return;
            if (!event.target.value.trim()) return;
            autoChooseByIssueDate();
        });

        form.querySelector("[data-passport-add]")?.addEventListener("click", () => {
            const index = Number.parseInt(totalInput.value, 10);
            const html = template.innerHTML.replaceAll("__prefix__", String(index));
            list.insertAdjacentHTML("beforeend", html);
            totalInput.value = String(index + 1);
            const added = list.lastElementChild;
            window.CRMDriverSuggestions?.enhanceWithin(added);
            window.CRMDateInputs?.enhanceWithin?.(added);
            formatPassportRow(added);
            autoChooseByIssueDate();
            added?.querySelector("input[name$='-series']")?.focus();
        });

        formatAllRows();
        autoChooseByIssueDate();
    };

    const enhanceWithin = (root = document) => {
        if (root.matches?.("[data-driver-form]")) enhance(root);
        root.querySelectorAll?.("[data-driver-form]").forEach(enhance);
    };

    document.addEventListener("DOMContentLoaded", () => enhanceWithin(document));
    window.CRMDriverPassports = {enhance, enhanceWithin};
})();
