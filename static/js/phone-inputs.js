(() => {
    "use strict";

    const digitsFor = (value) => {
        let digits = String(value || "").replace(/\D/g, "").slice(0, 11);
        if (digits.startsWith("8")) digits = `7${digits.slice(1)}`;
        if (digits.startsWith("9")) digits = `7${digits}`;
        return digits;
    };

    const displayPhone = (value) => {
        const digits = digitsFor(value);
        if (!digits) return "";
        const valueAfterCode = digits.startsWith("7") ? digits.slice(1) : digits;
        const parts = ["+7"];
        if (valueAfterCode.slice(0, 3)) parts.push(valueAfterCode.slice(0, 3));
        let result = parts.join(" ");
        if (valueAfterCode.length > 3) result += ` ${valueAfterCode.slice(3, 6)}`;
        if (valueAfterCode.length > 6) result += `-${valueAfterCode.slice(6, 8)}`;
        if (valueAfterCode.length > 8) result += `-${valueAfterCode.slice(8, 10)}`;
        return result;
    };

    const isValid = (value) => /^7\d{10}$/.test(digitsFor(value));

    const messageFor = (input) => {
        let message = input.parentElement?.querySelector("[data-phone-warning]");
        if (!message) {
            message = document.createElement("small");
            message.className = "phone-input-warning";
            message.dataset.phoneWarning = "";
            input.insertAdjacentElement("afterend", message);
        }
        return message;
    };

    const validate = (input, showError = true) => {
        const message = messageFor(input);
        const valid = !input.value || isValid(input.value);
        input.classList.toggle("is-phone-invalid", showError && !valid);
        input.setCustomValidity(valid ? "" : "Введите номер в формате +7 900 000-00-00.");
        message.hidden = valid || !showError;
        message.textContent = valid ? "" : "Введите номер в формате +7 900 000-00-00.";
        return valid;
    };

    const enhanceInput = (input) => {
        if (!input || input.dataset.phoneReady === "true") return;
        input.dataset.phoneReady = "true";
        input.addEventListener("input", () => {
            const cursorAtEnd = input.selectionStart === input.value.length;
            input.value = displayPhone(input.value);
            if (cursorAtEnd) input.setSelectionRange(input.value.length, input.value.length);
            validate(input, false);
        });
        input.addEventListener("blur", () => validate(input));
        input.addEventListener("change", () => validate(input));
        if (input.value) input.value = displayPhone(input.value);
        validate(input, false);
    };

    const enhanceWithin = (root = document) => {
        if (root.matches?.("input[data-phone-input], input[name='phone'], input[name$='-phone'], input[name$='_phone']")) enhanceInput(root);
        root.querySelectorAll?.("input[data-phone-input], input[name='phone'], input[name$='-phone'], input[name$='_phone']").forEach(enhanceInput);
    };

    document.addEventListener("DOMContentLoaded", () => enhanceWithin(document));
    window.CRMPhoneInputs = {enhanceWithin};
})();
