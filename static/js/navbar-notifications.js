(() => {
    const center = document.querySelector("[data-navbar-notifications]");
    if (!center) return;
    const toggle = center.querySelector("[data-navbar-notification-toggle]");
    const menu = center.querySelector("[data-navbar-notification-menu]");
    const close = () => { menu.hidden = true; toggle.setAttribute("aria-expanded", "false"); };
    toggle.addEventListener("click", () => {
        const open = menu.hidden;
        menu.hidden = !open;
        toggle.setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("click", (event) => { if (!center.contains(event.target)) close(); });
})();
