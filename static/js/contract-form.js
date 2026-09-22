(() => {
    const setVisible = (elements, visible) => elements.forEach((element) => {
        element.hidden = !visible;
        element.querySelectorAll("input, select, textarea").forEach((field) => { field.disabled = !visible; });
    });
    const enhance = (form) => {
        if (!form || form.dataset.contractEnhanced === "true") return;
        form.dataset.contractEnhanced = "true";
        const byId = (id) => form.querySelector(`#${id}`);
        const kind = byId("id_kind");
        const indefinite = byId("id_is_indefinite");
        const renewal = byId("id_auto_renewal");
        const paymentTrigger = byId("id_payment_trigger");
        const expeditorAuthority = byId("id_expeditor_authority_type");
        const counterpartyAuthority = byId("id_counterparty_authority_type");
        const sync = () => {
            const customer = kind?.value === "client_forwarding";
            setVisible([...form.querySelectorAll("[data-contract-customer]")], customer);
            setVisible([...form.querySelectorAll("[data-contract-carrier]")], Boolean(kind?.value) && !customer);
            setVisible([...form.querySelectorAll("[data-contract-valid-until]")], !indefinite?.checked);
            setVisible([...form.querySelectorAll("[data-contract-renewal]")], Boolean(renewal?.checked));
            setVisible([...form.querySelectorAll("[data-contract-payment-other]")], paymentTrigger?.value === "other");
            setVisible([...form.querySelectorAll("[data-contract-expeditor-poa]")], expeditorAuthority?.value === "power_of_attorney");
            setVisible([...form.querySelectorAll("[data-contract-counterparty-poa]")], counterpartyAuthority?.value === "power_of_attorney");
        };
        [kind, indefinite, renewal, paymentTrigger, expeditorAuthority, counterpartyAuthority].filter(Boolean).forEach((field) => field.addEventListener("change", sync));
        sync();
    };
    const enhanceWithin = (root = document) => root.querySelectorAll("[data-contract-form]").forEach(enhance);
    window.CRMContractForm = { enhance, enhanceWithin };
    document.addEventListener("DOMContentLoaded", () => enhanceWithin(document));
})();
