(() => {
    "use strict";

    document.addEventListener("DOMContentLoaded", () => {
        const popup = document.createElement("div");
        popup.className = "crm-chat-popup";
        popup.hidden = true;
        popup.innerHTML = `
            <button class="crm-chat-popup-backdrop" type="button" aria-label="Закрыть чат" data-chat-popup-close></button>
            <section class="crm-chat-popup-panel" role="dialog" aria-modal="true" aria-label="Чат сотрудников">
                <header><strong class="crm-chat-popup-title"><i aria-hidden="true">●</i>Чат сотрудников</strong><span><a href="/chat/" data-chat-popup-full>Открыть отдельно</a><button type="button" aria-label="Закрыть чат" data-chat-popup-close>×</button></span></header>
                <iframe title="Чат сотрудников" data-chat-popup-frame></iframe>
            </section>`;
        document.body.append(popup);

        const frame = popup.querySelector("[data-chat-popup-frame]");
        const fullLink = popup.querySelector("[data-chat-popup-full]");
        let previouslyFocused = null;
        const close = () => {
            popup.hidden = true;
            document.body.classList.remove("chat-popup-is-open");
            previouslyFocused?.focus?.();
        };
        const open = (trigger) => {
            previouslyFocused = trigger;
            const url = new URL(trigger.href, window.location.origin);
            url.searchParams.set("embed", "1");
            if (frame.dataset.source !== url.href) {
                frame.src = url.href;
                frame.dataset.source = url.href;
            }
            fullLink.href = trigger.href;
            popup.hidden = false;
            document.body.classList.add("chat-popup-is-open");
            popup.querySelector("[data-chat-popup-close]")?.focus();
        };
        document.addEventListener("click", (event) => {
            const trigger = event.target.closest("[data-chat-popup]");
            if (!trigger) return;
            event.preventDefault();
            open(trigger);
        });
        popup.querySelectorAll("[data-chat-popup-close]").forEach((button) => button.addEventListener("click", close));
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && !popup.hidden) close();
        });
    });
})();
