(() => {
    "use strict";

    let modalElement;
    const modal = () => window.UIkit?.modal(modalElement, {stack: true, bgClose: false, escClose: false});
    const notify = (message, status = "warning") => window.CRMToasts?.show
        ? window.CRMToasts.show(message, status, 5000)
        : window.UIkit?.notification?.({message, status, pos: "top-center", timeout: 5000});

    const ensureModal = () => {
        if (modalElement) return modalElement;
        modalElement = document.createElement("div");
        modalElement.className = "crm-organization-modal";
        modalElement.setAttribute("uk-modal", "stack: true; bg-close: false; esc-close: false");
        document.body.appendChild(modalElement);
        return modalElement;
    };

    const showLoading = () => {
        ensureModal().innerHTML = '<div class="uk-modal-dialog uk-modal-body crm-organization-dialog organization-form-page"><div class="crm-modal-loading"><span uk-spinner></span><span>Открываем карточку контрагента…</span></div></div>';
    };

    const setField = (dialog, id, value) => {
        const field = dialog.querySelector(`#${id}`);
        if (!field || value === undefined || value === null || value === "") return;
        let normalized = String(value);
        if (id === "id_director_position") {
            normalized = normalized.trim().replace(/\s+/g, " ").toLowerCase();
            normalized = normalized ? `${normalized[0].toUpperCase()}${normalized.slice(1)}` : "";
        }
        if (id === "id_registration_date") {
            const date = /^(\d{4})-(\d{2})-(\d{2})$/.exec(normalized);
            if (date) normalized = `${date[3]}.${date[2]}.${date[1]}`;
        }
        if (id === "id_legal_address") normalized = normalized.toUpperCase();
        field.value = normalized;
        field.dispatchEvent(new Event("change", {bubbles: true}));
    };

    const bindDadata = (dialog) => {
        const tools = dialog.querySelector("[data-dadata-autofill]");
        const button = tools?.querySelector("[data-dadata-button]");
        const status = tools?.querySelector("[data-dadata-status]");
        const form = dialog.querySelector("form.organization-workspace");
        const taxId = form?.querySelector("#id_tax_id");
        if (!tools || !button || !form || !taxId) return;
        button.addEventListener("click", async () => {
            const inn = taxId.value.replace(/\D/g, "");
            if (!/^\d{10}$|^\d{12}$/.test(inn)) {
                if (status) status.textContent = "Укажите ИНН из 10 или 12 цифр.";
                taxId.focus();
                return;
            }
            button.disabled = true;
            if (status) status.textContent = "Получаем реквизиты…";
            try {
                const csrf = form.querySelector('[name="csrfmiddlewaretoken"]')?.value || "";
                const response = await fetch(tools.dataset.url, {
                    method: "POST",
                    headers: {Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "X-CSRFToken": csrf},
                    body: new URLSearchParams({inn})
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.error || "Не удалось получить реквизиты.");
                const party = result.party;
                const values = {
                    id_name: party.full_name, id_short_name: party.short_name, id_tax_id: party.inn,
                    id_kpp: party.kpp, id_ogrn: party.ogrn, id_registration_date: party.registration_date,
                    id_legal_address: party.legal_address, id_legal_address_meta: JSON.stringify(party.address_data || {}),
                    id_director_position: party.director_post, id_director_name: party.director_name,
                    id_verification_status: party.is_invalid || (party.status && party.status !== "ACTIVE") ? "warning" : "verified",
                    id_fns_status: ({ACTIVE: "active", LIQUIDATED: "liquidated", LIQUIDATING: "liquidating", REORGANIZING: "reorganizing", BANKRUPT: "bankrupt"})[party.status] || "unknown"
                };
                Object.entries(values).forEach(([id, value]) => setField(dialog, id, value));
                if (party.organization_type === "INDIVIDUAL") setField(dialog, "id_kind", "entrepreneur");
                const mirror = form.querySelector("[data-tax-id-mirror]");
                if (mirror) mirror.value = taxId.value;
                if (status) status.textContent = "Проверка выполнена: реквизиты заполнены.";
                notify("Проверка выполнена: реквизиты заполнены.", "success");
            } catch (error) {
                const message = error.message || "Не удалось получить реквизиты.";
                if (status) status.textContent = message;
                notify(message, "danger");
            } finally {
                button.disabled = false;
            }
        });
    };

    const bindForm = (dialog, sourceUrl) => {
        const form = dialog.querySelector("form.organization-workspace");
        if (!form) return;
        const submitUrl = new URL(sourceUrl, document.baseURI).href;
        form.setAttribute("action", submitUrl);
        const taxId = form.querySelector("#id_tax_id");
        form.querySelectorAll("[data-tax-id-mirror]").forEach((mirror) => {
            mirror.addEventListener("input", () => {
                taxId.value = mirror.value;
                taxId.dispatchEvent(new Event("input", {bubbles: true}));
            });
            taxId?.addEventListener("input", () => { mirror.value = taxId.value; });
        });
        const ownCompany = form.querySelector("#id_is_own_company");
        const ownCompanyTax = form.querySelector("[data-own-company-tax]");
        const syncOwnCompanyTax = () => ownCompanyTax?.classList.toggle("uk-hidden", !ownCompany?.checked);
        ownCompany?.addEventListener("change", syncOwnCompanyTax);
        syncOwnCompanyTax();
        dialog.querySelectorAll("[data-organization-modal-submit]").forEach((button) => {
            button.addEventListener("click", (event) => {
                event.preventDefault();
                form.requestSubmit(button);
            });
        });
        dialog.addEventListener("click", (event) => {
            const close = event.target.closest("[data-organization-modal-close]");
            if (close) {
                event.preventDefault();
                modal()?.hide();
                return;
            }
            const add = event.target.closest("[data-add-form]");
            if (add) {
                const prefix = add.dataset.addForm;
                const total = form.querySelector(`#id_${prefix}-TOTAL_FORMS`);
                const template = form.querySelector(`#${prefix}-empty-form`);
                const target = form.querySelector(`[data-formset="${prefix}"]`);
                if (total && template && target) {
                    target.insertAdjacentHTML("beforeend", template.innerHTML.replaceAll("__prefix__", total.value));
                    total.value = Number(total.value) + 1;
                }
                return;
            }
            const remove = event.target.closest("[data-remove-bank-account], [data-remove-contact], [data-remove-requisite-change]");
            if (!remove || remove.getAttribute("aria-disabled") === "true") return;
            event.preventDefault();
            const card = remove.closest("[data-bank-account-card], [data-contact-card], [data-requisite-change-card]");
            const deleted = card?.querySelector('[name$="-DELETE"]');
            if (deleted) {
                deleted.checked = true;
                card.classList.add("is-deleted");
            }
        });
        dialog.addEventListener("change", (event) => {
            const toggle = event.target.closest("[data-bank-primary-toggle], [data-contact-primary-toggle]");
            if (!toggle) return;
            const isBank = toggle.matches("[data-bank-primary-toggle]");
            const card = toggle.closest(isBank ? "[data-bank-account-card]" : "[data-contact-card]");
            dialog.querySelectorAll(isBank ? "[data-bank-account-card]" : "[data-contact-card]").forEach((item) => {
                const field = item.querySelector('[name$="-is_primary"]');
                if (field) field.value = item === card ? "True" : "False";
            });
        });
        bindDadata(dialog);
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const submit = event.submitter || form.querySelector('[type="submit"]');
            if (submit) submit.disabled = true;
            try {
                const data = new FormData(form);
                if (submit?.name && !data.has(submit.name)) data.append(submit.name, submit.value);
                const response = await fetch(submitUrl, {
                    method: "POST", body: data, credentials: "same-origin",
                    headers: {"X-Requested-With": "XMLHttpRequest", Accept: "application/json, text/html"}
                });
                const type = response.headers.get("content-type") || "";
                if (response.ok && type.includes("application/json")) {
                    modal()?.hide();
                    notify("Карточка контрагента сохранена.", "success");
                    window.location.reload();
                    return;
                }
                render(await response.text(), submitUrl);
                notify("Проверьте отмеченные поля карточки контрагента.", "danger");
            } catch (_error) {
                notify("Не удалось сохранить контрагента. Проверьте соединение.", "danger");
                if (submit?.isConnected) submit.disabled = false;
            }
        });
    };

    const render = (html, sourceUrl) => {
        const page = new DOMParser().parseFromString(html, "text/html");
        const form = page.querySelector("form.organization-workspace");
        if (!form) throw new Error("Форма контрагента не найдена");
        const commandPanel = form.querySelector(".organization-command-header");
        if (commandPanel) {
            commandPanel.classList.add("organization-modal-command-panel");
            commandPanel.querySelector(".form-section-title")?.remove();
            form.id = "organization-modal-form";
            commandPanel.querySelectorAll('button[type="submit"]').forEach((button) => {
                button.setAttribute("form", form.id);
                button.dataset.organizationModalSubmit = "";
            });
            commandPanel.querySelector('a[href$="/organizations/"]')?.setAttribute("data-organization-modal-close", "");
        }
        const primaryDetails = form.querySelector(".organization-primary-details");
        primaryDetails?.querySelector(".form-section-title > span")?.remove();
        primaryDetails?.classList.add("organization-modal-primary-details");
        const dialog = document.createElement("div");
        dialog.className = "uk-modal-dialog uk-modal-body crm-organization-dialog organization-form-page";
        const scroll = document.createElement("div");
        scroll.className = "organization-modal-scroll";
        scroll.append(form);
        if (commandPanel) dialog.append(commandPanel);
        dialog.append(scroll);
        modalElement.replaceChildren(dialog);
        bindForm(dialog, sourceUrl);
        window.CRMUniversalSelects?.enhanceWithin?.(dialog);
        window.CRMDateInputs?.enhanceWithin?.(dialog);
        window.CRMMoneyInputs?.enhanceWithin?.(dialog);
        window.UIkit?.update?.(modalElement);
    };

    const open = async (url) => {
        ensureModal();
        showLoading();
        modal()?.show();
        try {
            const response = await fetch(url, {headers: {"X-Requested-With": "XMLHttpRequest"}});
            if (!response.ok) throw new Error();
            render(await response.text(), response.url || url);
        } catch (_error) {
            modalElement.innerHTML = '<div class="uk-modal-dialog uk-modal-body crm-organization-dialog organization-form-page"><div class="uk-alert-danger" uk-alert>Не удалось открыть карточку контрагента.</div><button class="uk-button uk-button-default uk-modal-close" type="button">Закрыть</button></div>';
        }
    };

    document.addEventListener("click", (event) => {
        const trigger = event.target.closest("[data-organization-modal]");
        if (!trigger || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        open(trigger.href);
    });
})();
