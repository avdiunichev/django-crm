(() => {
    "use strict";

    const SELECTOR = "input[data-dadata-driver]";
    const DELAY = 260;

    const enhance = (input) => {
        if (!input || input.dataset.dadataDriverReady === "true") return;
        input.dataset.dadataDriverReady = "true";
        input.autocomplete = "off";

        const wrapper = document.createElement("div");
        wrapper.className = "crm-address-suggest crm-driver-suggest";
        input.insertAdjacentElement("beforebegin", wrapper);
        wrapper.appendChild(input);

        const dropdown = document.createElement("div");
        dropdown.className = "crm-address-dropdown crm-driver-dropdown";
        dropdown.hidden = true;
        dropdown.id = `${input.id || input.name}-dadata-suggestions`;
        wrapper.appendChild(dropdown);

        input.setAttribute("role", "combobox");
        input.setAttribute("aria-autocomplete", "list");
        input.setAttribute("aria-controls", dropdown.id);
        input.setAttribute("aria-expanded", "false");

        let timer;
        let controller;
        let activeIndex = -1;
        let requestNumber = 0;

        const close = () => {
            dropdown.hidden = true;
            input.setAttribute("aria-expanded", "false");
            activeIndex = -1;
        };
        const open = () => {
            dropdown.hidden = false;
            input.setAttribute("aria-expanded", "true");
        };
        const message = (text, kind = "muted") => {
            dropdown.replaceChildren();
            const item = document.createElement("div");
            item.className = `crm-address-message is-${kind}`;
            item.textContent = text;
            dropdown.appendChild(item);
            open();
        };
        const choose = (suggestion) => {
            input.value = suggestion.value;
            close();
            input.dispatchEvent(new Event("change", {bubbles: true}));
            input.focus();
        };
        const markActive = (buttons, nextIndex) => {
            buttons.forEach((button) => button.classList.remove("is-active"));
            if (!buttons.length) {
                activeIndex = -1;
                return;
            }
            activeIndex = (nextIndex + buttons.length) % buttons.length;
            buttons[activeIndex].classList.add("is-active");
            buttons[activeIndex].scrollIntoView({block: "nearest"});
        };
        const render = (suggestions) => {
            dropdown.replaceChildren();
            if (!suggestions.length) {
                message("Подходящих вариантов не найдено. Можно ввести значение вручную.");
                return;
            }
            suggestions.forEach((suggestion) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "crm-address-option crm-driver-option";
                const value = document.createElement("span");
                value.textContent = suggestion.value;
                button.appendChild(value);
                if (suggestion.code) {
                    const meta = document.createElement("small");
                    meta.textContent = `Код подразделения: ${suggestion.code}`;
                    button.appendChild(meta);
                }
                button.addEventListener("mousedown", (event) => event.preventDefault());
                button.addEventListener("click", () => choose(suggestion));
                dropdown.appendChild(button);
            });
            open();
        };
        const load = async () => {
            const query = input.value.trim();
            if (query.length < 2) {
                close();
                return;
            }
            controller?.abort();
            controller = new AbortController();
            const currentRequest = ++requestNumber;
            const url = new URL(input.dataset.dadataUrl, window.location.origin);
            url.searchParams.set("q", query);
            if (input.dataset.dadataPart) url.searchParams.set("part", input.dataset.dadataPart);
            message("DaData ищет подходящий вариант…", "loading");
            try {
                const response = await fetch(url, {
                    headers: {"Accept": "application/json"},
                    signal: controller.signal
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.error || "Подсказки DaData недоступны.");
                if (currentRequest !== requestNumber || document.activeElement !== input) return;
                render(result.suggestions || []);
            } catch (error) {
                if (error.name === "AbortError" || currentRequest !== requestNumber) return;
                message(error.message || "Подсказки DaData временно недоступны.", "danger");
            }
        };

        input.addEventListener("input", () => {
            clearTimeout(timer);
            controller?.abort();
            if (input.value.trim().length < 2) {
                close();
                return;
            }
            timer = window.setTimeout(load, DELAY);
        });
        input.addEventListener("keydown", (event) => {
            const buttons = Array.from(dropdown.querySelectorAll(".crm-driver-option"));
            if (event.key === "ArrowDown") {
                event.preventDefault();
                markActive(buttons, activeIndex + 1);
            } else if (event.key === "ArrowUp") {
                event.preventDefault();
                markActive(buttons, activeIndex - 1);
            } else if (event.key === "Enter" && activeIndex >= 0) {
                event.preventDefault();
                buttons[activeIndex]?.click();
            } else if (event.key === "Escape") {
                close();
            }
        });
        document.addEventListener("mousedown", (event) => {
            if (!wrapper.contains(event.target)) close();
        });
    };

    const enhanceWithin = (root = document) => {
        if (root.matches?.(SELECTOR)) enhance(root);
        root.querySelectorAll?.(SELECTOR).forEach(enhance);
    };

    document.addEventListener("DOMContentLoaded", () => {
        enhanceWithin(document);
        const observer = new MutationObserver((records) => {
            records.forEach((record) => {
                record.addedNodes.forEach((node) => {
                    if (node instanceof Element) enhanceWithin(node);
                });
            });
        });
        observer.observe(document.body, {childList: true, subtree: true});
    });

    window.CRMDriverSuggestions = {enhance, enhanceWithin};
})();
