(() => {
    "use strict";

    const SELECTOR = "input[data-dadata-city]";
    const MIN_QUERY_LENGTH = 2;
    const DELAY = 250;

    const cityFromSuggestion = (suggestion) => {
        const city = suggestion.city || suggestion.settlement || suggestion.area || suggestion.region || suggestion.value;
        return city || "";
    };

    const enhance = (input) => {
        if (!input || input.dataset.dadataCityReady === "true") return;
        input.dataset.dadataCityReady = "true";
        input.autocomplete = "off";

        const wrapper = document.createElement("div");
        wrapper.className = "crm-address-suggest";
        input.insertAdjacentElement("beforebegin", wrapper);
        wrapper.appendChild(input);

        const dropdown = document.createElement("div");
        dropdown.className = "crm-address-dropdown";
        dropdown.hidden = true;
        dropdown.id = `${input.id || input.name}-dadata-city-suggestions`;
        wrapper.appendChild(dropdown);

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

        const renderMessage = (message, kind = "muted") => {
            dropdown.replaceChildren();
            const item = document.createElement("div");
            item.className = `crm-address-message is-${kind}`;
            item.textContent = message;
            dropdown.appendChild(item);
            open();
        };

        const choose = (suggestion) => {
            const city = cityFromSuggestion(suggestion);
            input.value = city;
            input.dataset.dadataSelected = city;
            close();
            input.dispatchEvent(new Event("change", {bubbles: true}));
            input.focus();
        };

        const renderSuggestions = (suggestions) => {
            dropdown.replaceChildren();
            const unique = [];
            const seen = new Set();
            suggestions.forEach((suggestion) => {
                const city = cityFromSuggestion(suggestion);
                if (!city || seen.has(city.toLowerCase())) return;
                seen.add(city.toLowerCase());
                unique.push({...suggestion, city});
            });
            if (!unique.length) {
                renderMessage("Город не найден. Можно продолжить ввод вручную.");
                return;
            }
            unique.slice(0, 8).forEach((suggestion) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "crm-address-option";
                const value = document.createElement("span");
                value.textContent = suggestion.city;
                button.appendChild(value);
                const details = [suggestion.region, suggestion.area]
                    .filter((part, index, items) => part && items.indexOf(part) === index && part !== suggestion.city)
                    .join(" · ");
                if (details) {
                    const meta = document.createElement("small");
                    meta.textContent = details;
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
            if (query.length < MIN_QUERY_LENGTH) {
                close();
                return;
            }
            controller?.abort();
            controller = new AbortController();
            const currentRequest = ++requestNumber;
            const url = new URL(input.dataset.dadataCityUrl, window.location.origin);
            url.searchParams.set("q", query);
            renderMessage("DaData ищет город…", "loading");
            try {
                const response = await fetch(url, {
                    headers: {"Accept": "application/json"},
                    signal: controller.signal
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.error || "Подсказки DaData недоступны.");
                if (currentRequest !== requestNumber || document.activeElement !== input) return;
                renderSuggestions(result.suggestions || []);
            } catch (error) {
                if (error.name === "AbortError" || currentRequest !== requestNumber) return;
                renderMessage(error.message || "Подсказки DaData временно недоступны.", "danger");
            }
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

        input.setAttribute("role", "combobox");
        input.setAttribute("aria-autocomplete", "list");
        input.setAttribute("aria-controls", dropdown.id);
        input.setAttribute("aria-expanded", "false");

        input.addEventListener("input", () => {
            delete input.dataset.dadataSelected;
            clearTimeout(timer);
            controller?.abort();
            if (input.value.trim().length < MIN_QUERY_LENGTH) {
                close();
                return;
            }
            timer = window.setTimeout(load, DELAY);
        });
        input.addEventListener("keydown", (event) => {
            const buttons = Array.from(dropdown.querySelectorAll(".crm-address-option"));
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

    window.CRMCitySuggestions = {enhance, enhanceWithin};
})();
