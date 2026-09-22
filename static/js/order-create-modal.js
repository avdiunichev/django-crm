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

    const open = async (url) => {
        ensureModal();
        const target = new URL(url, window.location.href);
        target.searchParams.set("modal", "1");
        const loading = modalElement.querySelector(".crm-order-modal-loading");
        loading.hidden = false;
        frame.hidden = true;
        frame.removeAttribute("src");
        frame.srcdoc = "";
        modal()?.show();
        try {
            const response = await fetch(target.href, {
                credentials: "same-origin",
                headers: {"X-Requested-With": "XMLHttpRequest"},
            });
            if (response.redirected && new URL(response.url).pathname.startsWith("/login/")) {
                window.location.assign(response.url);
                return;
            }
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            let html = await response.text();
            const base = `<base href="${target.href.replaceAll('"', '&quot;')}">`;
            html = /<head(?:\s[^>]*)?>/i.test(html)
                ? html.replace(/<head(?:\s[^>]*)?>/i, (head) => `${head}${base}`)
                : `${base}${html}`;
            frame.srcdoc = html;
        } catch (_error) {
            loading.hidden = true;
            frame.hidden = true;
            window.CRMToasts?.show(
                "Не удалось открыть форму заказа. Обновите страницу и повторите попытку.",
                "error",
                5000,
            );
        }
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
        if (event.data.action === "saved") {
            modal()?.hide();
            if (event.data.url && event.data.openUrl) window.location.assign(event.data.url);
            else window.location.reload();
        }
    });

    document.addEventListener("DOMContentLoaded", () => {
        if (!document.body.classList.contains("order-modal-page") || window.parent === window) return;
        document.querySelectorAll("[data-order-modal-close]").forEach((control) => {
            control.addEventListener("click", (event) => {
                event.preventDefault();
                window.parent.postMessage({type: messageType, action: "close"}, window.location.origin);
            });
        });
        const form = document.querySelector("[data-order-form]");
        if (!form || form.dataset.modalSubmitReady === "true") return;
        form.dataset.modalSubmitReady = "true";
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const submitter = event.submitter;
            const data = new FormData(form);
            const actionUrl = new URL(form.getAttribute("action") || document.baseURI, document.baseURI).href;
            if (submitter?.name) data.set(submitter.name, submitter.value);
            const buttons = form.querySelectorAll('button[type="submit"]');
            buttons.forEach((button) => { button.disabled = true; });
            form.setAttribute("aria-busy", "true");
            try {
                const response = await fetch(actionUrl, {
                    method: "POST",
                    body: data,
                    credentials: "same-origin",
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                        "Accept": "application/json, text/html",
                    },
                });
                const contentType = response.headers.get("content-type") || "";
                if (contentType.includes("application/json")) {
                    const payload = await response.json();
                    if (!response.ok || !payload.ok) throw new Error(payload.message || "Заказ не сохранён.");
                    if (payload.action === "save_stay") {
                        window.location.assign(payload.url);
                        return;
                    }
                    window.parent.postMessage({
                        type: messageType,
                        action: "saved",
                        url: payload.url,
                        openUrl: payload.action === "assign",
                    }, window.location.origin);
                    return;
                }
                let html = await response.text();
                const base = `<base href="${actionUrl.replaceAll('"', '&quot;')}">`;
                html = /<head(?:\s[^>]*)?>/i.test(html)
                    ? html.replace(/<head(?:\s[^>]*)?>/i, (head) => `${head}${base}`)
                    : `${base}${html}`;
                document.open();
                document.write(html);
                document.close();
            } catch (error) {
                window.CRMToasts?.show(error.message || "Не удалось сохранить заказ.", "error", 5000);
                buttons.forEach((button) => { button.disabled = false; });
                form.removeAttribute("aria-busy");
            }
        });
    });
})();
