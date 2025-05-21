/** @odoo-module **/

import {
    ProductTemplateAttributeLine as PTAL
} from "@sale/js/product_template_attribute_line/product_template_attribute_line";
import { patch } from "@web/core/utils/patch";

patch(PTAL, {
    props: {
        ...PTAL.props,
        attribute: {
            type: Object,
            shape: {
                id: Number,
                name: String,
                display_type: {
                    type: String,
                    validate: type => ["color", "multi", "pills", "radio", "select", "radio_circle", "radio_square", "radio_image"].includes(type),
                },
            },
        },
        extraInfo: {
            type: Object,
            optional: true,
        },
    },
});

patch(PTAL.prototype, {
    getPTAVTemplate() {
        switch (this.props.attribute.display_type) {
            case 'radio_circle':
                return 'sale.ptav_pills';
            case 'radio_square':
                return 'sale.ptav_pills';
            case 'radio_image':
                return 'droggolSaleProductConfigurator.ptav_radio_image';
        }
        return super.getPTAVTemplate();
    }
});
