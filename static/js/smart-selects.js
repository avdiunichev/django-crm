(() => {
    const SELECTOR = "select:not([multiple]):not([data-native-select])";
    const normalize = (value) => String(value || "").toLocaleLowerCase("ru-RU").trim();
    const isPlaceholder = (label) => /^[-—\s]+$/.test(label || "");

    const fieldLabel = (select) => {
        if (!select.id) return "";
        const label = document.querySelector(`label[for="${CSS.escape(select.id)}"]`);
        return label?.textContent.replace("*", "").trim() || "";
    };

    const enhance = (select) => {
        if (!select || select.dataset.smartReady === "true" || select.multiple) return;
        select.dataset.smartReady = "true";

        const required = select.required;
        select.required = false;
        select.classList.add("crm-smart-native");
        select.tabIndex = -1;
        select.setAttribute("aria-hidden", "true");

        const wrapper = document.createElement("div");
        wrapper.className = "crm-smart-select crm-universal-select";
        const search = document.createElement("input");
        search.type = "search";
        search.className = "uk-input crm-smart-search";
        search.autocomplete = "off";
        search.placeholder = select.dataset.searchPlaceholder
            || (fieldLabel(select) ? `Поиск: ${fieldLabel(select)}` : "Начните вводить для поиска");
        search.setAttribute("role", "combobox");
        search.setAttribute("aria-autocomplete", "list");
        search.setAttribute("aria-expanded", "false");
        if (select.id) {
            search.id = `${select.id}__search`;
            const label = document.querySelector(`label[for="${CSS.escape(select.id)}"]`);
            if (label) label.htmlFor = search.id;
        }

        const dropdown = document.createElement("div");
        dropdown.className = "crm-smart-dropdown";
        dropdown.hidden = true;
        wrapper.append(search, dropdown);
        select.insertAdjacentElement("afterend", wrapper);

        let activeIndex = -1;
        let committedValue = "";
        let committedText = "";
        const selectedText = () => {
            const option = select.selectedOptions[0];
            if (!option || isPlaceholder(option.textContent.trim())) return "";
            return option.textContent.trim();
        };
        const close = (restore = false) => {
            dropdown.hidden = true;
            search.setAttribute("aria-expanded", "false");
            activeIndex = -1;
            if (restore && search.value !== committedText) {
                select.value = committedValue;
                search.value = committedText;
                search.setCustomValidity(required && !committedValue ? "Выберите значение из списка" : "");
            }
        };
        const syncFromSelect = () => {
            search.value = selectedText();
            search.dataset.selectedText = search.value;
            committedValue = select.value;
            committedText = search.value;
            search.setCustomValidity(required && !select.value ? "Выберите значение из списка" : "");
        };
        const choose = (option) => {
            select.value = option.value;
            syncFromSelect();
            close();
            select.dispatchEvent(new Event("change", {bubbles: true}));
            search.focus();
        };
        const optionIsVisible = (option, query) => {
            const label = option.textContent.trim();
            if (!option.value && isPlaceholder(label)) return false;
            return !query || normalize(label).includes(query);
        };
        const markActive = (buttons, index) => {
            buttons.forEach((button) => button.classList.remove("is-active"));
            if (!buttons.length) {
                activeIndex = -1;
                return;
            }
            activeIndex = (index + buttons.length) % buttons.length;
            buttons[activeIndex].classList.add("is-active");
            buttons[activeIndex].scrollIntoView({block: "nearest"});
        };
        const render = () => {
            const query = normalize(search.value);
            const options = Array.from(select.options).filter((option) => optionIsVisible(option, query));
            dropdown.innerHTML = "";
            options.slice(0, 50).forEach((option) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "crm-smart-option";
                button.textContent = option.textContent.trim();
                if (option.selected) button.classList.add("is-selected");
                button.addEventListener("mousedown", (event) => event.preventDefault());
                button.addEventListener("click", () => choose(option));
                dropdown.appendChild(button);
            });
            if (!options.length) {
                const empty = document.createElement("div");
                empty.className = "crm-smart-empty";
                empty.textContent = "Подходящих вариантов не найдено.";
                dropdown.appendChild(empty);
            }
            dropdown.hidden = false;
            search.setAttribute("aria-expanded", "true");
            activeIndex = -1;
        };

        search.addEventListener("focus", () => {
            render();
            search.select();
        });
        search.addEventListener("input", () => {
            if (search.value !== committedText) select.value = "";
            else select.value = committedValue;
            search.setCustomValidity(
                required && !select.value
                    ? "Выберите значение из списка"
                    : ""
            );
            render();
        });
        search.addEventListener("keydown", (event) => {
            const buttons = Array.from(dropdown.querySelectorAll(".crm-smart-option"));
            if (event.key === "ArrowDown") {
                event.preventDefault();
                if (dropdown.hidden) render();
                markActive(buttons, activeIndex + 1);
            } else if (event.key === "ArrowUp") {
                event.preventDefault();
                markActive(buttons, activeIndex - 1);
            } else if (event.key === "Enter" && !dropdown.hidden && activeIndex >= 0) {
                event.preventDefault();
                buttons[activeIndex]?.click();
            } else if (event.key === "Escape") {
                close(true);
            }
        });
        select.addEventListener("change", syncFromSelect);
        select.addEventListener("optionschange", syncFromSelect);
        document.addEventListener("mousedown", (event) => {
            if (!wrapper.contains(event.target)) close(true);
        });
        syncFromSelect();
    };

    const enhanceWithin = (root = document) => {
        if (root.matches?.(SELECTOR)) enhance(root);
        root.querySelectorAll?.(SELECTOR).forEach(enhance);
    };

    document.addEventListener("DOMContentLoaded", () => {
        enhanceWithin(document);
        const observer = new MutationObserver((records) => {
            const changedSelects = new Set();
            records.forEach((record) => {
                record.addedNodes.forEach((node) => {
                    if (!(node instanceof Element)) return;
                    enhanceWithin(node);
                    const ownerSelect = node.closest("select[data-smart-ready='true']");
                    if (ownerSelect) changedSelects.add(ownerSelect);
                });
            });
            changedSelects.forEach((select) => {
                select.dispatchEvent(new Event("optionschange", {bubbles: true}));
            });
        });
        observer.observe(document.body, {childList: true, subtree: true});
    });

    window.CRMUniversalSelects = {enhance, enhanceWithin};
})();
