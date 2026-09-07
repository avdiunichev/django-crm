(() => {
    "use strict";

    let modalElement;

    const modal = () => window.UIkit?.modal(modalElement, {
        stack: true,
        bgClose: false
    });

    const ensureModal = () => {
        if (modalElement) return modalElement;
        modalElement = document.createElement("div");
        modalElement.className = "crm-driver-modal";
        modalElement.setAttribute("uk-modal", "stack: true; bg-close: false");
        document.body.appendChild(modalElement);
        return modalElement;
    };

    const showLoading = () => {
        ensureModal().innerHTML = '<div class="uk-modal-dialog uk-modal-body crm-driver-dialog bootstrap-driver-page"><div class="crm-modal-loading"><span uk-spinner></span><span>Открываем карточку водителя…</span></div></div>';
    };

    const notify = (message, status = "warning") => {
        window.UIkit?.notification?.({message, status, pos: "top-center"});
    };

    const render = (html, sourceUrl) => {
        const page = new DOMParser().parseFromString(html, "text/html");
        const heading = page.querySelector(".page-heading");
        const form = page.querySelector("[data-driver-form]");
        if (!heading || !form) throw new Error("Форма водителя не найдена");

        const dialog = document.createElement("div");
        dialog.className = "uk-modal-dialog uk-modal-body crm-driver-dialog bootstrap-driver-page";
        dialog.innerHTML = '<button class="uk-modal-close-default" type="button" uk-close aria-label="Закрыть"></button>';
        dialog.append(heading, form);
        form.action = sourceUrl;
        form.querySelectorAll(".back-link, .form-actions a[href]").forEach((link) => {
            if (link.matches(".uk-button-danger")) return;
            link.addEventListener("click", (event) => {
                event.preventDefault();
                modal()?.hide();
            });
        });

        modalElement.replaceChildren(dialog);
        window.CRMDriverSuggestions?.enhanceWithin(dialog);
        window.CRMDriverPassports?.enhanceWithin(dialog);
        window.CRMDriverLicenses?.enhanceWithin(dialog);
        window.CRMDriverCarriers?.enhanceWithin(dialog);
        window.UIkit?.update?.(modalElement);

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

    const open = async (url) => {
        ensureModal();
        showLoading();
        modal()?.show();
        try {
            const response = await fetch(url, {
                headers: {"X-Requested-With": "XMLHttpRequest"}
            });
            if (!response.ok) throw new Error();
            render(await response.text(), response.url || url);
        } catch (_error) {
            modalElement.innerHTML = '<div class="uk-modal-dialog uk-modal-body crm-driver-dialog bootstrap-driver-page"><button class="uk-modal-close-default" type="button" uk-close></button><div class="uk-alert-danger" uk-alert>Не удалось открыть карточку водителя.</div></div>';
        }
    };

    document.addEventListener("click", (event) => {
        const trigger = event.target.closest("[data-driver-modal]");
        if (!trigger) return;
        event.preventDefault();
        open(trigger.href);
    });
})();
