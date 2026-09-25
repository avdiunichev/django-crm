(() => {
    const SMART_SELECTOR = "select[data-smart-select]";
    const normalize = (value) => String(value || "").toLocaleLowerCase("ru-RU").trim();
    let transportationModalElement;
    let quickModalElement;
    let vehicleModalElement;
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
        const actions = document.createElement("div");
        actions.className = "crm-smart-actions";
        const edit = document.createElement("button");
        edit.type = "button";
        edit.className = "uk-button uk-button-default crm-smart-edit";
        edit.textContent = "Открыть";
        edit.title = "Открыть или отредактировать выбранную карточку";
        edit.disabled = !select.value;
        const create = document.createElement("button");
        create.type = "button";
        create.className = "uk-button uk-button-default crm-smart-add";
        create.textContent = "Создать";
        create.title = select.dataset.createLabel || "Создать новую карточку";
        actions.append(edit, create);
        wrapper.append(search, actions, dropdown);
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
            if (search.dataset.openValue !== undefined) {
                select.value = search.dataset.openValue;
                search.value = search.dataset.openLabel || "";
                delete search.dataset.openValue;
                delete search.dataset.openLabel;
                syncDisabled();
            }
        };
        const syncDisabled = () => {
            search.disabled = select.disabled;
            edit.disabled = select.disabled || !select.value;
            create.disabled = select.disabled || !select.dataset.createUrl || !hasParent();
            wrapper.classList.toggle("is-disabled", select.disabled);
            if (select.disabled) close();
        };
        const choose = (option) => {
            select.value = option.value;
            search.value = option.textContent.trim();
            search.dataset.selectedLabel = search.value;
            delete search.dataset.openValue;
            delete search.dataset.openLabel;
            close();
            select.dispatchEvent(new Event("change", {bubbles: true}));
        };
        let searchTimer = null;
        let searchController = null;
        let searchSequence = 0;
        let globalScope = false;
        const renderServerItems = (items, hasMore, query) => {
            dropdown.innerHTML = "";
            items.forEach((item) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "crm-smart-option";
                const title = document.createElement("strong");
                title.textContent = item.label;
                button.append(title);
                if (item.meta) {
                    const meta = document.createElement("small");
                    meta.textContent = item.meta;
                    button.append(meta);
                }
                button.addEventListener("mousedown", (event) => event.preventDefault());
                button.addEventListener("click", async () => {
                    let option = Array.from(select.options).find((candidate) => String(candidate.value) === String(item.id));
                    if (!option) { option = new Option(item.label, item.id); select.add(option); }
                    if (Array.isArray(item.roles)) option.dataset.roles = item.roles.join(" ");
                    if (item.tractor_id) option.dataset.tractorId = item.tractor_id;
                    if (item.trailer_id) option.dataset.trailerId = item.trailer_id;
                    choose(option);
                });
                dropdown.appendChild(button);
            });
            if (!items.length) {
                const empty = document.createElement("div");
                empty.className = "crm-smart-empty";
                empty.textContent = query.length < 2 && query.length > 0 ? "Введите минимум 2 символа" : "Ничего не найдено";
                dropdown.appendChild(empty);
            }
            if (hasMore) {
                const more = document.createElement("div");
                more.className = "crm-smart-empty";
                more.textContent = "Найдено больше 20 записей. Уточните запрос.";
                dropdown.appendChild(more);
            }
            if (select.dataset.searchResource !== "organization" && select.dataset.parentSource) {
                const scopeButton = document.createElement("button");
                scopeButton.type = "button";
                scopeButton.className = "crm-smart-create uk-button uk-button-default uk-button-small";
                scopeButton.textContent = globalScope ? "Популярные у перевозчика" : "Весь справочник";
                scopeButton.addEventListener("mousedown", (event) => event.preventDefault());
                scopeButton.addEventListener("click", () => { globalScope = !globalScope; runServerSearch(); });
                dropdown.appendChild(scopeButton);
            }
            if (query.length >= 2 && !items.length && select.dataset.createUrl) {
                const createButton = document.createElement("button");
                createButton.type = "button";
                createButton.className = "crm-smart-create uk-button uk-button-primary uk-button-small";
                createButton.textContent = select.dataset.createLabel || "Создать карточку";
                createButton.addEventListener("mousedown", (event) => event.preventDefault());
                createButton.addEventListener("click", () => openQuickCreate(select, search.value));
                dropdown.appendChild(createButton);
            }
            dropdown.hidden = false;
            search.setAttribute("aria-expanded", "true");
        };
        const runServerSearch = async () => {
            if (!select.dataset.searchUrl) return render();
            const query = search.value.trim();
            if (query.length === 1) return renderServerItems([], false, query);
            searchController?.abort();
            searchController = new AbortController();
            const sequence = ++searchSequence;
            dropdown.innerHTML = '<div class="crm-smart-empty">Поиск…</div>';
            dropdown.hidden = false;
            try {
                const url = new URL(select.dataset.searchUrl, document.baseURI);
                url.searchParams.set("resource", select.dataset.searchResource);
                url.searchParams.set("q", query);
                const role = currentRole();
                if (role) url.searchParams.set("role", role);
                const parent = document.getElementById(select.dataset.parentSource || "")?.value;
                if (parent) url.searchParams.set("organization", parent);
                if (select.dataset.resourceKind) url.searchParams.set("kind", select.dataset.resourceKind);
                if (globalScope) url.searchParams.set("scope", "all");
                const response = await fetch(url, {signal: searchController.signal, headers: {"Accept": "application/json"}});
                if (!response.ok) throw new Error();
                const data = await response.json();
                if (sequence !== searchSequence) return;
                renderServerItems(data.items || [], Boolean(data.has_more), query);
            } catch (error) {
                if (error.name === "AbortError") return;
                dropdown.innerHTML = '<div class="crm-smart-empty uk-text-danger">Ошибка поиска. Повторите запрос.</div>';
            }
        };
        const scheduleServerSearch = (immediate = false) => {
            window.clearTimeout(searchTimer);
            searchTimer = window.setTimeout(runServerSearch, immediate ? 0 : 320);
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
                empty.textContent = query
                    ? "Контрагент с таким названием или ИНН не найден. Можно создать новую карточку."
                    : "Список пока пуст.";
                dropdown.appendChild(empty);
            }
            if (hasParent() && query.length >= 2 && options.length === 0 && select.dataset.createUrl) {
                const create = document.createElement("button");
                create.type = "button";
                create.className = "crm-smart-create uk-button uk-button-primary uk-button-small";
                create.innerHTML = `<span uk-icon="plus"></span> ${select.dataset.createLabel || "Создать карточку"}`;
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

        search.addEventListener("focus", () => {
            if (search.dataset.openValue === undefined) {
                // The selected record remains assigned until another option is
                // chosen. Only the visible query is cleared to show the catalog.
                search.dataset.openValue = select.value;
                search.dataset.openLabel = search.value;
                search.value = "";
            }
            select.dataset.searchUrl ? scheduleServerSearch(true) : render();
        });
        search.addEventListener("input", () => {
            if (search.value !== search.dataset.selectedLabel) {
                select.value = "";
                search.setCustomValidity(wasRequired ? "Выберите значение из списка" : "");
                select.dataset.smartTyping = "true";
                select.dispatchEvent(new Event("change", {bubbles: true}));
                delete select.dataset.smartTyping;
            }
            if (select.dataset.searchUrl) scheduleServerSearch();
            else render();
        });
        search.addEventListener("keydown", (event) => {
            if (event.key === "Escape") close();
        });
        select.addEventListener("optionschange", () => {
            syncFromSelect();
            if (!dropdown.hidden) select.dataset.searchUrl ? scheduleServerSearch(true) : render();
        });
        select.addEventListener("change", () => {
            if (select.dataset.smartTyping !== "true") syncFromSelect();
            syncDisabled();
        });
        select.addEventListener("disabledchange", syncDisabled);
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
            if (!wrapper.contains(event.target) && !dropdown.contains(event.target)) close();
        });
        create.addEventListener("click", () => openQuickCreate(select, search.value));
        edit.addEventListener("click", () => openSelectedEntity(select));
        syncFromSelect();
        syncDisabled();
    };

    const addCreatedOption = (select, item) => {
        let option = Array.from(select.options).find((candidate) => String(candidate.value) === String(item.id));
        if (!option) {
            option = new Option(item.label, item.id);
            select.add(option);
        }
        option.textContent = item.label;
        if (Array.isArray(item.roles)) option.dataset.roles = item.roles.join(" ");
        select.value = String(item.id);
        select.dispatchEvent(new Event("optionschange", {bubbles: true}));
        select.dispatchEvent(new Event("change", {bubbles: true}));
    };

    const emitEntitySaved = (type, item, action) => {
        document.dispatchEvent(new CustomEvent("crm:entity-saved", {
            detail: {type, id: item?.id, action, item}
        }));
    };

    const syncEntityOptions = (type, item, sourceSelect) => {
        document.querySelectorAll(`${SMART_SELECTOR}[data-entity-type="${type}"]`).forEach((select) => {
            let option = Array.from(select.options).find((candidate) => String(candidate.value) === String(item.id));
            const carrier = document.getElementById(select.dataset.parentSource || "")?.value;
            const carrierAllowed = true;
            const kindAllowed = !select.dataset.resourceKind || (
                select.dataset.resourceKind === "trailer"
                    ? ["trailer", "semitrailer"].includes(item.kind)
                    : !["trailer", "semitrailer"].includes(item.kind)
            );
            if (!option && carrierAllowed && kindAllowed) {
                option = new Option(item.label, item.id);
                select.add(option);
            }
            if (option) {
                option.textContent = item.label;
                if (Array.isArray(item.roles)) option.dataset.roles = item.roles.join(" ");
                select.dispatchEvent(new Event("optionschange", {bubbles: true}));
            }
        });
        if (sourceSelect) addCreatedOption(sourceSelect, item);
    };

    const buildQuickUrl = (select) => {
        const url = new URL(select.dataset.createUrl, document.baseURI);
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

    const buildEditUrl = (select) => {
        if (!select.value || !select.dataset.editUrlTemplate) return null;
        return new URL(
            select.dataset.editUrlTemplate.replace(/\/0\//, `/${select.value}/`),
            document.baseURI
        );
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
                    if (activeQuickSelect && result.item) {
                        syncEntityOptions(activeQuickSelect.dataset.entityType, result.item, activeQuickSelect);
                        emitEntitySaved(activeQuickSelect.dataset.entityType, result.item, "created");
                    }
                    modalInstance(quickModalElement)?.hide();
                    notify("Контрагент создан и выбран в документе.", "success");
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

    const setOrganizationField = (dialog, id, value) => {
        const field = dialog.querySelector(`#${id}`);
        if (!field || value === undefined || value === null || value === "") return;
        let normalized = String(value);
        if (id === "id_director_position") {
            normalized = normalized.trim().replace(/\s+/g, " ").toLowerCase();
            normalized = normalized ? `${normalized[0].toUpperCase()}${normalized.slice(1)}` : "";
        }
        if (id === "id_registration_date") {
            const isoDate = /^(\d{4})-(\d{2})-(\d{2})$/.exec(normalized);
            if (isoDate) normalized = `${isoDate[3]}.${isoDate[2]}.${isoDate[1]}`;
        }
        if (id === "id_legal_address") normalized = normalized.toUpperCase();
        field.value = normalized;
        field.dispatchEvent(new Event("change", {bubbles: true}));
    };

    const bindFullOrganizationDadata = (dialog, autoFill = false) => {
        const tools = dialog.querySelector("[data-dadata-autofill]");
        const button = tools?.querySelector("[data-dadata-button]");
        const status = tools?.querySelector("[data-dadata-status]");
        const form = dialog.querySelector("form.organization-workspace");
        const taxId = form?.querySelector("#id_tax_id");
        if (!tools || !button || !form || !taxId) return;
        const fill = async () => {
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
                    headers: {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "X-CSRFToken": csrf},
                    body: new URLSearchParams({inn})
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.error || "Не удалось получить реквизиты.");
                const party = result.party;
                const values = {
                    id_name: party.full_name,
                    id_short_name: party.short_name,
                    id_tax_id: party.inn,
                    id_kpp: party.kpp,
                    id_ogrn: party.ogrn,
                    id_registration_date: party.registration_date,
                    id_legal_address: party.legal_address,
                    id_legal_address_meta: JSON.stringify(party.address_data || {}),
                    id_director_position: party.director_post,
                    id_director_name: party.director_name,
                    id_verification_status: party.is_invalid || (party.status && party.status !== "ACTIVE") ? "warning" : "verified",
                    id_fns_status: ({ACTIVE: "active", LIQUIDATED: "liquidated", LIQUIDATING: "liquidating", REORGANIZING: "reorganizing", BANKRUPT: "bankrupt"})[party.status] || "unknown"
                };
                Object.entries(values).forEach(([id, value]) => setOrganizationField(dialog, id, value));
                if (party.organization_type === "INDIVIDUAL") setOrganizationField(dialog, "id_kind", "entrepreneur");
                const mirror = form.querySelector("[data-tax-id-mirror]");
                if (mirror) mirror.value = taxId.value;
                const fnsStatus = dialog.querySelector("[data-fns-status]");
                const isInactive = party.is_invalid || (party.status && party.status !== "ACTIVE");
                if (fnsStatus) {
                    fnsStatus.textContent = `ФНС: ${party.status_label || "Не проверен"}`;
                    fnsStatus.classList.toggle("uk-text-success", party.status === "ACTIVE");
                    fnsStatus.classList.toggle("uk-text-danger", Boolean(isInactive));
                }
                const message = isInactive
                    ? "Проверка выполнена. Перед сохранением проверьте статус контрагента."
                    : "Проверка выполнена: реквизиты заполнены.";
                if (status) status.textContent = message;
                notify(message, isInactive ? "danger" : "success");
            } catch (error) {
                const message = error.message || "Не удалось получить реквизиты.";
                if (status) status.textContent = message;
                notify(message, "danger");
            } finally { button.disabled = false; }
        };
        button.addEventListener("click", fill);
        if (autoFill) fill();
    };

    const bindFullOrganizationForm = (dialog, sourceUrl) => {
        const form = dialog.querySelector("form.organization-workspace");
        if (!form) return;
        // Named form controls (including the two action buttons) shadow form.action.
        const submitUrl = new URL(sourceUrl, document.baseURI).href;
        form.setAttribute("action", submitUrl);
        let saving = false;
        form.querySelectorAll('a[href$="/organizations/"]').forEach((link) => {
            link.addEventListener("click", (event) => { event.preventDefault(); modalInstance(quickModalElement)?.hide(); });
        });
        const taxId = form.querySelector("#id_tax_id");
        form.querySelectorAll("[data-tax-id-mirror]").forEach((mirror) => {
            mirror.addEventListener("input", () => { taxId.value = mirror.value; taxId.dispatchEvent(new Event("input", {bubbles: true})); });
            taxId?.addEventListener("input", () => { mirror.value = taxId.value; });
        });
        const ownCompany = form.querySelector("#id_is_own_company");
        const ownCompanyTax = form.querySelector("[data-own-company-tax]");
        const syncOwnCompanyTax = () => ownCompanyTax?.classList.toggle("uk-hidden", !ownCompany?.checked);
        ownCompany?.addEventListener("change", syncOwnCompanyTax);
        syncOwnCompanyTax();
        dialog.addEventListener("click", (event) => {
            const add = event.target.closest("[data-add-form]");
            if (add) {
                const prefix = add.dataset.addForm;
                const total = form.querySelector(`#id_${prefix}-TOTAL_FORMS`);
                const template = form.querySelector(`#${prefix}-empty-form`);
                const target = form.querySelector(`[data-formset="${prefix}"]`);
                if (total && template && target) { target.insertAdjacentHTML("beforeend", template.innerHTML.replaceAll("__prefix__", total.value)); total.value = Number(total.value) + 1; }
                return;
            }
            const remove = event.target.closest("[data-remove-bank-account], [data-remove-contact], [data-remove-requisite-change]");
            if (!remove || remove.getAttribute("aria-disabled") === "true") return;
            event.preventDefault();
            const card = remove.closest("[data-bank-account-card], [data-contact-card], [data-requisite-change-card]");
            const deleted = card?.querySelector('[name$="-DELETE"]');
            if (deleted) { deleted.checked = true; card.classList.add("is-deleted"); }
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
        bindFullOrganizationDadata(dialog);
        const submitOrganization = async (submit) => {
            if (saving) return;
            saving = true;
            if (submit) submit.disabled = true;
            try {
                const formData = new FormData(form);
                if (submit?.name && !formData.has(submit.name)) {
                    formData.append(submit.name, submit.value);
                }
                const response = await fetch(submitUrl, {
                    method: "POST",
                    body: formData,
                    credentials: "same-origin",
                    headers: {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/html"}
                });
                const contentType = response.headers.get("content-type") || "";
                if (response.ok && contentType.includes("application/json")) {
                    const result = await response.json();
                    if (activeQuickSelect && result.item) {
                        const action = sourceUrl.includes("/edit/") ? "updated" : "created";
                        syncEntityOptions("organization", result.item, activeQuickSelect);
                        emitEntitySaved("organization", result.item, action);
                    }
                    modalInstance(quickModalElement)?.hide();
                    notify("Карточка контрагента сохранена и данные обновлены.", "success");
                    return;
                }
                if (!response.ok) {
                    throw new Error(`Не удалось сохранить контрагента: ошибка сервера ${response.status}. Введённые данные сохранены в форме.`);
                }
                renderFullOrganizationForm(await response.text(), sourceUrl);
                notify("Проверьте отмеченные поля карточки контрагента.", "danger");
            } catch (error) {
                notify(error.message || "Не удалось сохранить контрагента. Проверьте соединение.", "danger");
                if (submit?.isConnected) submit.disabled = false;
            } finally {
                saving = false;
            }
        };
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            event.stopImmediatePropagation();
            submitOrganization(event.submitter || form.querySelector('[type="submit"]'));
        }, {capture: true});
        form.querySelectorAll('button[type="submit"]').forEach((button) => {
            button.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                submitOrganization(button);
            });
        });
    };

    const renderFullOrganizationForm = (html, sourceUrl) => {
        const page = new DOMParser().parseFromString(html, "text/html");
        const form = page.querySelector("form.organization-workspace");
        if (!form) throw new Error("Форма контрагента не найдена");
        const dialog = document.createElement("div");
        dialog.className = "uk-modal-dialog uk-modal-body crm-full-organization-dialog";
        dialog.append(form);
        quickModalElement.replaceChildren(dialog);
        bindFullOrganizationForm(dialog, sourceUrl);
        window.CRMUniversalSelects?.enhanceWithin?.(dialog);
        window.CRMDateInputs?.enhanceWithin?.(dialog);
        window.CRMMoneyInputs?.enhanceWithin?.(dialog);
        window.UIkit?.update?.(quickModalElement);
    };

    async function openFullOrganization(select, query, requestedUrl = null) {
        const modal = ensureModal("quick");
        activeQuickSelect = select;
        activeQuickQuery = query || "";
        showLoading(modal, "Открываем карточку контрагента…");
        modal.classList.add("crm-full-organization-modal");
        modalInstance(modal)?.show();
        try {
            const response = await fetch(requestedUrl || buildQuickUrl(select), {headers: {"X-Requested-With": "XMLHttpRequest"}});
            if (!response.ok) throw new Error();
            renderFullOrganizationForm(await response.text(), response.url || select.dataset.createUrl);
            const form = modal.querySelector("form.organization-workspace");
            const inn = requestedUrl ? "" : activeQuickQuery.replace(/\D/g, "");
            const field = form?.querySelector("#id_tax_id");
            if (field && /^[0-9]{10}$|^[0-9]{12}$/.test(inn)) {
                field.value = inn;
                form.querySelector("[data-tax-id-mirror]").value = inn;
                modal.querySelector("[data-dadata-button]")?.click();
            }
        } catch (_error) {
            modal.innerHTML = '<div class="uk-modal-dialog uk-modal-body"><button class="uk-modal-close-default" type="button" uk-close></button><div class="uk-alert-danger" uk-alert>Не удалось открыть карточку контрагента.</div></div>';
        }
    }

    async function openQuickCreate(select, query) {
        if (select.dataset.fullOrganizationCreate === "true") return openFullOrganization(select, query);
        const sourceUrl = buildQuickUrl(select).toString();
        if (select.dataset.entityType === "driver" && window.CRMDriverModal?.open) {
            return window.CRMDriverModal.open(sourceUrl, {
                action: "created",
                onSaved: (item) => syncEntityOptions("driver", item, select)
            });
        }
        if (select.dataset.entityType === "vehicle") {
            return openVehicleCard(select, sourceUrl, "created");
        }
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
            if (activeQuickQuery.replace(/\D/g, "").match(/^\d{10}$|^\d{12}$/)) {
                dialog.querySelector("[data-quick-dadata-button]")?.click();
            }
            if (window.UIkit?.update) UIkit.update(modal);
        } catch (_error) {
            modal.innerHTML = '<div class="uk-modal-dialog uk-modal-body"><button class="uk-modal-close-default" type="button" uk-close></button><div class="uk-alert-danger" uk-alert>Не удалось открыть форму создания.</div></div>';
        }
    }

    const openSelectedEntity = (select) => {
        const url = buildEditUrl(select);
        if (!url) return;
        if (select.dataset.entityType === "organization") {
            openFullOrganization(select, "", url.toString());
        } else if (select.dataset.entityType === "driver" && window.CRMDriverModal?.open) {
            window.CRMDriverModal.open(url.toString(), {
                action: "updated",
                onSaved: (item) => syncEntityOptions("driver", item, select)
            });
        } else if (select.dataset.entityType === "vehicle") {
            openVehicleCard(select, url.toString(), "updated");
        }
    };

    const ensureVehicleModal = () => {
        if (vehicleModalElement) return vehicleModalElement;
        vehicleModalElement = document.createElement("div");
        vehicleModalElement.className = "crm-vehicle-modal";
        vehicleModalElement.setAttribute("uk-modal", "stack: true; bg-close: false; esc-close: false");
        document.body.appendChild(vehicleModalElement);
        return vehicleModalElement;
    };

    const renderVehicleCard = (select, html, sourceUrl, entityAction) => {
        const page = new DOMParser().parseFromString(html, "text/html");
        const form = page.querySelector("[data-vehicle-form]");
        if (!form) throw new Error("Форма транспорта не найдена");
        const dialog = document.createElement("div");
        dialog.className = "uk-modal-dialog uk-modal-body crm-driver-dialog vehicle-form-page";
        dialog.append(form);
        form.action = sourceUrl;
        form.querySelectorAll(".back-link, .form-actions a[href], .vehicle-command-panel a[href]").forEach((link) => {
            if (link.matches(".driver-delete-button, a[href*='/delete/']")) return;
            link.addEventListener("click", (event) => {
                event.preventDefault();
                modalInstance(vehicleModalElement)?.hide();
            });
        });
        vehicleModalElement.replaceChildren(dialog);
        window.CRMVehicleForm?.enhanceWithin?.(dialog);
        window.CRMVehicleCarriers?.enhanceWithin?.(dialog);
        window.CRMUniversalSelects?.enhanceWithin?.(dialog);
        window.UIkit?.update?.(vehicleModalElement);
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const submit = event.submitter || form.querySelector('[type="submit"]');
            const data = new FormData(form);
            if (submit?.name) data.set(submit.name, submit.value);
            form.querySelectorAll('button[type="submit"]').forEach((button) => { button.disabled = true; });
            try {
                const response = await fetch(form.action, {
                    method: "POST",
                    body: data,
                    headers: {"Accept": "application/json, text/html", "X-Requested-With": "XMLHttpRequest"}
                });
                const contentType = response.headers.get("content-type") || "";
                if (response.ok && contentType.includes("application/json")) {
                    const result = await response.json();
                    syncEntityOptions("vehicle", result.item, select);
                    emitEntitySaved("vehicle", result.item, entityAction);
                    notify(result.message || "Карточка транспорта сохранена.", "success");
                    if (result.action === "save") {
                        await openVehicleCard(select, result.url, "updated");
                    } else {
                        modalInstance(vehicleModalElement)?.hide();
                    }
                    return;
                }
                renderVehicleCard(select, await response.text(), sourceUrl, entityAction);
                notify("Проверьте заполнение карточки транспорта.", "danger");
            } catch (_error) {
                notify("Не удалось сохранить транспорт. Проверьте соединение.", "danger");
                form.querySelectorAll('button[type="submit"]').forEach((button) => { button.disabled = false; });
            }
        });
    };

    async function openVehicleCard(select, sourceUrl, entityAction) {
        const modal = ensureVehicleModal();
        showLoading(modal, "Открываем карточку транспорта…");
        modalInstance(modal)?.show();
        try {
            const response = await fetch(sourceUrl, {headers: {"X-Requested-With": "XMLHttpRequest"}});
            if (!response.ok) throw new Error();
            renderVehicleCard(select, await response.text(), response.url || sourceUrl, entityAction);
        } catch (_error) {
            modal.innerHTML = '<div class="uk-modal-dialog uk-modal-body"><div class="uk-alert-danger" uk-alert>Не удалось открыть карточку транспорта.</div></div>';
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
            // SmartSelect includes the carrier in each server search.  Do not
            // preload the carrier's entire fleet into the page.
            Object.values(resources).forEach((select) => select?.dispatchEvent(new Event("optionschange", {bubbles: true})));
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
        carrier?.addEventListener("optionschange", loadResources);
        syncDirectCarrier();
        loadResources();

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
