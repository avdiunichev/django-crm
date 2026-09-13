(() => {
    "use strict";

    const SELECTOR = "input[data-dadata-bank]";

    const digits = (value) => String(value || "").replace(/\D/g, "");

    const findField = (input, fieldName) => {
        if (!fieldName) return null;
        const form = input.closest("form") || document;
        return form.querySelector(`[name="${CSS.escape(fieldName)}"]`);
    };

    const fillIfSafe = (field, value, marker) => {
        if (!field || !value) return;
        const previous = field.dataset.dadataBankValue || "";
        if (field.value && field.value !== previous) return;
        field.value = value;
        field.dataset.dadataBankValue = value;
        field.dispatchEvent(new Event("input", {bubbles: true}));
        field.dispatchEvent(new Event("change", {bubbles: true}));
        if (marker) field.dataset.dadataBankSource = marker;
    };

    const lookupBank = async (input) => {
        const bik = digits(input.value);
        input.value = bik;
        if (bik.length !== 9) return;

        const bankNameField = findField(input, input.dataset.bankNameField);
        const correspondentField = findField(input, input.dataset.correspondentAccountField);
        const url = new URL(input.dataset.dadataBankUrl, window.location.origin);
        url.searchParams.set("bik", bik);

        try {
            const response = await fetch(url, {
                headers: {"X-Requested-With": "XMLHttpRequest"},
                credentials: "same-origin",
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(payload.error || "Банк не найден");
            }
            const bank = payload.bank || {};
            fillIfSafe(bankNameField, bank.bank_name || bank.value, bik);
            fillIfSafe(correspondentField, bank.correspondent_account, bik);
        } catch (error) {}
    };

    const enhance = (input) => {
        if (!input || input.dataset.dadataBankReady === "true") return;
        input.dataset.dadataBankReady = "true";
        let timer = null;
        input.addEventListener("input", () => {
            clearTimeout(timer);
            timer = setTimeout(() => lookupBank(input), 450);
        });
        input.addEventListener("blur", () => {
            clearTimeout(timer);
            lookupBank(input);
        });
    };

    const init = (root = document) => {
        root.querySelectorAll(SELECTOR).forEach(enhance);
    };

    window.CrmBankSuggestions = {init};
    document.addEventListener("DOMContentLoaded", () => {
        init();
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => mutation.addedNodes.forEach((node) => {
                if (node.nodeType !== 1) return;
                if (node.matches?.(SELECTOR)) enhance(node);
                init(node);
            }));
        });
        observer.observe(document.body, {childList: true, subtree: true});
    });
})();
