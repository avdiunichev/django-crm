(() => {
    "use strict";

    const SELECTOR = "input[data-dadata-address]";
    const MIN_QUERY_LENGTH = 3;
    const DELAY = 280;

    const enhance = (input) => {
        if (!input || input.dataset.dadataAddressReady === "true") return;
        input.dataset.dadataAddressReady = "true";
        input.autocomplete = "off";

        const wrapper = document.createElement("div");
        wrapper.className = "crm-address-suggest";
        input.insertAdjacentElement("beforebegin", wrapper);
        wrapper.appendChild(input);

        const dropdown = document.createElement("div");
        dropdown.className = "crm-address-dropdown";
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

        const clearMeta = () => {
            const metaTargetId = input.dataset.dadataMetaTarget;
            const metaTarget = metaTargetId && document.getElementById(metaTargetId);
            if (metaTarget) metaTarget.value = "";
        };

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
            input.value = suggestion.value;
            input.dataset.dadataSelected = suggestion.value;
            const metaTargetId = input.dataset.dadataMetaTarget;
            const metaTarget = metaTargetId && document.getElementById(metaTargetId);
            if (metaTarget) {
                // Keep the normalized DaData response in the form. The server
                // copies only whitelisted address parts into the route stop.
                metaTarget.value = JSON.stringify(suggestion);
                metaTarget.dispatchEvent(new Event("change", {bubbles: true}));
            }
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

        const renderSuggestions = (suggestions) => {
            dropdown.replaceChildren();
            if (!suggestions.length) {
                renderMessage("Адрес не найден. Можно продолжить ввод вручную.");
                return;
            }
            suggestions.forEach((suggestion) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "crm-address-option";
                const value = document.createElement("span");
                value.textContent = suggestion.value;
                button.appendChild(value);
                const details = [suggestion.postal_code, suggestion.region]
                    .filter((part, index, items) => part && items.indexOf(part) === index)
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
            const url = new URL(input.dataset.dadataAddressUrl, window.location.origin);
            url.searchParams.set("q", query);
            const city = document.getElementById(input.dataset.dadataCitySource || "")?.value.trim();
            if (city) url.searchParams.set("city", city);
            renderMessage("DaData ищет подходящий адрес…", "loading");
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

        input.addEventListener("input", () => {
            delete input.dataset.dadataSelected;
            clearMeta();
            clearTimeout(timer);
            controller?.abort();
            if (input.value.trim().length < MIN_QUERY_LENGTH) {
                close();
                return;
            }
            timer = window.setTimeout(load, DELAY);
        });
        const cityInput = document.getElementById(input.dataset.dadataCitySource || "");
        cityInput?.addEventListener("input", clearMeta);
        cityInput?.addEventListener("change", clearMeta);
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

    window.CRMAddressSuggestions = {enhance, enhanceWithin};
})();
