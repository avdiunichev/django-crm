(() => {
    "use strict";

    const messageType = "crm-order-create-modal";
    let modalElement;
    let frame;

    const modal = () => window.UIkit?.modal(modalElement, {
        stack: true,
        bgClose: false,
        escClose: false,
    });

    const ensureModal = () => {
        if (modalElement) return modalElement;
        modalElement = document.createElement("div");
        modalElement.className = "crm-order-create-modal";
        modalElement.setAttribute("uk-modal", "stack: true; bg-close: false; esc-close: false");
        const dialog = document.createElement("div");
        dialog.className = "uk-modal-dialog crm-order-create-dialog";
        const loading = document.createElement("div");
        loading.className = "crm-order-modal-loading";
        loading.innerHTML = '<span uk-spinner></span><span>Открываем форму заказа…</span>';
        frame = document.createElement("iframe");
        frame.className = "crm-order-create-frame";
        frame.title = "Добавление нового заказа";
        frame.hidden = true;
        dialog.append(loading, frame);
        modalElement.append(dialog);
        document.body.append(modalElement);

        frame.addEventListener("load", () => {
            let frameUrl;
            try {
                frameUrl = new URL(frame.contentWindow.location.href);
            } catch (_error) {
                return;
            }
            if (frameUrl.pathname === "/orders/") {
                modal()?.hide();
                window.location.reload();
                return;
            }
            if (frameUrl.pathname.startsWith("/transportations/")) {
                window.location.assign(frameUrl.href);
                return;
            }
            loading.hidden = true;
            frame.hidden = false;
        });
        return modalElement;
    };

    const open = (url) => {
        ensureModal();
        const target = new URL(url, window.location.href);
        target.searchParams.set("modal", "1");
        const loading = modalElement.querySelector(".crm-order-modal-loading");
        loading.hidden = false;
        frame.hidden = true;
        frame.src = target.href;
        modal()?.show();
    };

    document.addEventListener("click", (event) => {
        const trigger = event.target.closest("[data-order-create-modal]");
        if (!trigger) return;
        event.preventDefault();
        open(trigger.href);
    });

    window.addEventListener("message", (event) => {
        if (event.origin !== window.location.origin || event.data?.type !== messageType) return;
        if (event.data.action === "close") modal()?.hide();
    });

    document.addEventListener("DOMContentLoaded", () => {
        if (!document.body.classList.contains("order-modal-page") || window.parent === window) return;
        document.querySelectorAll("[data-order-modal-close]").forEach((control) => {
            control.addEventListener("click", (event) => {
                event.preventDefault();
                window.parent.postMessage({type: messageType, action: "close"}, window.location.origin);
            });
        });
    });
})();
