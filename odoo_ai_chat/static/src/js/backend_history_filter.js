/**
 * Aplica automáticamente el filtro de Cliente/Proveedor cuando el botón del chat
 * abre las vistas estándar de Odoo (/odoo/sales o /odoo/purchase).
 *
 * Se mantiene separado del chat frontend para no alterar la lógica ya existente:
 * solo actúa en backend si la URL incluye ai_chat_history_filter=1.
 */
(function () {
    "use strict";

    function getParam(name) {
        try {
            return new URL(window.location.href).searchParams.get(name) || "";
        } catch (error) {
            return "";
        }
    }

    function isEnabled() {
        return getParam("ai_chat_history_filter") === "1";
    }

    function textOf(node) {
        return (node && (node.innerText || node.textContent) || "").replace(/\s+/g, " ").trim();
    }

    function cleanUrl() {
        try {
            var url = new URL(window.location.href);
            [
                "ai_chat_history_filter",
                "ai_chat_history_kind",
                "ai_chat_partner_id",
                "ai_chat_partner_name",
                "ai_chat_partner_field"
            ].forEach(function (key) {
                url.searchParams.delete(key);
            });
            var clean = url.pathname + (url.search ? url.search : "") + (url.hash || "");
            window.history.replaceState(window.history.state, document.title, clean);
        } catch (error) {
            // Si el navegador no permite limpiar la URL, el filtro ya seguirá aplicado.
        }
    }

    function findSearchInput() {
        return document.querySelector(".o_searchview_input") ||
            document.querySelector(".o_searchview input") ||
            document.querySelector("input[placeholder='Buscar...']") ||
            document.querySelector("input[placeholder='Search...']");
    }

    function setInputValue(input, value) {
        input.focus();
        if ("value" in input) {
            input.value = value;
        } else {
            input.textContent = value;
        }
        input.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "insertText", data: value}));
        input.dispatchEvent(new Event("change", {bubbles: true}));
        input.dispatchEvent(new KeyboardEvent("keyup", {bubbles: true, key: value.slice(-1) || "a"}));
    }

    function optionMatches(option, fieldLabel, partnerName) {
        var text = textOf(option).toLowerCase();
        var field = String(fieldLabel || "").toLowerCase();
        var partner = String(partnerName || "").toLowerCase();
        return text.indexOf("buscar") !== -1 &&
            text.indexOf(field) !== -1 &&
            (!partner || text.indexOf(partner) !== -1 || text.indexOf("para:") !== -1);
    }

    function clickMatchingAutocomplete(fieldLabel, partnerName) {
        var options = Array.prototype.slice.call(document.querySelectorAll(
            ".o_searchview_autocomplete li, .o-autocomplete--dropdown-item, .ui-menu-item, .dropdown-menu .dropdown-item, .o-dropdown--menu .dropdown-item"
        ));
        var match = options.find(function (option) {
            return optionMatches(option, fieldLabel, partnerName);
        }) || options.find(function (option) {
            return textOf(option).toLowerCase().indexOf(String(fieldLabel || "").toLowerCase()) !== -1;
        });
        if (match) {
            match.click();
            return true;
        }
        return false;
    }

    function pressEnter(input) {
        input.dispatchEvent(new KeyboardEvent("keydown", {bubbles: true, cancelable: true, key: "Enter", code: "Enter", which: 13, keyCode: 13}));
        input.dispatchEvent(new KeyboardEvent("keyup", {bubbles: true, cancelable: true, key: "Enter", code: "Enter", which: 13, keyCode: 13}));
    }

    function applyHistoryFilter() {
        if (!isEnabled()) {
            return;
        }

        var partnerName = getParam("ai_chat_partner_name");
        var fieldLabel = getParam("ai_chat_partner_field") || (getParam("ai_chat_history_kind") === "purchase" ? "Proveedor" : "Cliente");
        if (!partnerName) {
            cleanUrl();
            return;
        }

        var attempts = 0;
        var timer = window.setInterval(function () {
            attempts += 1;
            var input = findSearchInput();
            if (!input) {
                if (attempts > 80) {
                    window.clearInterval(timer);
                    cleanUrl();
                }
                return;
            }

            setInputValue(input, partnerName);

            window.setTimeout(function () {
                if (!clickMatchingAutocomplete(fieldLabel, partnerName)) {
                    pressEnter(input);
                }
                window.clearInterval(timer);
                window.setTimeout(cleanUrl, 700);
            }, 500);
        }, 250);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", applyHistoryFilter);
    } else {
        applyHistoryFilter();
    }
})();
