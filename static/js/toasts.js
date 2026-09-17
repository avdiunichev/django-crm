(() => {
    "use strict";

    const dismiss = (toast) => {
        if (!toast || toast.dataset.dismissing === "true") return;
        toast.dataset.dismissing = "true";
        toast.classList.add("is-dismissing");
        window.setTimeout(() => toast.remove(), 240);
    };

    const bind = (toast, timeout = 5000) => {
        toast.querySelector("[data-crm-toast-close]")?.addEventListener(
            "click",
            () => dismiss(toast),
        );
        window.setTimeout(() => dismiss(toast), Math.max(5000, timeout));
    };

    const show = (message, kind = "info", timeout = 5000) => {
        let stack = document.querySelector(".crm-toast-stack");
        if (!stack) {
            stack = document.createElement("div");
            stack.className = "crm-toast-stack";
            stack.setAttribute("aria-live", "polite");
            document.body.append(stack);
        }
        const toast = document.createElement("div");
        toast.className = `crm-toast is-${kind}`;
        toast.setAttribute("role", "status");
        toast.dataset.crmToast = "";
        const icon = document.createElement("span");
        icon.className = "crm-toast-icon";
        icon.textContent = kind === "success" ? "✓" : kind === "error" ? "!" : "i";
        const text = document.createElement("p");
        text.textContent = message;
        const close = document.createElement("button");
        close.className = "crm-toast-close";
        close.type = "button";
        close.setAttribute("aria-label", "Закрыть уведомление");
        close.dataset.crmToastClose = "";
        close.textContent = "×";
        toast.append(icon, text, close);
        stack.append(toast);
        bind(toast, timeout);
    };

    const initialize = () => {
        document.querySelectorAll("[data-crm-toast]").forEach(bind);
    };

    window.CRMToasts = {show};

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize, {once: true});
    } else {
        initialize();
    }
})();
