/** @odoo-module **/

import { whenReady } from "@odoo/owl";

const LISTS_URL = "/my/product-lists";

function isAuthenticatedWebsiteUser() {
    return Boolean(document.querySelector("#cabrera_authenticated_website_user"));
}

function setWishlistCount(count) {
    const hasFavorites = Number(count || 0) > 0;

    document.querySelectorAll("header .o_wsale_my_wish").forEach((wishNode) => {
        // Igual que el comportamiento esperado de Odoo: sin favoritos no se
        // muestra el acceso del header; con favoritos sí, pero sin contador.
        wishNode.classList.toggle("d-none", !hasFavorites);
    });

    document.querySelectorAll("header .my_wish_quantity").forEach((badge) => {
        badge.textContent = String(count || 0);
        badge.classList.add("d-none");
        badge.setAttribute("aria-hidden", "true");
    });
}

async function refreshWishlistCount() {
    try {
        const response = await fetch("/shop/wishlist?count=1", {
            credentials: "same-origin",
            headers: {"X-Requested-With": "XMLHttpRequest"},
        });
        if (!response.ok) {
            return;
        }
        const productIds = await response.json();
        if (Array.isArray(productIds)) {
            setWishlistCount(productIds.length);
        }
    } catch {
        // El icono es un refuerzo visual; un fallo de red no debe afectar a la web.
    }
}

function buildWishlistFromCart(cartNode) {
    const wishNode = cartNode.cloneNode(true);
    wishNode.removeAttribute("id");
    wishNode.classList.remove("o_wsale_my_cart");
    // El fallback nace oculto y solo se muestra cuando confirmamos que hay favoritos.
    wishNode.classList.add("o_wsale_my_wish", "cabrera-header-wishlist", "d-none");

    const link = wishNode.querySelector("a") || wishNode;
    if (link.tagName === "A") {
        link.setAttribute("href", isAuthenticatedWebsiteUser() ? LISTS_URL : "/shop/wishlist");
        link.setAttribute("title", "Mis listas de productos");
        link.setAttribute("aria-label", "Mis listas de productos");
    }

    const icons = wishNode.querySelectorAll(".fa-shopping-cart, .fa-cart-shopping");
    if (icons.length) {
        icons.forEach((icon) => {
            icon.classList.remove("fa-shopping-cart", "fa-cart-shopping");
            icon.classList.add("fa-heart");
        });
    } else if (link.tagName === "A") {
        const icon = document.createElement("i");
        icon.className = "fa fa-heart cabrera-header-wishlist-icon";
        link.prepend(icon);
    }

    let badge = wishNode.querySelector(".my_cart_quantity, .my_wish_quantity");
    if (badge) {
        badge.classList.remove("my_cart_quantity");
        badge.classList.add("my_wish_quantity");
        badge.textContent = "0";
    } else if (link.tagName === "A") {
        badge = document.createElement("sup");
        badge.className = "my_wish_quantity badge rounded-pill cabrera-header-wishlist-badge d-none";
        badge.textContent = "0";
        link.appendChild(badge);
    }

    // Algunos headers muestran un texto junto al carrito. Evitamos heredar "Carrito".
    wishNode.querySelectorAll("span, small").forEach((element) => {
        if (!element.classList.contains("my_wish_quantity") && /carrito|cart/i.test(element.textContent || "")) {
            element.textContent = "Favoritos";
        }
    });

    return wishNode;
}

function ensureWishlistHeaderIcon() {
    const header = document.querySelector("header#top") || document.querySelector("header");
    if (!header || header.querySelector(".o_wsale_my_wish")) {
        return;
    }

    const cartNode = header.querySelector(".o_wsale_my_cart");
    if (!cartNode || !cartNode.parentNode) {
        return;
    }

    const wishNode = buildWishlistFromCart(cartNode);
    cartNode.insertAdjacentElement("afterend", wishNode);
}

whenReady(() => {
    ensureWishlistHeaderIcon();
    refreshWishlistCount();

    // Si el tema reconstruye el header al cargar, repetimos el fallback una vez.
    window.setTimeout(() => {
        ensureWishlistHeaderIcon();
        refreshWishlistCount();
    }, 700);

    // El JS nativo de wishlist actualiza el contador cuando puede. Este refresco
    // cubre también headers personalizados que no incluyen el template estándar.
    document.addEventListener("click", (event) => {
        if (event.target.closest(".o_add_wishlist, .o_add_wishlist_dyn, .o_wish_rm")) {
            window.setTimeout(refreshWishlistCount, 650);
        }
    }, true);

    // En usuarios autenticados el corazón abre directamente el área profesional,
    // incluso cuando Odoo considera que la wishlist está vacía.
    document.addEventListener("click", (event) => {
        const wishlistLink = event.target.closest("header .o_wsale_my_wish a, header a.cabrera-header-wishlist-link");
        if (!wishlistLink || !isAuthenticatedWebsiteUser()) {
            return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        window.location.assign(LISTS_URL);
    }, true);
});
