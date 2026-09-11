(() => {
    "use strict";

    const normalizeMoney = (value) => value
        .replace(/\s/g, "")
        .replace(",", ".")
        .replace(/[^\d.-]/g, "");

    const formatMoney = (value) => {
        const normalized = normalizeMoney(value);
        if (!normalized || normalized === "-" || normalized === ".") return "";
        const number = Number(normalized);
        if (!Number.isFinite(number)) return value;
        return new Intl.NumberFormat("ru-RU", {
            minimumFractionDigits: 0,
            maximumFractionDigits: 2,
        }).format(number);
    };

    const formatMoneyWhileTyping = (value) => {
        const normalized = normalizeMoney(value);
        if (!normalized || normalized === "-" || normalized === ".") return normalized === "." ? "," : normalized;
        const [integerPart, ...fractionParts] = normalized.split(".");
        const integer = integerPart || "0";
        const grouped = new Intl.NumberFormat("ru-RU", {
            maximumFractionDigits: 0,
        }).format(Number(integer));
        if (!fractionParts.length) return grouped;
        return `${grouped},${fractionParts.join("").slice(0, 2)}`;
    };

    const enhanceMoneyInput = (input) => {
        if (input.dataset.moneyReady === "true") return;
        input.dataset.moneyReady = "true";
        input.value = formatMoney(input.value);
        input.addEventListener("input", () => {
            const cursorAtEnd = input.selectionStart === input.value.length;
            const formatted = formatMoneyWhileTyping(input.value);
            if (formatted && formatted !== input.value) input.value = formatted;
            if (cursorAtEnd) input.setSelectionRange(input.value.length, input.value.length);
        });
        input.addEventListener("blur", () => { input.value = formatMoney(input.value); });
    };

    const enhanceCargoInput = (input) => {
        if (input.dataset.cargoReady === "true") return;
        const source = document.getElementById("cargo-name-suggestions-data");
        if (!source) return;
        let suggestions = [];
        try { suggestions = JSON.parse(source.textContent || "[]"); } catch (error) { return; }
        if (!suggestions.length) return;
        input.dataset.cargoReady = "true";
        const wrapper = document.createElement("div");
        wrapper.className = "crm-smart-select crm-universal-select cargo-autocomplete";
        input.classList.add("crm-smart-search");
        input.parentNode.insertBefore(wrapper, input);
        wrapper.appendChild(input);
        const menu = document.createElement("div");
        menu.className = "crm-smart-dropdown cargo-autocomplete-menu";
        menu.hidden = true;
        menu.setAttribute("role", "listbox");
        wrapper.appendChild(menu);

        const close = () => { menu.hidden = true; menu.replaceChildren(); };
        const render = () => {
            const needle = input.value.trim().toLocaleLowerCase("ru-RU");
            const matches = suggestions.filter((item) => item.toLocaleLowerCase("ru-RU").includes(needle)).slice(0, 8);
            if (!matches.length) return close();
            menu.replaceChildren(...matches.map((name) => {
                const option = document.createElement("button");
                option.type = "button";
                option.className = "crm-smart-option cargo-autocomplete-option";
                option.textContent = name;
                option.setAttribute("role", "option");
                if (name === input.value.trim()) option.classList.add("is-selected");
                option.addEventListener("mousedown", (event) => {
                    event.preventDefault();
                    input.value = name;
                    input.dispatchEvent(new Event("input", { bubbles: true }));
                    close();
                    input.focus();
                });
                return option;
            }));
            menu.hidden = false;
        };
        input.addEventListener("focus", render);
        input.addEventListener("input", render);
        input.addEventListener("keydown", (event) => {
            if (event.key === "Escape") close();
            if (event.key === "ArrowDown" && !menu.hidden) {
                event.preventDefault();
                menu.querySelector("button")?.focus();
            }
        });
        wrapper.addEventListener("focusout", () => setTimeout(() => {
            if (!wrapper.contains(document.activeElement)) close();
        }, 0));
    };

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-money-input], [data-decimal-input]").forEach(enhanceMoneyInput);
        document.querySelectorAll("[data-cargo-autocomplete]").forEach(enhanceCargoInput);
        document.querySelectorAll("form[data-order-form]").forEach((form) => {
            form.addEventListener("submit", () => {
                form.querySelectorAll("[data-money-input], [data-decimal-input]").forEach((input) => {
                    input.value = normalizeMoney(input.value);
                });
            });
        });
    });
})();
