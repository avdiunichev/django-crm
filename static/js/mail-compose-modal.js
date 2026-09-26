(() => {
    document.addEventListener("DOMContentLoaded", () => {
        const modal = document.getElementById("mail-compose-modal");
        if (!modal || !window.UIkit) return;
        const dialog = UIkit.modal(modal);
        document.addEventListener("click", (event) => {
            const trigger = event.target.closest("[data-mail-compose-modal-open]");
            if (!trigger) return;
            event.preventDefault();
            dialog.show();
        });
    });
})();
