(() => {
    "use strict";

    let modalElement;
    let sourceUrl = "";
    const draftKey = "crm-vehicle-modal-draft";

    const notify = (message, status = "warning") => {
        if (window.CRMToasts?.show) return window.CRMToasts.show(message, status, 5000);
        window.UIkit?.notification?.({message, status, pos: "top-center", timeout: 5000});
    };

    const modal = () => window.UIkit?.modal(modalElement, {
        stack: true, bgClose: false, escClose: false
    });

    const ensureModal = () => {
        if (modalElement) return modalElement;
        modalElement = document.createElement("div");
        modalElement.className = "crm-vehicle-modal";
        modalElement.setAttribute("uk-modal", "stack: true; bg-close: false; esc-close: false");
        document.body.appendChild(modalElement);
        return modalElement;
    };

    const clearDraft = () => window.sessionStorage.removeItem(draftKey);

    const saveDraft = (form) => {
        const fields = Array.from(form.elements)
            .filter((field) => field.name && !["submit", "button", "reset"].includes(field.type))
            .map((field) => ({name: field.name, value: field.value, type: field.type, checked: field.checked}));
        window.sessionStorage.setItem(draftKey, JSON.stringify({sourceUrl, fields}));
    };

    const restoreDraft = (form, draft) => {
        if (!draft?.fields?.length) return;
        draft.fields.forEach((saved) => {
            const field = form.elements.namedItem(saved.name);
            if (!field || field instanceof RadioNodeList) return;
            if (["checkbox", "radio"].includes(saved.type)) field.checked = saved.checked;
            else field.value = saved.value;
            field.dispatchEvent(new Event("change", {bubbles: true}));
        });
    };

    const render = (html, draft = null, showErrors = false) => {
        const page = new DOMParser().parseFromString(html, "text/html");
        const form = page.querySelector("[data-vehicle-form]");
        if (!form) throw new Error("Форма транспорта не найдена");

        const dialog = document.createElement("div");
        dialog.className = "uk-modal-dialog uk-modal-body crm-vehicle-dialog vehicle-form-page";
        dialog.append(form);
        form.action = sourceUrl;
        form.querySelectorAll(".order-command-actions a[href]").forEach((link) => {
            if (link.matches(".driver-delete-button, a[href*='/delete/']")) return;
            link.addEventListener("click", (event) => {
                event.preventDefault();
                clearDraft();
                modal()?.hide();
            });
        });
        modalElement.replaceChildren(dialog);
        window.CRMVehicleForm?.enhanceWithin(dialog);
        window.CRMVehicleCarriers?.enhanceWithin(dialog);
        restoreDraft(form, draft);
        window.UIkit?.update?.(modalElement);

        if (showErrors) notify("Заполните обязательное поле", "danger");
        const remember = () => saveDraft(form);
        form.addEventListener("input", remember);
        form.addEventListener("change", remember);
        remember();

        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const submit = event.submitter || form.querySelector('[type="submit"]');
            if (submit) submit.disabled = true;
            try {
                const data = new FormData(form);
                if (submit?.name) data.set(submit.name, submit.value);
                const response = await fetch(sourceUrl, {
                    method: "POST", body: data,
                    headers: {Accept: "application/json, text/html", "X-Requested-With": "XMLHttpRequest"}
                });
                const contentType = response.headers.get("content-type") || "";
                if (response.ok && contentType.includes("application/json")) {
                    const result = await response.json();
                    clearDraft();
                    notify(result.message || "Карточка транспорта сохранена.", "success");
                    document.dispatchEvent(new CustomEvent("crm:entity-saved", {
                        detail: {type: "vehicle", id: result.item?.id, action: result.action, item: result.item}
                    }));
                    if (result.action === "save") {
                        sourceUrl = result.url;
                        await open(sourceUrl);
                    } else {
                        modal()?.hide();
                        window.location.reload();
                    }
                    return;
                }
                render(await response.text(), null, true);
            } catch (_error) {
                notify("Не удалось сохранить транспорт. Проверьте соединение.", "danger");
                if (submit?.isConnected) submit.disabled = false;
            }
        });
    };

    const open = async (url, draft = null) => {
        sourceUrl = url;
        ensureModal();
        modalElement.innerHTML = '<div class="uk-modal-dialog uk-modal-body crm-vehicle-dialog"><div class="crm-modal-loading"><span uk-spinner></span><span>Открываем карточку транспорта…</span></div></div>';
        modal()?.show();
        try {
            const response = await fetch(url, {headers: {"X-Requested-With": "XMLHttpRequest"}});
            if (!response.ok) throw new Error();
            render(await response.text(), draft);
        } catch (_error) {
            modalElement.innerHTML = '<div class="uk-modal-dialog uk-modal-body crm-vehicle-dialog"><div class="uk-alert-danger" uk-alert>Не удалось открыть карточку транспорта.</div></div>';
        }
    };

    document.addEventListener("click", (event) => {
        const trigger = event.target.closest("[data-vehicle-modal]");
        if (!trigger) return;
        event.preventDefault();
        clearDraft();
        open(trigger.href);
    });

    window.addEventListener("DOMContentLoaded", () => {
        try {
            const draft = JSON.parse(window.sessionStorage.getItem(draftKey) || "null");
            if (draft?.sourceUrl) open(draft.sourceUrl, draft);
        } catch (_error) {
            clearDraft();
        }
    });
})();
