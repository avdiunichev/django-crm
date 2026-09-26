(() => {
    "use strict";

    const SELECTOR = "input[data-dadata-email-url]";
    const DELAY = 260;

    const enhance = (input) => {
        if (!input || input.dataset.dadataEmailReady === "true") return;
        input.dataset.dadataEmailReady = "true";
        // "new-password" is deliberately used here: some browsers ignore
        // autocomplete="off" for e-mail fields, while this token suppresses
        // their saved-address dropdown without affecting CRM suggestions.
        input.autocomplete = "new-password";

        const wrapper = document.createElement("div");
        wrapper.className = "crm-address-suggest crm-mail-recipient-suggest";
        input.insertAdjacentElement("beforebegin", wrapper);
        wrapper.appendChild(input);
        const dropdown = document.createElement("div");
        dropdown.className = "crm-address-dropdown crm-mail-recipient-dropdown";
        dropdown.hidden = true;
        wrapper.appendChild(dropdown);

        const localOptions = Array.from(document.getElementById(input.dataset.recipientSuggestions || "")?.options || [])
            .map((option) => ({value: option.value, label: option.label || option.value}));
        let timer;
        let controller;
        let requestNumber = 0;

        const close = () => { dropdown.hidden = true; };
        const open = () => { dropdown.hidden = false; };
        const choose = (value) => {
            input.value = value;
            close();
            input.dispatchEvent(new Event("change", {bubbles: true}));
            input.focus();
        };
        const render = (items) => {
            dropdown.replaceChildren();
            if (!items.length) {
                const message = document.createElement("div");
                message.className = "crm-address-message is-muted";
                message.textContent = "Подсказок нет. Можно указать адрес вручную.";
                dropdown.appendChild(message);
                open();
                return;
            }
            items.forEach((item) => {
                const option = document.createElement("button");
                option.type = "button";
                option.className = "crm-address-option";
                const value = document.createElement("span");
                value.textContent = item.value;
                option.appendChild(value);
                if (item.label && item.label !== item.value) {
                    const label = document.createElement("small");
                    label.textContent = item.label;
                    option.appendChild(label);
                }
                option.addEventListener("mousedown", (event) => event.preventDefault());
                option.addEventListener("click", () => choose(item.value));
                dropdown.appendChild(option);
            });
            open();
        };
        const load = async () => {
            const query = input.value.trim();
            if (query.length < 2) {
                close();
                return;
            }
            const local = localOptions.filter((item) => `${item.value} ${item.label}`.toLowerCase().includes(query.toLowerCase()));
            controller?.abort();
            controller = new AbortController();
            const request = ++requestNumber;
            try {
                const url = new URL(input.dataset.dadataEmailUrl, document.baseURI);
                url.searchParams.set("q", query);
                const response = await fetch(url, {headers: {Accept: "application/json"}, signal: controller.signal});
                const result = await response.json();
                if (!response.ok) throw new Error(result.error || "Подсказки DaData недоступны.");
                if (request !== requestNumber || document.activeElement !== input) return;
                const known = new Set(local.map((item) => item.value.toLowerCase()));
                render([...local, ...(result.suggestions || []).filter((item) => !known.has(item.value.toLowerCase()))]);
            } catch (error) {
                if (error.name === "AbortError" || request !== requestNumber) return;
                render(local);
            }
        };
        input.addEventListener("input", () => {
            clearTimeout(timer);
            controller?.abort();
            timer = window.setTimeout(load, DELAY);
        });
        input.addEventListener("keydown", (event) => {
            if (event.key === "Escape") close();
        });
        document.addEventListener("mousedown", (event) => {
            if (!wrapper.contains(event.target)) close();
        });
    };

    const enhanceWithin = (root = document) => {
        if (root.matches?.(SELECTOR)) enhance(root);
        root.querySelectorAll?.(SELECTOR).forEach(enhance);
    };

    document.addEventListener("DOMContentLoaded", () => enhanceWithin());
    window.addEventListener("crm:content-updated", (event) => enhanceWithin(event.detail.root));
})();
