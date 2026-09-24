(() => {
    "use strict";
    // Popovers retain their DOM parent and event handlers, but paint outside
    // overflow/transform/stacking contexts, including scrollable modal cards.
    const selector = ".crm-smart-dropdown, .crm-address-dropdown";
    const entries = new Map();
    let frame = 0;
    const set = (node, key, value) => {
        if (node.style.getPropertyValue(key) !== value) node.style.setProperty(key, value, "important");
    };
    const close = (menu, entry) => {
        menu.hidden = true;
        entry.anchor.setAttribute("aria-expanded", "false");
        if (entry.topLayer && menu.matches(":popover-open")) menu.hidePopover();
        if (!entry.topLayer && entry.home.isConnected && menu.parentNode !== entry.home) {
            entry.home.appendChild(menu);
        }
    };
    const place = (menu, entry) => {
        const rect = entry.anchor.getBoundingClientRect();
        const viewport = window.visualViewport;
        const left = viewport?.offsetLeft || 0;
        const top = viewport?.offsetTop || 0;
        const width = viewport?.width || document.documentElement.clientWidth;
        const height = viewport?.height || document.documentElement.clientHeight;
        if (!rect.width || !rect.height || rect.bottom <= top || rect.top >= top + height) {
            close(menu, entry);
            return;
        }
        for (let parent = entry.home; parent && parent !== document.body; parent = parent.parentElement) {
            if (!/(auto|scroll|hidden|clip)/.test(getComputedStyle(parent).overflowY)) continue;
            const clip = parent.getBoundingClientRect();
            if (rect.bottom <= clip.top || rect.top >= clip.bottom) {
                close(menu, entry);
                return;
            }
        }
        const gap = 4, margin = 8;
        const menuWidth = Math.min(menu.classList.contains("crm-date-dropdown") ? 300 : rect.width, width - margin * 2);
        const below = Math.max(0, top + height - rect.bottom - gap - margin);
        const above = Math.max(0, rect.top - top - gap - margin);
        const desired = menu.classList.contains("crm-date-dropdown") ? 380 : 320;
        const upwards = below < Math.min(desired, menu.scrollHeight) && above > below;
        const available = Math.min(desired, upwards ? above : below);
        set(menu, "width", menuWidth + "px");
        set(menu, "min-width", "0px");
        set(menu, "max-height", available + "px");
        set(menu, "left", Math.max(left + margin, Math.min(rect.left, left + width - menuWidth - margin)) + "px");
        set(menu, "top", (upwards ? rect.top - gap - Math.min(menu.scrollHeight + 2, available) : rect.bottom + gap) + "px");
    };
    const update = () => {
        frame = 0;
        let active = false;
        for (const [menu, entry] of entries) {
            if (!entry.home.isConnected || !entry.anchor.isConnected || !menu.isConnected) {
                close(menu, entry);
                if (!entry.topLayer) menu.remove();
                entries.delete(menu);
                continue;
            }
            if (menu.hidden) {
                if (entry.topLayer && menu.matches(":popover-open")) menu.hidePopover();
                if (!entry.topLayer && menu.parentNode !== entry.home) entry.home.appendChild(menu);
                continue;
            }
            active = true;
            if (entry.topLayer) {
                if (!menu.matches(":popover-open")) menu.showPopover();
            } else if (menu.parentNode === entry.home) {
                (entry.home.closest(".uk-modal") || document.body).appendChild(menu);
            }
            place(menu, entry);
        }
        // Follow scrolling, modal animations, resized fields and mobile keyboards.
        if (active) frame = requestAnimationFrame(update);
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(update); };
    const register = (menu) => {
        if (entries.has(menu)) return;
        const home = menu.parentElement;
        const anchor = home?.querySelector("input:not([type=hidden]), button, select");
        if (!anchor) return;
        const topLayer = typeof menu.showPopover === "function";
        entries.set(menu, { home, anchor, topLayer });
        if (topLayer) menu.setAttribute("popover", "manual");
        menu.classList.add("crm-floating-dropdown");
        for (const [key, value] of Object.entries({
            position: "fixed", margin: "0px", right: "auto", bottom: "auto",
            "box-sizing": "border-box", "z-index": "2147483000",
            transform: "none", "min-height": "0px", overflow: "auto"
        })) set(menu, key, value);
    };
    const scan = (root) => {
        if (root.nodeType !== Node.ELEMENT_NODE) return;
        if (root.matches(selector)) register(root);
        root.querySelectorAll(selector).forEach(register);
    };
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => mutation.addedNodes.forEach(scan));
        schedule();
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden"] });
    scan(document.body);
    schedule();
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") entries.forEach((entry, menu) => close(menu, entry));
    });
    document.addEventListener("pointerdown", (event) => {
        entries.forEach((entry, menu) => {
            if (!menu.hidden && !entry.home.contains(event.target) && !menu.contains(event.target)) close(menu, entry);
        });
    }, true);
})();
