(() => {
    "use strict";

    const TABLE_SELECTOR = "table:not([data-sortable=\"false\"])";
    const DATE_PATTERN = /^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})(?:\s+(\d{1,2}):(\d{2}))?/;

    const cleanText = (value) => (value || "")
        .replace(/\u00a0/g, " ")
        .replace(/[\u200b\u200e\u200f]/g, "")
        .replace(/\s+/g, " ")
        .trim();

    const parseDate = (text) => {
        const match = cleanText(text).match(DATE_PATTERN);
        if (!match) return null;
        let year = Number(match[3]);
        if (year < 100) year += year < 70 ? 2000 : 1900;
        const date = new Date(
            year,
            Number(match[2]) - 1,
            Number(match[1]),
            Number(match[4] || 0),
            Number(match[5] || 0),
        );
        return Number.isNaN(date.getTime()) ? null : date.getTime();
    };

    const parseNumber = (text) => {
        let normalized = cleanText(text)
            .replace(/[−–—]/g, "-")
            .replace(/[₽%]/g, "")
            .replace(/\b(?:RUB|USD|EUR|KZT|BYN|CNY|руб(?:лей|ль)?\.?)\b/gi, "")
            .replace(/\s/g, "");
        if (!normalized || !/^[+-]?[\d.,]+$/.test(normalized)) {
            return null;
        }
        const sign = /^[+-]/.test(normalized) ? normalized[0] : "";
        let body = sign ? normalized.slice(1) : normalized;
        if (body.includes(",") && body.includes(".")) {
            // The last separator is the decimal mark; the other one is a
            // thousands separator (e.g. 1,234.56 or 1.234,56).
            if (body.lastIndexOf(",") > body.lastIndexOf(".")) {
                body = body.replace(/\./g, "").replace(",", ".");
            } else {
                body = body.replace(/,/g, "");
            }
        } else if (body.includes(",")) {
            const groups = body.split(",");
            // Django's intcomma filter produces 1,234,567. Decimal values
            // with a comma (for example 12,50) keep the comma as a dot.
            if (groups.length > 1 && groups.slice(1).every((group) => group.length === 3)) {
                body = groups.join("");
            } else {
                body = body.replace(",", ".");
            }
        }
        const canonical = `${sign}${body}`;
        if (!/^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$/.test(canonical)) return null;
        const number = Number(canonical);
        return Number.isFinite(number) ? number : null;
    };

    const cellValue = (cell) => {
        if (!cell) return {type: "empty", value: ""};
        const explicit = cell.dataset.sortValue
            ?? cell.querySelector("[data-sort-value]")?.dataset.sortValue;
        // Financial cells often contain a primary amount in <strong> and a
        // secondary percentage/status in <small>. Sort by the amount shown
        // first instead of concatenating both values into one text string.
        const source = explicit ?? cell.querySelector("strong")?.textContent ?? cell.textContent;
        const text = cleanText(source);
        if (!text) return {type: "empty", value: ""};
        if (cell.dataset.sortType === "date") {
            return {type: "number", value: parseDate(text) ?? 0};
        }
        if (cell.dataset.sortType === "number") {
            return {type: "number", value: parseNumber(text) ?? 0};
        }
        const date = parseDate(text);
        if (date !== null) return {type: "number", value: date};
        const number = parseNumber(text);
        if (number !== null) return {type: "number", value: number};
        return {type: "text", value: text.toLocaleLowerCase("ru-RU")};
    };

    const compare = (left, right) => {
        if (left.type === "empty" && right.type !== "empty") return 1;
        if (right.type === "empty" && left.type !== "empty") return -1;
        if (left.type === "number" && right.type === "number") {
            return left.value - right.value;
        }
        return new Intl.Collator("ru", {numeric: true, sensitivity: "base"})
            .compare(String(left.value), String(right.value));
    };

    const MONEY_HEADER_PATTERN = /(?:^|\s)(?:сумма|сумма\s*\/\s*ндс|ндс|остаток|выручка|расход|расходы|маржа|маржинальность|прибыль|себестоимость|ставка|цена|стоимость|задолженность|долг|оплата|плат[её]ж|оплачено|получено|выплачено|начислено|лимит|итого|оборот)(?:\s|$)/i;

    const alignMoneyColumn = (table, column) => {
        const rows = [
            ...Array.from(table.tHead?.rows || []),
            ...Array.from(table.tBodies).flatMap((tbody) => Array.from(tbody.rows)),
            ...Array.from(table.tFoot?.rows || []),
        ];
        rows.forEach((row) => {
            const cell = row.cells[column];
            if (!cell) return;
            cell.classList.add("uk-text-right", "crm-money-cell");
            if (!cell.dataset.sortType) cell.dataset.sortType = "number";
        });
    };

    const alignExplicitMoneyCells = (table) => {
        table.querySelectorAll(".amount-income, .amount-expense, .amount-problem").forEach((element) => {
            const cell = element.closest("td, th");
            if (!cell) return;
            cell.classList.add("uk-text-right", "crm-money-cell");
            if (!cell.dataset.sortType) cell.dataset.sortType = "number";
        });
    };

    const isDataRow = (row, columnCount) => {
        if (row.dataset.sortable === "false") return false;
        if (row.querySelector(".empty-state, .empty-cell")) return false;
        if (row.classList.contains("uk-text-bold") || row.dataset.total === "true") return false;
        return row.cells.length >= columnCount;
    };

    const sortTable = (table, column, direction) => {
        const headerRow = table.querySelector("thead tr:last-child");
        if (!headerRow) return;
        const columnCount = headerRow.cells.length;
        const factor = direction === "desc" ? -1 : 1;
        Array.from(table.tBodies).forEach((tbody) => {
            const rows = Array.from(tbody.rows);
            const sortable = rows.filter((row) => isDataRow(row, columnCount));
            if (sortable.length < 2) return;
            const slots = sortable.slice();
            const positions = new Map(sortable.map((row, index) => [row, index]));
            sortable.sort((left, right) => {
                const result = compare(
                    cellValue(left.cells[column]),
                    cellValue(right.cells[column]),
                );
                return result * factor || positions.get(left) - positions.get(right);
            });
            // Replace only data-row slots, leaving totals and empty-state
            // rows exactly where the template placed them.
            const markers = slots.map(() => document.createComment("crm-sort-slot"));
            slots.forEach((row, index) => tbody.replaceChild(markers[index], row));
            sortable.forEach((row, index) => tbody.replaceChild(row, markers[index]));
        });
    };

    const enhanceTable = (table) => {
        if (table.dataset.tableSortReady === "true") return;
        const headerRow = table.querySelector("thead tr:last-child");
        if (!headerRow || !table.tBodies.length) return;
        table.dataset.tableSortReady = "true";
        alignExplicitMoneyCells(table);
        const headers = Array.from(headerRow.cells);
        headers.forEach((header, index) => {
            if (MONEY_HEADER_PATTERN.test(cleanText(header.textContent))) {
                alignMoneyColumn(table, index);
            }
            if (!cleanText(header.textContent) || header.querySelector("input, button")) return;
            header.classList.add("crm-sortable-header");
            header.setAttribute("role", "button");
            header.setAttribute("tabindex", "0");
            header.setAttribute("aria-sort", "none");
            header.title = "Сортировать";
            const activate = () => {
                const current = table.dataset.sortColumn === String(index)
                    ? table.dataset.sortDirection
                    : "";
                const direction = current === "asc" ? "desc" : "asc";
                headers.forEach((item) => {
                    if (item.classList.contains("crm-sortable-header")) {
                        item.setAttribute("aria-sort", "none");
                    }
                });
                header.setAttribute("aria-sort", direction === "asc" ? "ascending" : "descending");
                table.dataset.sortColumn = String(index);
                table.dataset.sortDirection = direction;
                sortTable(table, index, direction);
            };
            header.addEventListener("click", activate);
            header.addEventListener("keydown", (event) => {
                if (event.key !== "Enter" && event.key !== " ") return;
                event.preventDefault();
                activate();
            });
        });
    };

    const init = (root = document) => {
        root.querySelectorAll(TABLE_SELECTOR).forEach(enhanceTable);
    };

    window.CrmTableSort = {init};
    document.addEventListener("DOMContentLoaded", () => {
        init();
        // Keep AJAX/modal-inserted register tables sortable as well.
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => mutation.addedNodes.forEach((node) => {
                if (node.nodeType !== 1) return;
                if (node.matches?.(TABLE_SELECTOR)) enhanceTable(node);
                init(node);
            }));
        });
        observer.observe(document.body, {childList: true, subtree: true});
    });
})();
