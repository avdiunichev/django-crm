(() => {
    "use strict";

    const dismiss = (toast) => {
        if (!toast || toast.dataset.dismissing === "true") return;
        toast.dataset.dismissing = "true";
        toast.classList.add("is-dismissing");
        window.setTimeout(() => toast.remove(), 240);
    };

    const initialize = () => {
        document.querySelectorAll("[data-crm-toast]").forEach((toast) => {
            toast.querySelector("[data-crm-toast-close]")?.addEventListener(
                "click",
                () => dismiss(toast),
            );
            const timeout = toast.classList.contains("is-error")
                || toast.classList.contains("is-warning")
                ? 9000
                : 5500;
            window.setTimeout(() => dismiss(toast), timeout);
        });
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize, {once: true});
    } else {
        initialize();
    }
})();
