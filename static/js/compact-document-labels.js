(() => {
    "use strict";
    const compact = (root = document) => {
        root.querySelectorAll?.(".transportation-register-documents > div > span").forEach((label) => {
            const value = label.textContent.trim().toLowerCase();
            if (value.startsWith("вход")) label.textContent = "Вх.";
            if (value.startsWith("исход")) label.textContent = "Исх.";
        });
    };
    document.addEventListener("DOMContentLoaded", () => {
        compact();
        new MutationObserver(() => compact()).observe(document.body, {childList: true, subtree: true});
    });
})();
