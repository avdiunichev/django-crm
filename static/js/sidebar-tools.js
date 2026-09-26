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
        const desktopNavigation = sidebar.querySelector(".mobile-nav-list");
        const chat = desktopNavigation?.querySelector(':scope > a[href*="/chat"]');
        const profile = tools.querySelector(".personal-settings-link");
        const chatReturnPoint = chat ? document.createComment("crm sidebar chat return point") : null;
        if (chat && chatReturnPoint) desktopNavigation.insertBefore(chatReturnPoint, chat);

        const placeTools = () => {
            if (desktopBreakpoint.matches) {
                if (chat) {
                    chat.classList.add("crm-dock-chat");
                    chat.dataset.chatPopup = "";
                    if (profile) {
                        tools.insertBefore(chat, profile.nextSibling);
                    } else {
                        tools.insertBefore(chat, tools.firstChild);
                    }
                }
                sidebar.appendChild(tools);
            } else {
                header.insertBefore(tools, returnPoint.nextSibling);
                if (chat && chatReturnPoint) {
                    chat.classList.remove("crm-dock-chat");
                    delete chat.dataset.chatPopup;
                    desktopNavigation.insertBefore(chat, chatReturnPoint.nextSibling);
                }
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
