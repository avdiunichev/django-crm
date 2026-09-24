(() => {
    "use strict";
    const enhance = (root) => {
    if (!root || root.dataset.driverSmartReady === "true") return;
    const modalElement = root.closest(".uk-modal");
    const form = root.closest("[data-driver-form]") || document.querySelector("[data-driver-form]");
    if (!modalElement || !form) return;
    root.dataset.driverSmartReady = "true";
    // A driver card can itself be opened in a modal. Keep the smart-input
    // dialog at document level so it is not hidden together with its parent.
    if (modalElement.parentElement !== document.body) document.body.append(modalElement);

    const source = root.querySelector("[data-driver-smart-source]");
    const resultBox = root.querySelector("[data-driver-smart-result]");
    const applyButton = root.querySelector("[data-driver-smart-apply]");
    let parsed = null;
    const clean = (value) => String(value || "").replace(/\s+/g, " ").trim();
    const date = "(\\d{2}\\.\\d{2}\\.\\d{4})";

    const parse = (raw) => {
        const text = String(raw || "").replace(/\\?\r?\n/g, "\n").replace(/&(?:#x20|nbsp);/gi, " ");
        const flat = clean(text);
        const data = {};
        const fio = flat.match(/(?:^|\s)([А-ЯЁ][а-яё-]+)\s+([А-ЯЁ][а-яё-]+)\s+([А-ЯЁ][а-яё-]+)(?=\s|$)/u);
        if (fio) data.fullName = `${fio[1]} ${fio[2]} ${fio[3]}`;
        const birth = flat.match(new RegExp(`(?:дата\\s+рождения|родил(?:ся|ась)|г\\.?\\s*р\\.?)?\\s*${date}`, "i"));
        if (birth) data.birthDate = birth[1];
        const passport = flat.match(/паспорт\D{0,12}(\d{4})\D{1,8}(\d{6})/i);
        if (passport) { data.passportSeries = passport[1]; data.passportNumber = passport[2]; }
        const issueDate = flat.match(new RegExp(`(?:дата\\s+выдачи|выдан(?:а|о)?(?:\\s+[^\\d]{0,80})?)\\s*${date}`, "i"));
        if (issueDate) data.passportIssueDate = issueDate[1];
        const issuer = text.match(/(?:^|\n)\s*((?:ОТДЕЛ(?:ОМ)?|ОТДЕЛЕНИ(?:ЕМ|Е)|УФМС|МВД)[^\n]*)/im);
        if (issuer) {
            const issuerValue = issuer[1].split(/\s+(?:дата\s+выдачи|код)(?=\s|:|$)/i)[0];
            data.passportIssuedBy = clean(issuerValue).toUpperCase();
        }
        const phone = flat.match(/(?:тел(?:ефон)?\s*[:\-]?\s*)?(?:\+7|8)[\s()\-]*\d{3}[\s()\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}/i);
        if (phone) {
            const digits = phone[0].replace(/\D/g, "").replace(/^8/, "7").slice(-11);
            if (digits.length === 11) data.phone = `+7 ${digits.slice(1, 4)} ${digits.slice(4, 7)}-${digits.slice(7, 9)}-${digits.slice(9)}`;
        }
        const taxId = flat.match(/(?:инн)\D{0,8}(\d{12})/i);
        if (taxId) data.taxId = taxId[1];
        const license = flat.match(/(?:водительск\w*\s+удостоверен\w*|ву|права)\D{0,15}(\d{2})\D?(\d{2})\D?(\d{6})/i);
        if (license) data.licenseNumber = `${license[1]} ${license[2]} ${license[3]}`;
        const found = Object.keys(data).length;
        return {data, found};
    };

    const labels = {fullName: "ФИО", birthDate: "Дата рождения", passportSeries: "Серия паспорта", passportNumber: "Номер паспорта", passportIssuedBy: "Кем выдан", passportIssueDate: "Дата выдачи", phone: "Телефон", taxId: "ИНН", licenseNumber: "Водительское удостоверение"};
    const recognize = () => {
        parsed = parse(source.value);
        resultBox.replaceChildren(); resultBox.hidden = false;
        const heading = document.createElement("h3");
        heading.textContent = parsed.found ? `Распознано полей: ${parsed.found}` : "Автозаполнение невозможно";
        resultBox.append(heading);
        if (parsed.found) {
            const list = document.createElement("dl");
            Object.entries(parsed.data).forEach(([key, value]) => { const dt = document.createElement("dt"); dt.textContent = labels[key]; const dd = document.createElement("dd"); dd.textContent = value; list.append(dt, dd); });
            resultBox.append(list);
            const note = document.createElement("div"); note.className = "is-warning"; note.textContent = "Проверьте распознанные значения перед сохранением карточки."; resultBox.append(note);
        }
        applyButton.disabled = !parsed.found;
    };
    const set = (selector, value) => { if (!value) return; const field = form.querySelector(selector); if (!field) return; field.value = value; field.dispatchEvent(new Event("input", {bubbles: true})); field.dispatchEvent(new Event("change", {bubbles: true})); };
    const apply = () => {
        if (!parsed?.found) return;
        const d = parsed.data;
        set("#id_full_name", d.fullName); set("#id_birth_date", d.birthDate); set("#id_tax_id", d.taxId);
        set("input[name$='-phone']", d.phone);
        set("input[name$='-series']", d.passportSeries); set("input[name$='-number']", d.passportNumber);
        set("input[name$='-issued_by']", d.passportIssuedBy); set("input[name$='-issue_date']", d.passportIssueDate);
        if (d.licenseNumber) set("[data-license-form] input[name$='-number']", d.licenseNumber);
        window.UIkit?.modal(root.closest(".uk-modal"))?.hide();
        form.scrollIntoView({behavior: "smooth", block: "start"});
    };
    root.querySelector("[data-driver-smart-recognize]")?.addEventListener("click", recognize);
    applyButton?.addEventListener("click", apply);
    };

    const enhanceWithin = (scope = document) => {
        if (scope.matches?.("[data-driver-smart-input]")) enhance(scope);
        scope.querySelectorAll?.("[data-driver-smart-input]").forEach(enhance);
    };
    document.addEventListener("DOMContentLoaded", () => enhanceWithin(document));
    window.CRMDriverSmartInput = {enhanceWithin};
})();
