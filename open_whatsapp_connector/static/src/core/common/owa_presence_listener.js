import { registry } from "@web/core/registry";

/**
 * Phase B3 — pipes `owa_presence` bus events into the Thread model so the
 * sidebar/header can show an online dot. Backend emits one event per chat
 * with `{ channel_id, typing, online }` payload; we mirror them onto the
 * matching Thread record's transient flags.
 */
export const owaPresenceListenerService = {
    dependencies: ["bus_service", "mail.store"],
    start(env, { bus_service, "mail.store": store }) {
        bus_service.subscribe("owa_presence", (payload) => {
            if (!payload?.channel_id) {
                return;
            }
            const thread = store.Thread.get({
                model: "discuss.channel",
                id: payload.channel_id,
            });
            if (!thread) {
                return;
            }
            thread.owaOnline = !!payload.online;
            thread.owaTyping = !!payload.typing;
        });
        bus_service.start();
    },
};

registry.category("services").add("owa.presence_listener", owaPresenceListenerService);
