(() => {
    "use strict";

    const CONTENT_SELECTOR = ".main > .content";
    const LINK_SELECTOR = [
        ".crm-desktop-sidebar a[href]",
        ".mobile-nav-list a[href]",
        ".mailbox-folder-tabs a[href]",
        ".organization-profile-tabs a[href]",
        ".trip-profile-tabs a[href]",
    ].join(", ");
    let navigationInProgress = false;

    const isSameDocumentLink = (link) => {
        if (!link || !link.matches(LINK_SELECTOR)) return false;
        if (link.target || link.hasAttribute("download") || link.dataset.mailComposeModalOpen !== undefined) return false;
        if (link.closest("[uk-toggle], [uk-modal-toggle]")) return false;
        const url = new URL(link.href, window.location.href);
        return url.origin === window.location.origin
            && !(url.pathname === window.location.pathname && url.search === window.location.search && url.hash);
    };

    const synchronizeNavigation = (nextDocument) => {
        const nextLinks = new Map(Array.from(nextDocument.querySelectorAll(".mobile-nav-list a[href]"))
            .map((link) => [new URL(link.href, window.location.href).pathname + new URL(link.href, window.location.href).search, link]));
        document.querySelectorAll(".mobile-nav-list a[href]").forEach((link) => {
            const key = new URL(link.href, window.location.href).pathname + new URL(link.href, window.location.href).search;
            const nextLink = nextLinks.get(key);
            const active = Boolean(nextLink?.classList.contains("is-active"));
            link.classList.toggle("is-active", active);
            link.toggleAttribute("aria-current", active);
        });
        document.querySelectorAll(".crm-nav-block").forEach((group) => {
            if (group.querySelector(".is-active")) group.open = true;
        });
    };

    const replaceContent = (html, url, pushState) => {
        const nextDocument = new DOMParser().parseFromString(html, "text/html");
        const currentContent = document.querySelector(CONTENT_SELECTOR);
        const nextContent = nextDocument.querySelector(CONTENT_SELECTOR);
        if (!currentContent || !nextContent) {
            window.location.assign(url);
            return;
        }
        currentContent.replaceChildren(...Array.from(nextContent.childNodes));
        document.title = nextDocument.title || document.title;
        document.body.className = nextDocument.body.className;
        synchronizeNavigation(nextDocument);
        window.UIkit?.update?.(currentContent);
        window.dispatchEvent(new CustomEvent("crm:content-updated", {detail: {root: currentContent}}));
        if (pushState) window.history.pushState({crmPartialNavigation: true}, "", url);
        window.scrollTo({top: 0, behavior: "auto"});
    };

    const navigate = async (url, {pushState = true} = {}) => {
        if (navigationInProgress) return;
        navigationInProgress = true;
        document.documentElement.classList.add("crm-navigation-pending");
        try {
            const response = await fetch(url, {headers: {"X-Requested-With": "CRMPartialNavigation", Accept: "text/html"}, credentials: "same-origin"});
            if (!response.ok || response.redirected) {
                window.location.assign(response.url || url);
                return;
            }
            replaceContent(await response.text(), url, pushState);
        } catch (error) {
            window.location.assign(url);
        } finally {
            navigationInProgress = false;
            document.documentElement.classList.remove("crm-navigation-pending");
        }
    };

    document.addEventListener("click", (event) => {
        if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        const link = event.target.closest("a");
        if (!isSameDocumentLink(link)) return;
        event.preventDefault();
        navigate(link.href);
    });

    document.addEventListener("submit", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== "get" || !form.closest(CONTENT_SELECTOR)) return;
        if (form.matches("[data-no-partial-navigation]")) return;
        event.preventDefault();
        const url = new URL(form.action || window.location.href, window.location.href);
        new FormData(form).forEach((value, key) => url.searchParams.set(key, String(value)));
        navigate(url.href);
    });

    window.addEventListener("popstate", () => navigate(window.location.href, {pushState: false}));
})();
