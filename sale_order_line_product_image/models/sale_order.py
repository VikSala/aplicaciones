# -*- coding: utf-8 -*-
# Part of Browseinfo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models,_
import io, base64, subprocess, tempfile
from odoo.exceptions import ValidationError


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    image_128 = fields.Binary(string="Image")

    @api.onchange('product_id')
    def onchange_sale_product_image(self):
        for line in self:
            if line.product_id.image_128:
                print(type(line.product_id.image_128))
                line.image_128 = line.png_to_jpeg_white_bg(line.product_id.image_128)
            else:
                line.image_128 = False

    def png_to_jpeg_white_bg(self, image_bytes: bytes) -> bytes:
        try:
            raw_webp = base64.b64decode(image_bytes)
            if raw_webp.startswith(b'RIFF') and b'WEBP' in raw_webp[:12]:
                with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as webp_file:
                    webp_file.write(raw_webp)
                    webp_file.flush()
                    webp_path = webp_file.name

                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as jpg_file:
                    jpg_path = jpg_file.name

                subprocess.run(["dwebp", webp_path, "-o", jpg_path], check=True)

                with open(jpg_path, "rb") as f:
                    jpeg_bytes = f.read()

                return base64.b64encode(jpeg_bytes)
            else:
                return image_bytes

        except subprocess.CalledProcessError as e:
            raise ValidationError(f"Error while parsing the image:\n{e}\nTry installing the 'webp' package.")
