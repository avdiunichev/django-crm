(() => {
    const content = document.querySelector('.transportations-workspace-page .main > .content');
    if (!content) return;
    const resize = () => {
        // Keep the toolbar outside the scroll area; only the table rows scroll.
        const top = content.getBoundingClientRect().top;
        content.style.setProperty('--register-height', `${Math.max(320, window.innerHeight - top - 16)}px`);
    };
    resize();
    window.addEventListener('resize', resize);
})();
