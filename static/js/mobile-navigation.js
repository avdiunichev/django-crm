(() => {
    const menu = document.querySelector("[data-mobile-nav]");
    const toggle = document.querySelector("[data-mobile-nav-toggle]");
    if (!menu || !toggle) return;

    const close = () => {
        menu.hidden = true;
        toggle.setAttribute("aria-expanded", "false");
        toggle.focus();
    };
    const open = () => {
        menu.hidden = false;
        toggle.setAttribute("aria-expanded", "true");
        menu.querySelector("[data-mobile-nav-close]")?.focus();
    };

    toggle.addEventListener("click", () => (menu.hidden ? open() : close()));
    menu.querySelector("[data-mobile-nav-close]")?.addEventListener("click", close);
    menu.addEventListener("click", (event) => {
        if (event.target === menu) close();
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !menu.hidden) close();
    });
})();
