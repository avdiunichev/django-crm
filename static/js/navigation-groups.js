/* Progressive enhancement: without JavaScript all permitted links stay visible. */
(() => {
    document.querySelectorAll('.mobile-nav-list').forEach((nav) => {
        nav.querySelectorAll(':scope > .mobile-nav-group').forEach((heading) => {
            const group = document.createElement('details');
            group.className = 'crm-nav-block';
            const summary = document.createElement('summary');
            summary.className = 'crm-nav-block-title';
            while (heading.firstChild) summary.append(heading.firstChild);
            heading.replaceWith(group);
            group.append(summary);
            const links = document.createElement('div');
            links.className = 'crm-nav-block-links';
            while (group.nextElementSibling?.classList.contains('mobile-nav-subitem')) {
                links.append(group.nextElementSibling);
            }
            group.append(links);
            group.open = Boolean(links.querySelector('.is-active'));
            links.querySelectorAll('.is-active').forEach((link) => link.setAttribute('aria-current', 'page'));
        });
    });
})();
