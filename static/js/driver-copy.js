(() => {
    "use strict";

    const notify = (message, kind) => {
        if (window.CRMToasts?.show) window.CRMToasts.show(message, kind, 5000);
        else window.UIkit?.notification?.({
            message,
            status: kind === "error" ? "danger" : kind,
            pos: "top-center",
            timeout: 5000
        });
    };

    const writeClipboard = async (text) => {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
            return;
        }
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.append(textarea);
        textarea.focus();
        textarea.select();
        document.execCommand("copy");
        textarea.remove();
    };

    const activeRow = (form, selector, hiddenName) => Array.from(
        form.querySelectorAll(selector)
    ).find((row) => {
        const hidden = row.querySelector(`input[name$='-${hiddenName}']`);
        return hidden?.checked || ["True", "true", "on"].includes(hidden?.value);
    });
    const rowValue = (row, selector) => row?.querySelector(selector)?.value?.trim() || "";

    const formCopyText = (form) => {
        const value = (selector) => form.querySelector(selector)?.value?.trim() || "";
        const passport = activeRow(form, "[data-passport-form]", "is_current");
        const passportText = passport ? [
            rowValue(passport, "input[name$='-series']"),
            rowValue(passport, "input[name$='-number']"),
            rowValue(passport, "input[name$='-issued_by']"),
            rowValue(passport, "input[name$='-issue_date']"),
        ].filter(Boolean).join(" ") : "";
        const license = activeRow(form, "[data-license-form]", "is_current");
        const licenseNumber = rowValue(license, "input[name$='-number']");
        const licenseDates = [
            rowValue(license, "input[name$='-issue_date']"),
            rowValue(license, "input[name$='-expiry_date']"),
        ].filter(Boolean).join(" - ");
        const phoneRows = Array.from(form.querySelectorAll("[data-driver-phone-form]"))
            .filter((row) => !row.querySelector("input[name$='-DELETE']")?.checked);
        const primaryPhone = phoneRows.find(
            (row) => row.querySelector("[data-driver-phone-primary]")?.checked
        );
        const orderedPhones = [
            primaryPhone,
            ...phoneRows.filter((row) => row !== primaryPhone),
        ].filter(Boolean);
        const phones = orderedPhones
            .map((row) => rowValue(row, "input[name$='-phone']"))
            .filter(Boolean)
            .join(", ");
        const vehicle = form.dataset.driverVehicleText?.trim() || "";
        return [
            value("#id_full_name") ? `ФИО: ${value("#id_full_name")}` : "",
            value("#id_tax_id") ? `ИНН: ${value("#id_tax_id")}` : "",
            passportText ? `ПАСПОРТ: ${passportText}` : "",
            licenseNumber ? `ВУ: ${[licenseNumber, licenseDates].filter(Boolean).join(" ")}` : "",
            phones ? `ТЕЛ: ${phones}` : "",
            vehicle ? `ТС: ${vehicle}` : "",
        ].filter(Boolean).join("\n");
    };

    document.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-driver-copy], .copy-driver-data");
        if (!button || button.disabled) return;
        const form = button.closest("[data-driver-form]");
        const text = form ? formCopyText(form) : (button.dataset.copyText || "");
        if (!text) {
            notify("Нет данных для копирования.", "warning");
            return;
        }
        try {
            await writeClipboard(text);
            notify("Карточка водителя скопирована в буфер обмена.", "success");
        } catch (_error) {
            notify("Не удалось скопировать данные.", "error");
        }
    });
})();
