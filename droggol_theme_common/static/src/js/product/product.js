/** @odoo-module **/

import { Product } from "@sale/js/product/product";
import { patch } from "@web/core/utils/patch";

patch(Product, {
    props: {
        ...Product.props,
        extraInfo: {
            type: Object,
            optional: true,
        },
    },
});
