(() => {
    "use strict";

    const enhance = (root) => {
        if (!root || root.dataset.driverSmartReady === "true") return;
        const modal = root.closest(".uk-modal");
        const form = root.closest("[data-driver-form]") || document.querySelector("[data-driver-form]");
        if (!modal || !form) return;
        root.dataset.driverSmartReady = "true";
        if (modal.parentElement !== document.body) document.body.append(modal);
        window.UIkit?.modal(modal, {stack: true, bgClose: false, escClose: false});

        const source = root.querySelector("[data-driver-smart-source]");
        const resultBox = root.querySelector("[data-driver-smart-result]");
        const applyButton = root.querySelector("[data-driver-smart-apply]");
        let parsed = null;
        const clean = (value) => String(value || "").replace(/\s+/g, " ").trim();
        const titleCase = (value) => value.toLocaleLowerCase("ru-RU").replace(/(^|[-\s])([а-яё])/giu, (_, p, l) => `${p}${l.toLocaleUpperCase("ru-RU")}`);
        const date = "(\\d{2}\\.\\d{2}\\.\\d{4})";
        const isDate = (value) => {
            const [day, month, year] = String(value || "").split(".").map(Number);
            return year >= 1900 && year <= 2100 && month >= 1 && month <= 12 && day >= 1 && day <= 31;
        };
        const decoded = (raw) => {
            const decoder = document.createElement("textarea");
            decoder.innerHTML = String(raw || "");
            return decoder.value.replace(/\*\*/g, "").replace(/\u00a0/g, " ");
        };
        const findName = (text, until) => {
            const rawSample = text.slice(0, until || text.length);
            const sample = rawSample.replace(/^\s*(?:водитель|фио)\s*[:,-]?\s*/i, "");
            const offset = rawSample.length - sample.length;
            const matcher = /(?:^|\s)([А-ЯЁ][А-ЯЁа-яё-]+)\s+([А-ЯЁ][А-ЯЁа-яё-]+)\s+([А-ЯЁ][А-ЯЁа-яё-]+)(?=\s|$)/gu;
            const blocked = new Set(["ПАСПОРТ", "УМВД", "УФМС", "МВД", "РОССИИ", "ВОД", "УДОСТОВЕРЕНИЕ", "ВОДИТЕЛЬ"]);
            let match;
            while ((match = matcher.exec(sample))) {
                if (!match.slice(1, 4).some((part) => blocked.has(part.toLocaleUpperCase("ru-RU")))) {
                    return {parts: match.slice(1, 4), index: match.index + offset, length: match[0].length};
                }
            }
            return null;
        };
        const parse = (raw) => {
            const flat = clean(decoded(raw));
            const data = {};
            const passport = flat.match(/(?:паспорт\D{0,16})?\b(\d{4})\D{1,4}(\d{6})\b/i);
            const fio = findName(flat, passport?.index);
            if (fio) data.fullName = titleCase(fio.parts.join(" "));
            const birth = flat.match(new RegExp(`(?:дата\\s+рождения|родил(?:ся|ась)|д\\.?\\s*р\\.?|г\\.?\\s*р\\.?)\\s*[:,-]?\\s*${date}`, "i"));
            const dateAfterName = fio ? flat.slice(fio.index + fio.length).match(new RegExp(`^\\s*[,;]?\\s*${date}`)) : null;
            if (birth?.[1] && isDate(birth[1])) data.birthDate = birth[1];
            else if (dateAfterName?.[1] && isDate(dateAfterName[1])) data.birthDate = dateAfterName[1];
            if (passport) {
                data.passportSeries = passport[1];
                data.passportNumber = passport[2];
                const afterPassport = flat.slice(passport.index + passport[0].length);
                const boundary = afterPassport.search(/(?:вод\.?\s*удостоверен\w*|в\s*\/\s*у\b|ву\b|права\b|тел(?:ефон)?\.?|инн\b)/i);
                const tail = boundary >= 0 ? afterPassport.slice(0, boundary) : afterPassport;
                const issue = tail.match(new RegExp(`(?:дата\\s+выдачи|выдан(?:а|о)?|[,;]?\\s+от)\\s*${date}`, "i")) || tail.match(new RegExp(date));
                const issueDate = issue?.[1];
                if (issueDate && isDate(issueDate)) {
                    data.passportIssueDate = issueDate;
                    const issuer = tail.slice(0, issue.index).replace(/^\s*(?:выдан(?:а|о)?\s*)?/i, "").replace(/[,;.\s]+$/, "");
                    if (/(?:отдел|уфмс|умвд|мвд|овд|гу\s*мвд)/i.test(issuer)) data.passportIssuedBy = clean(issuer).toUpperCase();
                }
            }
            const phone = flat.match(/(?:тел(?:ефон)?\s*[:\-]?\s*)?(?:\+7|8)[\s()\-]*\d{3}[\s()\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}/i);
            if (phone) {
                const digits = phone[0].replace(/\D/g, "").replace(/^8/, "7").slice(-11);
                if (digits.length === 11) data.phone = `+7 ${digits.slice(1, 4)} ${digits.slice(4, 7)}-${digits.slice(7, 9)}-${digits.slice(9)}`;
            }
            const taxId = flat.match(/(?:инн)\D{0,8}(\d{12})/i);
            if (taxId) data.taxId = taxId[1];
            const license = flat.match(/(?:вод(?:ительск)?\.?\s*удостоверен\w*|вод\.\s*удостоверен\w*|в\s*\/\s*у\b|ву\b|права)\D{0,24}\b(\d{2})\D{0,3}(\d{2})\D{0,3}(\d{6})\b/i);
            if (license) {
                data.licenseNumber = `${license[1]} ${license[2]} ${license[3]}`;
                const licenseTail = flat.slice(license.index + license[0].length);
                const validity = licenseTail.match(new RegExp(`(?:выдан(?:а|о)?\\s*)?${date}\\s*(?:по|до)\\s*${date}`, "i"));
                if (validity?.[1] && isDate(validity[1])) data.licenseIssueDate = validity[1];
                if (validity?.[2] && isDate(validity[2])) data.licenseExpiryDate = validity[2];
            }
            return {data, found: Object.keys(data).length};
        };
        const labels = {fullName: "ФИО", birthDate: "Дата рождения", passportSeries: "Серия паспорта", passportNumber: "Номер паспорта", passportIssuedBy: "Кем выдан", passportIssueDate: "Дата выдачи", phone: "Телефон", taxId: "ИНН", licenseNumber: "Водительское удостоверение", licenseIssueDate: "Дата выдачи ВУ", licenseExpiryDate: "Действительно до"};
        const recognize = () => {
            parsed = parse(source.value);
            resultBox.replaceChildren(); resultBox.hidden = false;
            const heading = document.createElement("h3"); heading.textContent = parsed.found ? `Распознано полей: ${parsed.found}` : "Автозаполнение невозможно"; resultBox.append(heading);
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
            set("[data-license-form]:not([hidden]) input[name$='-number']", d.licenseNumber);
            set("[data-license-form]:not([hidden]) input[name$='-issue_date']", d.licenseIssueDate);
            set("[data-license-form]:not([hidden]) input[name$='-expiry_date']", d.licenseExpiryDate);
            window.UIkit?.modal(modal)?.hide(); form.scrollIntoView({behavior: "smooth", block: "start"});
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
