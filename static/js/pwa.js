(() => {
    if (!("serviceWorker" in navigator)) return;
    window.addEventListener("load", () => {
        navigator.serviceWorker.register("/service-worker.js").catch(() => {
            // Приложение продолжает работать как сайт, если браузер не поддерживает PWA.
        });
    });
})();
