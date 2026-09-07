(() => {
    const SMART_SELECTOR = "select[data-smart-select]";
    const normalize = (value) => String(value || "").toLocaleLowerCase("ru-RU").trim();
    let transportationModalElement;
    let quickModalElement;
    let activeQuickSelect;
    let activeQuickQuery = "";

    const modalInstance = (element) => window.UIkit?.modal(element, {stack: true});

    const ensureModal = (kind) => {
        const isQuick = kind === "quick";
        let element = isQuick ? quickModalElement : transportationModalElement;
        if (element) return element;
        element = document.createElement("div");
        element.className = isQuick ? "crm-quick-create-modal" : "crm-transportation-modal";
        element.setAttribute("uk-modal", "stack: true; bg-close: false");
        element.innerHTML = '<div class="uk-modal-dialog uk-modal-body"><div class="crm-modal-loading"><span uk-spinner></span><span>Загрузка…</span></div></div>';
        document.body.appendChild(element);
        if (isQuick) quickModalElement = element;
        else transportationModalElement = element;
        return element;
    };

    const showLoading = (element, message = "Загрузка…") => {
        element.innerHTML = `<div class="uk-modal-dialog uk-modal-body"><div class="crm-modal-loading"><span uk-spinner></span><span>${message}</span></div></div>`;
    };

    const notify = (message, status = "warning") => {
        if (window.UIkit?.notification) UIkit.notification({message, status, pos: "top-center"});
    };

    const optionAllowedForRole = (option, role) => {
        if (!role || !option.dataset.roles) return true;
        return option.dataset.roles.split(/\s+/).includes(role);
    };

    const enhanceSmartSelect = (select) => {
        if (!select || select.dataset.smartReady === "true") return;
        select.dataset.smartReady = "true";
        const wasRequired = select.required;
        select.required = false;
        select.classList.add("crm-smart-native");

        const wrapper = document.createElement("div");
        wrapper.className = "crm-smart-select";
        const search = document.createElement("input");
        search.type = "search";
        search.className = "uk-input crm-smart-search";
        search.placeholder = select.dataset.searchPlaceholder || "Начните вводить для поиска";
        search.autocomplete = "off";
        search.setAttribute("role", "combobox");
        search.setAttribute("aria-expanded", "false");
        search.required = wasRequired;
        const dropdown = document.createElement("div");
        dropdown.className = "crm-smart-dropdown";
        dropdown.hidden = true;
        wrapper.append(search, dropdown);
        select.insertAdjacentElement("afterend", wrapper);

        const currentRole = () => {
            if (select.dataset.requiredRole) return select.dataset.requiredRole;
            const source = document.getElementById(select.dataset.roleSource || "");
            return source?.value || "";
        };
        const selectedLabel = () => select.selectedOptions[0]?.value
            ? select.selectedOptions[0].textContent.trim()
            : "";
        const hasParent = () => {
            if (!select.dataset.parentSource) return true;
            return Boolean(document.getElementById(select.dataset.parentSource)?.value);
        };
        const close = () => {
            dropdown.hidden = true;
            search.setAttribute("aria-expanded", "false");
        };
        const choose = (option) => {
            select.value = option.value;
            search.value = option.textContent.trim();
            search.dataset.selectedLabel = search.value;
            close();
            select.dispatchEvent(new Event("change", {bubbles: true}));
        };
        const render = () => {
            const query = normalize(search.value);
            const role = currentRole();
            const options = Array.from(select.options).filter((option) => (
                option.value
                && optionAllowedForRole(option, role)
                && (!query || normalize(option.textContent).includes(query))
            ));
            dropdown.innerHTML = "";
            if (!hasParent()) {
                dropdown.innerHTML = '<div class="crm-smart-empty">Сначала выберите фактического перевозчика.</div>';
            } else if (options.length) {
                options.slice(0, 30).forEach((option) => {
                    const button = document.createElement("button");
                    button.type = "button";
                    button.className = "crm-smart-option";
                    button.textContent = option.textContent.trim();
                    if (option.selected) button.classList.add("is-selected");
                    button.addEventListener("mousedown", (event) => event.preventDefault());
                    button.addEventListener("click", () => choose(option));
                    dropdown.appendChild(button);
                });
            } else {
                const empty = document.createElement("div");
                empty.className = "crm-smart-empty";
                empty.textContent = query ? "Подходящих записей не найдено." : "Список пока пуст.";
                dropdown.appendChild(empty);
            }
            if (hasParent() && query.length >= 2 && options.length === 0 && select.dataset.createUrl) {
                const create = document.createElement("button");
                create.type = "button";
                create.className = "crm-smart-create uk-button uk-button-primary uk-button-small";
                create.innerHTML = `<span uk-icon="plus"></span> ${select.dataset.createLabel || "Создать"}`;
                create.addEventListener("mousedown", (event) => event.preventDefault());
                create.addEventListener("click", () => openQuickCreate(select, search.value));
                dropdown.appendChild(create);
            }
            dropdown.hidden = false;
            search.setAttribute("aria-expanded", "true");
        };
        const syncFromSelect = () => {
            search.value = selectedLabel();
            search.dataset.selectedLabel = search.value;
            if (!select.value) search.setCustomValidity(wasRequired ? "Выберите значение из списка" : "");
            else search.setCustomValidity("");
        };

        search.addEventListener("focus", render);
        search.addEventListener("input", () => {
            if (search.value !== search.dataset.selectedLabel) {
                select.value = "";
                search.setCustomValidity(wasRequired ? "Выберите значение из списка" : "");
                select.dataset.smartTyping = "true";
                select.dispatchEvent(new Event("change", {bubbles: true}));
                delete select.dataset.smartTyping;
            }
            render();
        });
        search.addEventListener("keydown", (event) => {
            if (event.key === "Escape") close();
        });
        select.addEventListener("optionschange", () => {
            syncFromSelect();
            if (!dropdown.hidden) render();
        });
        select.addEventListener("change", () => {
            if (select.dataset.smartTyping !== "true") syncFromSelect();
        });
        const roleSource = document.getElementById(select.dataset.roleSource || "");
        roleSource?.addEventListener("change", () => {
            const selected = select.selectedOptions[0];
            if (selected?.value && !optionAllowedForRole(selected, currentRole())) {
                select.value = "";
                select.dispatchEvent(new Event("change", {bubbles: true}));
            }
            syncFromSelect();
        });
        document.addEventListener("click", (event) => {
            if (!wrapper.contains(event.target)) close();
        });
        syncFromSelect();
    };

    const addCreatedOption = (select, item) => {
        let option = Array.from(select.options).find((candidate) => String(candidate.value) === String(item.id));
        if (!option) {
            option = new Option(item.label, item.id);
            if (Array.isArray(item.roles)) option.dataset.roles = item.roles.join(" ");
            select.add(option);
        }
        select.value = String(item.id);
        select.dispatchEvent(new Event("optionschange", {bubbles: true}));
        select.dispatchEvent(new Event("change", {bubbles: true}));
    };

    const buildQuickUrl = (select) => {
        const url = new URL(select.dataset.createUrl, window.location.origin);
        const roleSource = document.getElementById(select.dataset.roleSource || "");
        const role = select.dataset.requiredRole || roleSource?.value;
        if (role) url.searchParams.set("role", role);
        if (select.dataset.parentSource) {
            const parentValue = document.getElementById(select.dataset.parentSource)?.value;
            if (parentValue) url.searchParams.set("organization", parentValue);
        }
        if (select.dataset.resourceKind) url.searchParams.set("resource_kind", select.dataset.resourceKind);
        return url;
    };

    const bindQuickDadata = (dialog) => {
        const tools = dialog.querySelector("[data-quick-dadata]");
        const button = tools?.querySelector("[data-quick-dadata-button]");
        const status = tools?.querySelector("[data-quick-dadata-status]");
        const form = dialog.querySelector("[data-quick-create-form]");
        if (!button || !status || !form) return;
        button.addEventListener("click", async () => {
            const taxId = form.querySelector('[name="tax_id"]');
            const inn = String(taxId?.value || "").replace(/\D/g, "");
            if (![10, 12].includes(inn.length)) {
                status.textContent = "Введите ИНН из 10 или 12 цифр.";
                status.className = "uk-text-danger";
                taxId?.focus();
                return;
            }
            button.disabled = true;
            status.textContent = "Получаем реквизиты…";
            status.className = "uk-text-muted";
            try {
                const csrf = form.querySelector('[name="csrfmiddlewaretoken"]')?.value || "";
                const response = await fetch(tools.dataset.url, {
                    method: "POST",
                    headers: {
                        "Accept": "application/json",
                        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                        "X-CSRFToken": csrf
                    },
                    body: new URLSearchParams({inn})
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.error || "Не удалось получить реквизиты.");
                const party = result.party;
                const values = {
                    name: party.full_name,
                    short_name: party.short_name,
                    tax_id: party.inn,
                    kpp: party.kpp,
                    ogrn: party.ogrn,
                    legal_address: party.legal_address,
                    director_name: party.director_name,
                    phone: party.phone,
                    email: party.email,
                    kind: party.organization_type === "INDIVIDUAL" ? "entrepreneur" : "legal_entity"
                };
                Object.entries(values).forEach(([name, value]) => {
                    const field = form.querySelector(`[name="${name}"]`);
                    if (field && value) field.value = value;
                });
                status.textContent = "Реквизиты заполнены. Проверьте их перед созданием.";
                status.className = "uk-text-success";
            } catch (error) {
                status.textContent = error.message || "Не удалось получить реквизиты.";
                status.className = "uk-text-danger";
            } finally {
                button.disabled = false;
            }
        });
    };

    const bindQuickForm = (dialog) => {
        const form = dialog.querySelector("[data-quick-create-form]");
        if (!form) return;
        bindQuickDadata(dialog);
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const submit = form.querySelector('[type="submit"]');
            submit.disabled = true;
            try {
                const response = await fetch(form.action, {
                    method: "POST",
                    body: new FormData(form),
                    headers: {"X-Requested-With": "XMLHttpRequest"}
                });
                const contentType = response.headers.get("content-type") || "";
                if (response.ok && contentType.includes("application/json")) {
                    const result = await response.json();
                    if (activeQuickSelect && result.item) addCreatedOption(activeQuickSelect, result.item);
                    modalInstance(quickModalElement)?.hide();
                    notify("Запись создана и выбрана в заявке.", "success");
                    return;
                }
                const html = await response.text();
                quickModalElement.innerHTML = html;
                const nextDialog = quickModalElement.querySelector(".uk-modal-dialog");
                bindQuickForm(nextDialog);
                if (window.UIkit?.update) UIkit.update(quickModalElement);
            } catch (_error) {
                notify("Не удалось создать запись. Проверьте соединение и повторите.", "danger");
            } finally {
                if (submit.isConnected) submit.disabled = false;
            }
        });
    };

    async function openQuickCreate(select, query) {
        const modal = ensureModal("quick");
        activeQuickSelect = select;
        activeQuickQuery = query || "";
        showLoading(modal, "Открываем карточку…");
        modalInstance(modal)?.show();
        try {
            const response = await fetch(buildQuickUrl(select), {headers: {"X-Requested-With": "XMLHttpRequest"}});
            if (!response.ok) throw new Error();
            modal.innerHTML = await response.text();
            const dialog = modal.querySelector(".uk-modal-dialog");
            if (activeQuickQuery) {
                const digits = activeQuickQuery.replace(/\D/g, "");
                const field = digits.length >= 8
                    ? dialog.querySelector('[name="tax_id"]')
                    : dialog.querySelector('[name="name"], [name="last_name"], [name="registration_number"]');
                if (field && !field.value) field.value = activeQuickQuery;
            }
            bindQuickForm(dialog);
            if (window.UIkit?.update) UIkit.update(modal);
        } catch (_error) {
            modal.innerHTML = '<div class="uk-modal-dialog uk-modal-body"><button class="uk-modal-close-default" type="button" uk-close></button><div class="uk-alert-danger" uk-alert>Не удалось открыть форму создания.</div></div>';
        }
    }

    const replaceOptions = (select, items, selected) => {
        if (!select) return;
        select.innerHTML = '<option value="">---------</option>';
        items.forEach((item) => select.add(new Option(item.label, item.id)));
        select.value = String(selected || "");
        select.dispatchEvent(new Event("optionschange", {bubbles: true}));
    };

    const initializeModalTransportationForm = (form, dialog) => {
        if (!form || form.dataset.modalWorkspaceReady === "true") return;
        form.dataset.modalWorkspaceReady = "true";
        const executor = form.querySelector("#id_executor");
        const role = form.querySelector("#id_executor_role");
        const carrier = form.querySelector("#id_actual_carrier");
        const resources = {
            drivers: form.querySelector("#id_driver"),
            vehicles: form.querySelector("#id_vehicle"),
            trailers: form.querySelector("#id_trailer")
        };
        const loadResources = async () => {
            const selected = Object.fromEntries(Object.entries(resources).map(([key, select]) => [key, select?.value]));
            if (!carrier?.value) {
                Object.values(resources).forEach((select) => replaceOptions(select, [], ""));
                return;
            }
            try {
                const url = new URL(form.dataset.resourceUrl, window.location.origin);
                url.searchParams.set("organization", carrier.value);
                const response = await fetch(url);
                if (!response.ok) return;
                const data = await response.json();
                replaceOptions(resources.drivers, data.drivers, selected.drivers);
                replaceOptions(resources.vehicles, data.vehicles, selected.vehicles);
                replaceOptions(resources.trailers, data.trailers, selected.trailers);
            } catch (_error) {
                notify("Не удалось обновить водителей и транспорт.", "danger");
            }
        };
        const syncDirectCarrier = () => {
            if (role?.value === "carrier" && executor?.value) {
                carrier.value = executor.value;
                carrier.dispatchEvent(new Event("optionschange", {bubbles: true}));
                loadResources();
            }
        };
        executor?.addEventListener("change", syncDirectCarrier);
        role?.addEventListener("change", syncDirectCarrier);
        carrier?.addEventListener("change", loadResources);

        const revenue = form.querySelector("#id_customer_amount");
        const cost = form.querySelector("#id_executor_amount");
        const owner = form.querySelector("#id_owner_company");
        const customerVat = form.querySelector("#id_customer_vat_rate");
        const executorVat = form.querySelector("#id_executor_vat_rate");
        const currency = form.querySelector("#id_currency");
        const vatRates = JSON.parse(dialog.querySelector("#vat-rate-map")?.textContent || "{}");
        const ownerRates = JSON.parse(dialog.querySelector("#owner-tax-rate-map")?.textContent || "{}");
        const money = (value) => new Intl.NumberFormat("ru-RU", {minimumFractionDigits: 2, maximumFractionDigits: 2}).format(value) + " " + ((currency?.value || "RUB") === "RUB" ? "₽" : (currency?.value || "RUB"));
        const round = (value) => Math.round((value + Number.EPSILON) * 100) / 100;
        const vat = (amount, field) => {
            const rate = Number(vatRates[field?.value] || 0);
            return rate ? round(amount * rate / (100 + rate)) : 0;
        };
        const recalculate = () => {
            const income = Number(String(revenue?.value || 0).replace(",", ".")) || 0;
            const expense = Number(String(cost?.value || 0).replace(",", ".")) || 0;
            const margin = income - expense;
            const outputVat = vat(income, customerVat);
            const inputVat = vat(expense, executorVat);
            const profit = round((income - outputVat) - (expense - inputVat));
            const rate = Number(ownerRates[owner?.value] ?? 25);
            const profitTax = profit > 0 ? round(profit * rate / 100) : 0;
            const values = {
                "preview-revenue": money(income),
                "preview-cost": money(expense),
                "preview-margin": money(margin),
                "preview-percent": (income ? margin / income * 100 : 0).toLocaleString("ru-RU", {minimumFractionDigits: 2, maximumFractionDigits: 2}) + "%",
                "preview-vat-payable": money(Math.max(round(outputVat - inputVat), 0)),
                "preview-profit": money(profit),
                "preview-profit-tax": money(profitTax),
                "preview-net-profit": money(round(profit - profitTax))
            };
            Object.entries(values).forEach(([id, value]) => {
                const target = form.querySelector(`#${id}`);
                if (target) target.textContent = value;
            });
            const rateLabel = form.querySelector("#preview-profit-tax-rate");
            if (rateLabel) rateLabel.textContent = `Ставка нашей компании: ${rate.toLocaleString("ru-RU")}%`;
        };
        [revenue, cost, owner, customerVat, executorVat, currency].forEach((field) => {
            field?.addEventListener("input", recalculate);
            field?.addEventListener("change", recalculate);
        });
        recalculate();
    };

    const initializeTransportationContent = (container, isModal = false) => {
        container.querySelectorAll(SMART_SELECTOR).forEach(enhanceSmartSelect);
        const form = container.querySelector("#transportation-form");
        if (isModal) initializeModalTransportationForm(form, container);
    };

    const renderTransportationModal = (html, sourceUrl) => {
        const documentCopy = new DOMParser().parseFromString(html, "text/html");
        const heading = documentCopy.querySelector(".onec-document-heading");
        const form = documentCopy.querySelector("#transportation-form");
        if (!heading || !form) throw new Error("Форма не найдена");
        const dialog = document.createElement("div");
        dialog.className = "uk-modal-dialog uk-modal-body crm-transportation-dialog";
        dialog.innerHTML = '<button class="uk-modal-close-default" type="button" uk-close aria-label="Закрыть"></button>';
        dialog.append(heading, form);
        ["vat-rate-map", "owner-tax-rate-map"].forEach((id) => {
            const script = documentCopy.getElementById(id);
            if (script) dialog.appendChild(script);
        });
        form.action = sourceUrl;
        form.dataset.modalForm = "true";
        dialog.querySelectorAll("a").forEach((link) => {
            try {
                if (new URL(link.href).pathname === "/transportations/") {
                    link.addEventListener("click", (event) => {
                        event.preventDefault();
                        modalInstance(transportationModalElement)?.hide();
                    });
                }
            } catch (_error) { /* Ссылка остаётся обычной. */ }
        });
        transportationModalElement.innerHTML = "";
        transportationModalElement.appendChild(dialog);
        initializeTransportationContent(dialog, true);
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const submitter = event.submitter;
            const data = new FormData(form);
            if (submitter?.name) data.set(submitter.name, submitter.value);
            form.querySelectorAll('button[type="submit"]').forEach((button) => { button.disabled = true; });
            try {
                const response = await fetch(sourceUrl, {
                    method: "POST",
                    body: data,
                    headers: {"X-Requested-With": "XMLHttpRequest"}
                });
                if (response.redirected) {
                    window.location.assign(response.url);
                    return;
                }
                renderTransportationModal(await response.text(), sourceUrl);
            } catch (_error) {
                notify("Не удалось сохранить заявку.", "danger");
                form.querySelectorAll('button[type="submit"]').forEach((button) => { button.disabled = false; });
            }
        });
        if (window.UIkit?.update) UIkit.update(transportationModalElement);
    };

    const openTransportationModal = async (url) => {
        const modal = ensureModal("transportation");
        showLoading(modal, "Открываем новую заявку…");
        modalInstance(modal)?.show();
        try {
            const response = await fetch(url, {headers: {"X-Requested-With": "XMLHttpRequest"}});
            if (!response.ok) throw new Error();
            renderTransportationModal(await response.text(), response.url || url);
        } catch (_error) {
            modal.innerHTML = '<div class="uk-modal-dialog uk-modal-body"><button class="uk-modal-close-default" type="button" uk-close></button><div class="uk-alert-danger" uk-alert>Не удалось открыть форму заявки.</div></div>';
        }
    };

    document.addEventListener("click", (event) => {
        const trigger = event.target.closest("[data-transportation-modal]");
        if (!trigger) return;
        event.preventDefault();
        openTransportationModal(trigger.href);
    });

    document.addEventListener("DOMContentLoaded", () => {
        initializeTransportationContent(document, false);
    });
})();
