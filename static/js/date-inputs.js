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

    const parseDate = (value) => {
        const match = DATE_PATTERN.exec(value || "");
        if (!match) return null;
        const year = Number(match[3]);
        const month = Number(match[2]) - 1;
        const day = Number(match[1]);
        const result = new Date(year, month, day);
        return result.getFullYear() === year && result.getMonth() === month && result.getDate() === day
            ? result
            : null;
    };
    const dateValue = (date) => `${String(date.getDate()).padStart(2, "0")}.${String(date.getMonth() + 1).padStart(2, "0")}.${date.getFullYear()}`;
    const sameDay = (first, second) => first && second && first.getFullYear() === second.getFullYear() && first.getMonth() === second.getMonth() && first.getDate() === second.getDate();
    const monthTitle = new Intl.DateTimeFormat("ru-RU", {month: "long", year: "numeric"});
    const monthNames = Array.from({length: 12}, (_, index) => (
        new Intl.DateTimeFormat("ru-RU", {month: "long"}).format(new Date(2026, index, 1))
    ));

    const enhanceCalendar = (field) => {
        if (!field || field.dataset.crmCalendarReady === "true") return;
        field.dataset.crmCalendarReady = "true";
        const wrapper = document.createElement("div");
        wrapper.className = "crm-date-picker crm-smart-select";
        field.parentNode.insertBefore(wrapper, field);
        wrapper.appendChild(field);
        field.classList.add("crm-date-input");
        field.readOnly = true;
        field.setAttribute("role", "button");
        field.setAttribute("aria-haspopup", "dialog");
        const dropdown = document.createElement("div");
        dropdown.className = "crm-smart-dropdown crm-date-dropdown";
        dropdown.hidden = true;
        wrapper.appendChild(dropdown);
        let viewDate = parseDate(field.value) || new Date();
        const close = () => {
            dropdown.hidden = true;
            field.setAttribute("aria-expanded", "false");
        };
        const select = (date) => {
            field.value = dateValue(date);
            field.setCustomValidity("");
            field.dispatchEvent(new Event("change", {bubbles: true}));
            close();
        };
        const render = () => {
            const selected = parseDate(field.value);
            const today = new Date();
            const year = viewDate.getFullYear();
            const month = viewDate.getMonth();
            const firstDay = new Date(year, month, 1);
            const offset = (firstDay.getDay() + 6) % 7;
            const start = new Date(year, month, 1 - offset);
            dropdown.replaceChildren();
            const header = document.createElement("div");
            header.className = "crm-date-header";
            const previous = document.createElement("button");
            previous.type = "button";
            previous.className = "crm-date-nav";
            previous.textContent = "‹";
            previous.setAttribute("aria-label", "Предыдущий месяц");
            previous.addEventListener("mousedown", (event) => event.preventDefault());
            previous.addEventListener("click", () => { viewDate = new Date(year, month - 1, 1); render(); });
            const title = document.createElement("strong");
            title.textContent = monthTitle.format(viewDate).replace(/^./, (letter) => letter.toUpperCase());
            const next = document.createElement("button");
            next.type = "button";
            next.className = "crm-date-nav";
            next.textContent = "›";
            next.setAttribute("aria-label", "Следующий месяц");
            next.addEventListener("mousedown", (event) => event.preventDefault());
            next.addEventListener("click", () => { viewDate = new Date(year, month + 1, 1); render(); });
            header.append(previous, title, next);
            const controls = document.createElement("div");
            controls.className = "crm-date-controls";
            const monthSelect = document.createElement("select");
            monthSelect.className = "crm-date-select";
            monthSelect.setAttribute("aria-label", "Месяц");
            monthNames.forEach((name, index) => {
                const option = document.createElement("option");
                option.value = String(index);
                option.textContent = name.replace(/^./, (letter) => letter.toUpperCase());
                option.selected = index === month;
                monthSelect.appendChild(option);
            });
            const yearSelect = document.createElement("select");
            yearSelect.className = "crm-date-select";
            yearSelect.setAttribute("aria-label", "Год");
            const startYear = year - 10;
            for (let itemYear = startYear; itemYear <= year + 10; itemYear += 1) {
                const option = document.createElement("option");
                option.value = String(itemYear);
                option.textContent = String(itemYear);
                option.selected = itemYear === year;
                yearSelect.appendChild(option);
            }
            const todayButton = document.createElement("button");
            todayButton.type = "button";
            todayButton.className = "crm-date-today";
            todayButton.textContent = "Сегодня";
            [monthSelect, yearSelect, todayButton].forEach((control) => {
                control.addEventListener("mousedown", (event) => event.preventDefault());
            });
            monthSelect.addEventListener("change", () => {
                viewDate = new Date(year, Number(monthSelect.value), 1);
                render();
            });
            yearSelect.addEventListener("change", () => {
                viewDate = new Date(Number(yearSelect.value), month, 1);
                render();
            });
            todayButton.addEventListener("click", () => {
                const now = new Date();
                viewDate = new Date(now.getFullYear(), now.getMonth(), 1);
                select(now);
            });
            controls.append(monthSelect, yearSelect, todayButton);
            const weekdays = document.createElement("div");
            weekdays.className = "crm-date-weekdays";
            ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].forEach((label) => {
                const day = document.createElement("span");
                day.textContent = label;
                weekdays.appendChild(day);
            });
            const days = document.createElement("div");
            days.className = "crm-date-days";
            for (let index = 0; index < 42; index += 1) {
                const dayDate = new Date(start);
                dayDate.setDate(start.getDate() + index);
                const button = document.createElement("button");
                button.type = "button";
                button.className = "crm-date-day";
                button.textContent = String(dayDate.getDate());
                if (dayDate.getMonth() !== month) button.classList.add("is-outside");
                if (sameDay(dayDate, today)) button.classList.add("is-today");
                if (sameDay(dayDate, selected)) button.classList.add("is-selected");
                button.addEventListener("mousedown", (event) => event.preventDefault());
                button.addEventListener("click", () => select(dayDate));
                days.appendChild(button);
            }
            dropdown.append(header, controls, weekdays, days);
            dropdown.hidden = false;
            field.setAttribute("aria-expanded", "true");
        };
        field.addEventListener("focus", () => { viewDate = parseDate(field.value) || new Date(); render(); });
        field.addEventListener("click", () => { viewDate = parseDate(field.value) || viewDate || new Date(); render(); });
        field.addEventListener("keydown", (event) => {
            if (event.key === "Escape") close();
            if (event.key === "Enter" || event.key === " " || event.key === "ArrowDown") {
                event.preventDefault();
                viewDate = parseDate(field.value) || viewDate || new Date();
                render();
            }
        });
        field.addEventListener("beforeinput", (event) => event.preventDefault());
        field.addEventListener("paste", (event) => event.preventDefault());
        wrapper.addEventListener("focusout", () => setTimeout(() => { if (!wrapper.contains(document.activeElement)) close(); }, 0));
    };

    const enhanceWithin = (root = document) => {
        root.querySelectorAll?.(DATE_SELECTOR).forEach((field) => {
            normalizeInitialDateValue(field);
            enhanceCalendar(field);
        });
        root.querySelectorAll?.(TIME_SELECTOR).forEach(normalizeInitialTimeValue);
    };

    enhanceWithin();

    const observer = new MutationObserver((records) => {
        records.forEach((record) => record.addedNodes.forEach((node) => {
            if (!(node instanceof Element)) return;
            if (node.matches?.(DATE_SELECTOR)) {
                normalizeInitialDateValue(node);
                enhanceCalendar(node);
            }
            enhanceWithin(node);
        }));
    });
    observer.observe(document.body, {childList: true, subtree: true});

    document.addEventListener("input", (event) => {
        const field = event.target.closest?.(DATE_SELECTOR);
        if (!field) return;
        if (field.readOnly) return;
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
