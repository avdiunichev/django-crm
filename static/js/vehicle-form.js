(() => {
    "use strict";

    const TRACTOR = "tractor";
    const OPTIONAL_SELECTOR = "[data-vehicle-tractor-optional]";

    const enhance = (kindField) => {
        if (!kindField || kindField.dataset.vehicleKindReady === "true") return;
        kindField.dataset.vehicleKindReady = "true";
        const form = kindField.closest("form");
        if (!form) return;

        const optionalFields = () => Array.from(
            form.querySelectorAll(OPTIONAL_SELECTOR)
        );
        const attachmentSection = form.querySelector("[data-vehicle-attachment-section]");
        const attachmentCard = form.querySelector("[data-vehicle-attachment-card]");
        const attachmentToggle = form.querySelector("input[name$='-enabled']");
        const attachmentKind = form.querySelector("[data-vehicle-attachment-kind]");
        const attachmentTitle = form.querySelector("[data-vehicle-attachment-title]");
        const sync = () => {
            const hidden = kindField.value === TRACTOR;
            optionalFields().forEach((field) => {
                const container = field.closest(".field") || field.parentElement;
                if (container) container.hidden = hidden;
                field.setAttribute("aria-hidden", hidden ? "true" : "false");
            });
            form.classList.toggle("is-tractor", hidden);
            const canAttach = [TRACTOR, "truck"].includes(kindField.value);
            if (attachmentSection) attachmentSection.hidden = !canAttach;
            const expectedKind = kindField.value === TRACTOR ? "semitrailer" : "trailer";
            if (attachmentKind && canAttach) {
                attachmentKind.value = expectedKind;
                Array.from(attachmentKind.options).forEach((option) => {
                    option.hidden = option.value && option.value !== expectedKind;
                });
            }
            if (attachmentTitle) {
                attachmentTitle.textContent = kindField.value === TRACTOR ? "Полуприцеп" : "Прицеп";
            }
            if (attachmentCard) {
                attachmentCard.hidden = !canAttach || !attachmentToggle?.checked;
            }
        };

        kindField.addEventListener("change", sync);
        attachmentToggle?.addEventListener("change", sync);
        sync();
    };

    const enhanceWithin = (root = document) => {
        if (root.matches?.("[data-vehicle-kind]")) enhance(root);
        root.querySelectorAll?.("[data-vehicle-kind]").forEach(enhance);
    };

    document.addEventListener("DOMContentLoaded", () => {
        enhanceWithin(document);
        const observer = new MutationObserver((records) => {
            records.forEach((record) => record.addedNodes.forEach((node) => {
                if (node instanceof Element) enhanceWithin(node);
            }));
        });
        observer.observe(document.body, {childList: true, subtree: true});
    });

    window.CRMVehicleForm = {enhance, enhanceWithin};
})();
