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
        const visibleRows = () => Array.from(
            list.querySelectorAll("[data-license-form]")
        ).filter((row) => !row.querySelector("input[name$='-DELETE']")?.checked);

        const parseDateValue = (value) => {
            const text = (value || "").trim();
            let match = text.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
            if (match) return Number(`${match[3]}${match[2]}${match[1]}`);
            match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
            if (match) return Number(`${match[1]}${match[2]}${match[3]}`);
            return 0;
        };

        const parseDisplayDate = (value) => {
            const match = String(value || "").trim().match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
            if (!match) return null;
            const date = new Date(Number(match[3]), Number(match[2]) - 1, Number(match[1]));
            return date.getFullYear() === Number(match[3])
                && date.getMonth() === Number(match[2]) - 1
                && date.getDate() === Number(match[1]) ? date : null;
        };

        const displayDate = (date) => [
            String(date.getDate()).padStart(2, "0"),
            String(date.getMonth() + 1).padStart(2, "0"),
            date.getFullYear(),
        ].join(".");

        const tenYearsLater = (issued) => {
            const result = new Date(issued.getFullYear() + 10, issued.getMonth(), issued.getDate());
            // 29 February becomes 28 February when the target year is not leap.
            if (result.getMonth() !== issued.getMonth()) result.setDate(0);
            return result;
        };

        const fillExpiryFromIssueDate = (row) => {
            const issue = row?.querySelector("input[name$='-issue_date']");
            const expiry = row?.querySelector("input[name$='-expiry_date']");
            const issued = parseDisplayDate(issue?.value);
            if (!issued || !expiry || (expiry.value.trim() && row.dataset.expiryManual === "true")) return;
            const value = displayDate(tenYearsLater(issued));
            if (expiry.value === value) return;
            row.dataset.applyingExpiry = "true";
            row.dataset.expiryAuto = "true";
            expiry.value = value;
            expiry.dispatchEvent(new Event("change", {bubbles: true}));
            delete row.dataset.applyingExpiry;
        };

        const chooseCurrent = (selected, {manual = false} = {}) => {
            if (!selected) return;
            selected.checked = true;
            const selectedRow = selected.closest("[data-license-form]");
            currentInputs().forEach((input) => {
                const row = input.closest("[data-license-form]");
                input.checked = row === selectedRow;
                input.value = input.checked ? "True" : "False";
                row?.classList.toggle("is-current", input.checked);
                const radio = row?.querySelector("[data-license-current-radio]");
                if (radio) radio.checked = input.checked;
            });
            if (manual && selectedRow) selectedRow.dataset.currentManual = "true";
        };

        const autoChooseByDate = () => {
            const manual = list.querySelector("[data-license-form][data-current-manual='true'] input[name$='-is_current']");
            if (manual) {
                chooseCurrent(manual);
                return;
            }
            let best = null;
            visibleRows().forEach((row) => {
                if (!row.querySelector("input[name$='-number']")?.value.trim()) return;
                const expiryScore = parseDateValue(row.querySelector("input[name$='-expiry_date']")?.value);
                const issueScore = parseDateValue(row.querySelector("input[name$='-issue_date']")?.value);
                if (!best || expiryScore > best.expiryScore || (expiryScore === best.expiryScore && issueScore > best.issueScore)) {
                    best = {row, expiryScore, issueScore};
                }
            });
            const input = best?.row.querySelector("input[name$='-is_current']");
            if (input) chooseCurrent(input);
        };

        form.addEventListener("change", (event) => {
            if (event.target.matches("[data-license-current-radio]")) {
                const current = event.target
                    .closest("[data-license-form]")
                    ?.querySelector("input[name$='-is_current']");
                chooseCurrent(current, {manual: true});
            }
            if (event.target.matches("[data-driver-document-country]")) {
                const input = event.target
                    .closest("[data-license-form]")
                    ?.querySelector("[data-driver-license-number]");
                formatLicenseNumber(input);
            }
            if (event.target.matches("input[name$='-issue_date'], input[name$='-expiry_date'], input[name$='-DELETE']")) {
                const row = event.target.closest("[data-license-form]");
                if (event.target.matches("input[name$='-issue_date']")) fillExpiryFromIssueDate(row);
                if (event.target.matches("input[name$='-expiry_date']") && row && row.dataset.applyingExpiry !== "true") {
                    row.dataset.expiryManual = "true";
                    delete row.dataset.expiryAuto;
                }
                autoChooseByDate();
            }
        });

        form.addEventListener("input", (event) => {
            if (event.target.matches("[data-driver-license-number]")) {
                formatLicenseNumber(event.target);
            }
            if (!event.target.matches("input[name^='licenses-'][name$='-number'], input[name$='-issue_date'], input[name$='-expiry_date']")) return;
            const row = event.target.closest("[data-license-form]");
            if (!row || row.dataset.currentManual === "true") return;
            if (event.target.matches("input[name$='-issue_date']")) fillExpiryFromIssueDate(row);
            if (event.target.matches("input[name$='-expiry_date']") && row.dataset.applyingExpiry !== "true") {
                row.dataset.expiryManual = "true";
                delete row.dataset.expiryAuto;
            }
            if (!event.target.value.trim()) return;
            autoChooseByDate();
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
            fillExpiryFromIssueDate(added);
            autoChooseByDate();
            added?.querySelector("input[name$='-number']")?.focus();
        });

        formatAllRows();
        visibleRows().forEach((row) => {
            // Existing expiry dates are treated as user-approved values.
            // Auto-fill is only applied to an empty expiry field.
            if (row.querySelector("input[name$='-expiry_date']")?.value.trim()) {
                row.dataset.expiryManual = "true";
            } else {
                fillExpiryFromIssueDate(row);
            }
        });
        autoChooseByDate();
    };

    const enhanceWithin = (root = document) => {
        if (root.matches?.("[data-driver-form]")) enhance(root);
        root.querySelectorAll?.("[data-driver-form]").forEach(enhance);
    };

    document.addEventListener("DOMContentLoaded", () => enhanceWithin(document));
    window.CRMDriverLicenses = {enhance, enhanceWithin};
})();
