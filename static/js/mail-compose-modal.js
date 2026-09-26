(() => {
    document.addEventListener("DOMContentLoaded", () => {
        const modal = document.getElementById("mail-compose-modal");
        if (!modal || !window.UIkit) return;
        const dialog = UIkit.modal(modal);
        document.querySelectorAll("[data-mail-compose-modal-open]").forEach((trigger) => {
            trigger.addEventListener("click", (event) => {
                event.preventDefault();
                dialog.show();
            });
        });
    });
})();
