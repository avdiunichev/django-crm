(() => {
    "use strict";

    const modalSelector = "[data-safe-delete-modal]";

    const closeModal = (modal) => {
        modal.remove();
        document.body.classList.remove("has-safe-delete-modal");
    };

    const activateModal = (modal, embedded = false) => {
        if (embedded) document.body.append(modal);
        document.body.classList.add("has-safe-delete-modal");
        modal.querySelectorAll("[data-safe-delete-dismiss]").forEach((control) => {
            control.addEventListener("click", (event) => {
                if (embedded) {
                    event.preventDefault();
                    closeModal(modal);
                }
            });
        });
    };

    document.addEventListener("click", async (event) => {
        const link = event.target.closest("a[href*='/delete/']");
        if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        if (document.querySelector(modalSelector)) return;
        event.preventDefault();
        try {
            const response = await fetch(link.href, {headers: {"X-Requested-With": "XMLHttpRequest"}});
            if (!response.ok) throw new Error("Unable to load deletion confirmation");
            const page = new DOMParser().parseFromString(await response.text(), "text/html");
            const modal = page.querySelector(modalSelector);
            if (!modal) {
                window.location.assign(link.href);
                return;
            }
            activateModal(modal, true);
        } catch (error) {
            window.location.assign(link.href);
        }
    });

    const initialModal = document.querySelector(modalSelector);
    if (initialModal) activateModal(initialModal);
})();
