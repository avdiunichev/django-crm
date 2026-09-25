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
        const expeditor = byId("id_expeditor");
        const customerField = byId("id_customer");
        const carrier = byId("id_carrier");
        const defaultsUrl = form.dataset.partyDefaultsUrl;
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
        const applyValues = (values) => Object.entries(values || {}).forEach(([name, value]) => {
            const field = form.elements.namedItem(name);
            if (!field) return;
            field.value = value ?? "";
            field.dispatchEvent(new Event("change", { bubbles: true }));
        });
        const loadPartyDefaults = async (party, side) => {
            if (!defaultsUrl || !party?.value) return;
            const selectedId = party.value;
            try {
                const query = new URLSearchParams({ party: party.name.replace("id_", ""), id: selectedId, side });
                const response = await fetch(`${defaultsUrl}?${query.toString()}`, {
                    headers: { Accept: "application/json" },
                    credentials: "same-origin",
                });
                const payload = await response.json();
                if (response.ok && payload.ok && party.value === selectedId) applyValues(payload.values);
            } catch (_) {
                // Form remains usable when a request is temporarily unavailable.
            }
        };
        expeditor?.addEventListener("change", () => loadPartyDefaults(expeditor, "expeditor"));
        customerField?.addEventListener("change", () => loadPartyDefaults(customerField, "counterparty"));
        carrier?.addEventListener("change", () => loadPartyDefaults(carrier, "counterparty"));
        kind?.addEventListener("change", () => {
            const party = kind.value === "client_forwarding" ? customerField : carrier;
            loadPartyDefaults(party, "counterparty");
        });
        sync();
    };
    const enhanceWithin = (root = document) => root.querySelectorAll("[data-contract-form]").forEach(enhance);
    window.CRMContractForm = { enhance, enhanceWithin };
    document.addEventListener("DOMContentLoaded", () => enhanceWithin(document));
})();
