/** @odoo-module **/

import { ThemeConfigDialog } from '../theme_config/theme_config';
import { registry } from "@web/core/registry";

registry.category('website_custom_menus').add('droggol_theme_common.menu_theme_prime_config', {
    Component: ThemeConfigDialog,
    isDisplayed: (env) => !!env.services.website.currentWebsite
        && env.services.website.isDesigner
});
