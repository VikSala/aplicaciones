import { Composer } from "@mail/core/common/composer_model";
import { patch } from "@web/core/utils/patch";

// NB: the previous code passed a string as Object.assign's 2nd arg, which
// copied the string's characters as numeric-index keys (0:'o',1:'w',...) onto
// the prototype. Use the tracked patch() util with the two-arg form instead.
// (#discuss)
patch(Composer.prototype, {
    threadExpired: false,
});
