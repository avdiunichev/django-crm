(() => {
    "use strict";

    const desktopBreakpoint = window.matchMedia("(min-width: 1200px)");

    document.addEventListener("DOMContentLoaded", () => {
        const tools = document.querySelector(".crm-topnav-tools");
        const sidebar = document.querySelector(".crm-desktop-sidebar");
        const header = document.querySelector(".crm-topnav");
        if (!tools || !sidebar || !header) return;

        const returnPoint = document.createComment("crm sidebar tools return point");
        header.insertBefore(returnPoint, tools);

        const placeTools = () => {
            if (desktopBreakpoint.matches) {
                sidebar.appendChild(tools);
            } else {
                header.insertBefore(tools, returnPoint.nextSibling);
            }
        };

        placeTools();
        if (typeof desktopBreakpoint.addEventListener === "function") {
            desktopBreakpoint.addEventListener("change", placeTools);
        } else {
            desktopBreakpoint.addListener(placeTools);
        }
    });
})();
