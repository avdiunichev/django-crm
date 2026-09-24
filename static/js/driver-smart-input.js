(() => {
    "use strict";
    const enhance = (root) => {
    if (!root || root.dataset.driverSmartReady === "true") return;
    const modalElement = root.closest(".uk-modal");
    const form = root.closest("[data-driver-form]") || document.querySelector("[data-driver-form]");
    if (!modalElement || !form) return;
    root.dataset.driverSmartReady = "true";
    document.querySelectorAll("#driver-smart-input-modal").forEach((existing) => {
        if (existing !== modalElement) {
            window.UIkit?.getComponent?.(existing, "modal")?.$destroy();
            existing.remove();
        }
    });
    // A driver card can itself be opened in a modal. Keep the smart-input
    // dialog at document level so it is not hidden together with its parent.
    if (modalElement.parentElement !== document.body) document.body.append(modalElement);
    window.UIkit?.modal(modalElement, {stack: true, bgClose: false, escClose: false});

    const source = root.querySelector("[data-driver-smart-source]");
    const resultBox = root.querySelector("[data-driver-smart-result]");
    const applyButton = root.querySelector("[data-driver-smart-apply]");
    let parsed = null;
    const clean = (value) => String(value || "").replace(/\s+/g, " ").trim();
    const titleCaseName = (value) => value.toLocaleLowerCase("ru-RU").replace(/(^|[-\s])([а-яё])/giu, (_, prefix, letter) => `${prefix}${letter.toLocaleUpperCase("ru-RU")}`);
    const decodeText = (raw) => {
        const decoder = document.createElement("textarea");
        decoder.innerHTML = String(raw || "");
        return decoder.value.replace(/\*\*/g, "").replace(/\u00a0/g, " ").replace(/\r?\n/g, "\n");
    };
    const date = "(\\d{2}\\.\\d{2}\\.\\d{4})";

    const parse = (raw) => {
        const text = decodeText(raw);
        const flat = clean(text);
        const data = {};
        const fio = flat.match(/(?:^|\s)([А-ЯЁ][А-ЯЁа-яё-]+)\s+([А-ЯЁ][А-ЯЁа-яё-]+)\s+([А-ЯЁ][А-ЯЁа-яё-]+)(?=\s|$)/u);
        if (fio) data.fullName = titleCaseName(`${fio[1]} ${fio[2]} ${fio[3]}`);
        const explicitBirth = flat.match(new RegExp(`(?:дата\\s+рождения|родил(?:ся|ась)|г\\.?\\s*р\\.?)\\s*[:,-]?\\s*${date}`, "i"));
        const dateAfterName = fio ? flat.slice(fio.index + fio[0].length).match(new RegExp(`^\\s*[,;]?\\s*${date}`)) : null;
        const birth = explicitBirth || dateAfterName;
        if (birth) data.birthDate = birth[1];
        const passport = flat.match(/(?:паспорт\D{0,12})?(\d{4})[\s-]+(\d{6})(?=\s|$)/i);
        if (passport) { data.passportSeries = passport[1]; data.passportNumber = passport[2]; }
        const issueDate = flat.match(new RegExp(`(?:дата\\s+выдачи|выдан(?:а|о)?(?:\\s+[^\\d]{0,80})?|[,;]?\\s+от)\\s*${date}`, "i"));
        if (issueDate) data.passportIssueDate = issueDate[1];
        const issuer = flat.match(/((?:ОТДЕЛ(?:ОМ)?|ОТДЕЛЕНИ(?:ЕМ|Е)|УФМС|УМВД|МВД)\s+.*?)(?=\s*[,;]?\s+(?:дата\s+выдачи|от)\s+\d{2}\.\d{2}\.\d{4}|\s+(?:вод\.?\s*удостоверение|ву|права|тел\.?|$))/i);
        if (issuer) {
            const issuerValue = issuer[1].split(/\s+(?:дата\s+выдачи|код)(?=\s|:|$)/i)[0].replace(/[,.\s]+$/, "");
            data.passportIssuedBy = clean(issuerValue).toUpperCase();
        }
        const phone = flat.match(/(?:тел(?:ефон)?\s*[:\-]?\s*)?(?:\+7|8)[\s()\-]*\d{3}[\s()\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}/i);
        if (phone) {
            const digits = phone[0].replace(/\D/g, "").replace(/^8/, "7").slice(-11);
            if (digits.length === 11) data.phone = `+7 ${digits.slice(1, 4)} ${digits.slice(4, 7)}-${digits.slice(7, 9)}-${digits.slice(9)}`;
        }
        const taxId = flat.match(/(?:инн)\D{0,8}(\d{12})/i);
        if (taxId) data.taxId = taxId[1];
        const license = flat.match(/(?:вод(?:ительск)?\.?\s*удостоверен\w*|ву|права)\D{0,20}(\d{2})\D?(\d{2})\D?(\d{6})/i);
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
    const set = (selector, value) => { if (!value) return; const field = form.querySelector(selector); if (!field) return; field.value = value; field.dispatchEvent(new Event("change", {bubbles: true})); };
    const apply = () => {
        if (!parsed?.found) return;
        const d = parsed.data;
        set("#id_full_name", d.fullName); set("#id_birth_date", d.birthDate); set("#id_tax_id", d.taxId);
        set("[data-driver-phone-form]:not([hidden]) input[name$='-phone']", d.phone);
        set("[data-passport-form]:not([hidden]) input[name$='-series']", d.passportSeries); set("[data-passport-form]:not([hidden]) input[name$='-number']", d.passportNumber);
        set("[data-passport-form]:not([hidden]) input[name$='-issued_by']", d.passportIssuedBy); set("[data-passport-form]:not([hidden]) input[name$='-issue_date']", d.passportIssueDate);
        if (d.licenseNumber) set("[data-license-form] input[name$='-number']", d.licenseNumber);
        window.UIkit?.modal(root.closest(".uk-modal"))?.hide();
        form.scrollIntoView({behavior: "smooth", block: "start"});
    };
    root.querySelector("[data-driver-smart-recognize]")?.addEventListener("click", recognize);
    applyButton?.addEventListener("click", apply);
    source.addEventListener("input", () => { parsed = null; applyButton.disabled = true; resultBox.hidden = true; });
    };

    const enhanceWithin = (scope = document) => {
        if (scope.matches?.("[data-driver-smart-input]")) enhance(scope);
        scope.querySelectorAll?.("[data-driver-smart-input]").forEach(enhance);
    };
    document.addEventListener("DOMContentLoaded", () => enhanceWithin(document));
    window.CRMDriverSmartInput = {enhanceWithin};
})();
