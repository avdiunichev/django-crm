(() => {
    const DATE_SELECTOR = "input[data-crm-date]";
    const DATE_PATTERN = /^(\d{2})\.(\d{2})\.(\d{4})$/;

    const formatDigits = (value) => {
        const digits = value.replace(/\D/g, "").slice(0, 8);
        const parts = [digits.slice(0, 2)];
        if (digits.length > 2) parts.push(digits.slice(2, 4));
        if (digits.length > 4) parts.push(digits.slice(4, 8));
        return parts.join(".");
    };

    const normalizeInitialValue = (field) => {
        const isoMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(field.value);
        if (isoMatch) {
            field.value = `${isoMatch[3]}.${isoMatch[2]}.${isoMatch[1]}`;
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

    document.querySelectorAll(DATE_SELECTOR).forEach(normalizeInitialValue);

    document.addEventListener("input", (event) => {
        const field = event.target.closest?.(DATE_SELECTOR);
        if (!field) return;
        field.value = formatDigits(field.value);
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
})();
