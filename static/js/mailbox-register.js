(() => {
    "use strict";

    const init = (root = document) => {
        const selectAll = root.querySelector("[data-mailbox-select-all]");
        const button = root.querySelector("#mailbox-delete-selected");
        const markReadButton = root.querySelector("#mailbox-mark-read-selected");
        if (!button || !markReadButton || button.dataset.mailboxRegisterReady === "true") return;
        button.dataset.mailboxRegisterReady = "true";
        const selected = () => Array.from(root.querySelectorAll(".mailbox-message-select:checked"));
        const update = () => {
            const count = selected().length;
            button.disabled = count === 0;
            markReadButton.disabled = count === 0;
            button.textContent = count > 1 ? button.dataset.multipleLabel : button.dataset.singleLabel;
            if (selectAll) selectAll.checked = count > 0 && count === root.querySelectorAll(".mailbox-message-select").length;
        };
        selectAll?.addEventListener("change", () => {
            root.querySelectorAll(".mailbox-message-select").forEach((box) => { box.checked = selectAll.checked; });
            update();
        });
        root.querySelectorAll(".mailbox-message-select").forEach((box) => box.addEventListener("change", update));
        root.querySelectorAll(".mailbox-message-row").forEach((row) => row.addEventListener("click", (event) => {
            if (event.target.closest("input, a, button, label")) return;
            window.location.assign(row.dataset.mailboxMessageUrl);
        }));
        update();
    };

    window.CrmMailboxRegister = {init};
    document.addEventListener("DOMContentLoaded", () => init());
    window.addEventListener("crm:content-updated", (event) => init(event.detail.root));
})();
