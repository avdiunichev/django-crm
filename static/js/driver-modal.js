(() => {
    "use strict";

    let modalElement;
    const stateKey = "crm-driver-modal-draft";

    const modal = () => window.UIkit?.modal(modalElement, {
        stack: true,
        bgClose: false,
        escClose: false
    });

    const clearDraft = () => window.sessionStorage.removeItem(stateKey);

    const saveDraft = (sourceUrl, form) => {
        if (!sourceUrl || !form) return;
        const fields = Array.from(form.elements)
            .filter((field) => field.name && !["submit", "button", "reset"].includes(field.type))
            .map((field) => ({
                name: field.name,
                value: field.value,
                type: field.type,
                checked: Boolean(field.checked)
            }));
        window.sessionStorage.setItem(stateKey, JSON.stringify({sourceUrl, fields}));
    };

    const loadDraft = () => {
        try {
            return JSON.parse(window.sessionStorage.getItem(stateKey) || "null");
        } catch (_error) {
            clearDraft();
            return null;
        }
    };

    const ensureModal = () => {
        if (modalElement) return modalElement;
        modalElement = document.createElement("div");
        modalElement.className = "crm-driver-modal";
        modalElement.setAttribute("uk-modal", "stack: true; bg-close: false; esc-close: false");
        document.body.appendChild(modalElement);
        return modalElement;
    };

    const showLoading = () => {
        ensureModal().innerHTML = '<div class="uk-modal-dialog uk-modal-body crm-driver-dialog bootstrap-driver-page"><div class="crm-modal-loading"><span uk-spinner></span><span>Открываем карточку водителя…</span></div></div>';
    };

    const notify = (message, status = "warning") => {
        window.UIkit?.notification?.({message, status, pos: "top-center"});
    };

    const restoreDraft = (form, draft) => {
        if (!draft?.fields?.length) return;
        const fieldValue = (name) => draft.fields.find((field) => field.name === name)?.value;
        const addRows = (prefix, trigger) => {
            const total = Number(fieldValue(`${prefix}-TOTAL_FORMS`) || 0);
            const totalField = form.elements.namedItem(`${prefix}-TOTAL_FORMS`);
            while (totalField && Number(totalField.value) < total) form.querySelector(trigger)?.click();
        };
        addRows("employments", "[data-employment-add]");
        addRows("passports", "[data-passport-add]");
        addRows("licenses", "[data-license-add]");
        draft.fields.forEach((saved) => {
            const field = form.elements.namedItem(saved.name);
            if (!field || field instanceof RadioNodeList) return;
            if (["checkbox", "radio"].includes(saved.type)) field.checked = saved.checked;
            else field.value = saved.value;
            field.dispatchEvent(new Event("change", {bubbles: true}));
        });
    };

    const render = (html, sourceUrl, draft = null) => {
        const page = new DOMParser().parseFromString(html, "text/html");
        const form = page.querySelector("[data-driver-form]");
        const heading = page.querySelector(".page-heading");
        if (!form) throw new Error("Форма водителя не найдена");

        const dialog = document.createElement("div");
        dialog.className = "uk-modal-dialog uk-modal-body crm-driver-dialog bootstrap-driver-page driver-form-page";
        // The renewed card keeps its command panel inside the form.  The old
        // version had a separate page heading, so support both structures.
        if (heading && !form.contains(heading)) dialog.append(heading);
        dialog.append(form);
        form.action = sourceUrl;
        form.querySelectorAll(".back-link, .form-actions a[href], .driver-command-panel a[href]").forEach((link) => {
            if (link.matches(".uk-button-danger")) return;
            link.addEventListener("click", (event) => {
                event.preventDefault();
                clearDraft();
                modal()?.hide();
            });
        });

        modalElement.replaceChildren(dialog);
        window.CRMDriverSuggestions?.enhanceWithin(dialog);
        window.CRMDriverPassports?.enhanceWithin(dialog);
        window.CRMDriverLicenses?.enhanceWithin(dialog);
        window.CRMDriverCarriers?.enhanceWithin(dialog);
        restoreDraft(form, draft);
        window.UIkit?.update?.(modalElement);

        const remember = () => saveDraft(sourceUrl, form);
        form.addEventListener("input", remember);
        form.addEventListener("change", remember);
        remember();

        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const submit = form.querySelector('[type="submit"]');
            if (submit) submit.disabled = true;
            try {
                const response = await fetch(sourceUrl, {
                    method: "POST",
                    body: new FormData(form),
                    headers: {
                        "Accept": "application/json, text/html",
                        "X-Requested-With": "XMLHttpRequest"
                    }
                });
                const contentType = response.headers.get("content-type") || "";
                if (response.ok && contentType.includes("application/json")) {
                    const result = await response.json();
                    clearDraft();
                    modal()?.hide();
                    notify("Водитель создан.", "success");
                    window.location.assign(result.url);
                    return;
                }
                render(await response.text(), sourceUrl);
            } catch (_error) {
                notify("Не удалось сохранить водителя. Проверьте соединение.", "danger");
                if (submit?.isConnected) submit.disabled = false;
            }
        });
    };

    const open = async (url, draft = null) => {
        ensureModal();
        showLoading();
        modal()?.show();
        try {
            const response = await fetch(url, {
                headers: {"X-Requested-With": "XMLHttpRequest"}
            });
            if (!response.ok) throw new Error();
            render(await response.text(), response.url || url, draft);
        } catch (_error) {
            modalElement.innerHTML = '<div class="uk-modal-dialog uk-modal-body crm-driver-dialog bootstrap-driver-page"><div class="uk-alert-danger" uk-alert>Не удалось открыть карточку водителя.</div></div>';
        }
    };

    document.addEventListener("click", (event) => {
        const trigger = event.target.closest("[data-driver-modal]");
        if (!trigger) return;
        event.preventDefault();
        clearDraft();
        open(trigger.href);
    });

    window.addEventListener("DOMContentLoaded", () => {
        const draft = loadDraft();
        if (draft?.sourceUrl) open(draft.sourceUrl, draft);
    });
})();
