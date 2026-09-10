(() => {
    const DATE_SELECTOR = "input[data-crm-date]";
    const TIME_SELECTOR = "input[data-crm-time]";
    const DATE_PATTERN = /^(\d{2})\.(\d{2})\.(\d{4})$/;
    const TIME_PATTERN = /^(\d{2}):(\d{2})$/;

    const formatDateDigits = (value) => {
        const digits = value.replace(/\D/g, "").slice(0, 8);
        const parts = [digits.slice(0, 2)];
        if (digits.length > 2) parts.push(digits.slice(2, 4));
        if (digits.length > 4) parts.push(digits.slice(4, 8));
        return parts.join(".");
    };

    const formatTimeDigits = (value) => {
        const digits = value.replace(/\D/g, "").slice(0, 4);
        const parts = [digits.slice(0, 2)];
        if (digits.length > 2) parts.push(digits.slice(2, 4));
        return parts.join(":");
    };

    const normalizeInitialDateValue = (field) => {
        const isoMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(field.value);
        if (isoMatch) {
            field.value = `${isoMatch[3]}.${isoMatch[2]}.${isoMatch[1]}`;
        }
    };

    const normalizeInitialTimeValue = (field) => {
        const match = /^(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?$/.exec(field.value);
        if (match) {
            field.value = `${match[1]}:${match[2]}`;
        }
    };

    const isValidDate = (value) => {
        const match = DATE_PATTERN.exec(value);
        if (!match) return false;
        const day = Number(match[1]);
        const month = Number(match[2]);
        const year = Number(match[3]);
        const parsed = new Date(Date.UTC(year, month - 1, day));
        return parsed.getUTCFullYear() === year
            && parsed.getUTCMonth() === month - 1
            && parsed.getUTCDate() === day;
    };

    const isValidTime = (value) => {
        const match = TIME_PATTERN.exec(value);
        if (!match) return false;
        const hours = Number(match[1]);
        const minutes = Number(match[2]);
        return hours >= 0 && hours <= 23 && minutes >= 0 && minutes <= 59;
    };

    const enhanceWithin = (root = document) => {
        root.querySelectorAll?.(DATE_SELECTOR).forEach(normalizeInitialDateValue);
        root.querySelectorAll?.(TIME_SELECTOR).forEach(normalizeInitialTimeValue);
    };

    enhanceWithin();

    document.addEventListener("input", (event) => {
        const field = event.target.closest?.(DATE_SELECTOR);
        if (!field) return;
        field.value = formatDateDigits(field.value);
        field.setCustomValidity("");
    });

    document.addEventListener("input", (event) => {
        const field = event.target.closest?.(TIME_SELECTOR);
        if (!field) return;
        field.value = formatTimeDigits(field.value);
        field.setCustomValidity("");
    });

    document.addEventListener("blur", (event) => {
        const field = event.target.closest?.(DATE_SELECTOR);
        if (!field) return;
        if (!field.value || isValidDate(field.value)) {
            field.setCustomValidity("");
            return;
        }
        field.setCustomValidity("Введите корректную дату в формате ДД.ММ.ГГГГ");
    }, true);

    document.addEventListener("blur", (event) => {
        const field = event.target.closest?.(TIME_SELECTOR);
        if (!field) return;
        if (!field.value || isValidTime(field.value)) {
            field.setCustomValidity("");
            return;
        }
        field.setCustomValidity("Введите корректное время в формате ЧЧ:ММ");
    }, true);

    window.CRMDateInputs = {
        ...(window.CRMDateInputs || {}),
        enhanceWithin,
    };
})();
