/** @odoo-module **/

export const pickupProviderRegistry = new Map();

export function registerPickupProvider(code, provider) {
    if (!code || !provider?.open) {
        throw new Error("Invalid pickup provider registration");
    }
    pickupProviderRegistry.set(code, provider);
}
