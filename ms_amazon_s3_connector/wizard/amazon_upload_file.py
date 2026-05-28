# -*- coding: utf-8 -*-
################################################################################
#
#    MountSol
#
#    Copyright (C) 2024-TODAY MountSol(<https://www.mountsol.com>).
#    Author: MountSol (contact@mountsol.com)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
################################################################################
from odoo import fields, models
from odoo.exceptions import ValidationError


class AmazonUploadFile(models.TransientModel):
    """
    For opening wizard view
    """
    _name = "amazon.upload.file"
    _description = "Amazon Upload File"

    account_id = fields.Many2one(
        'amazon.s3.account',
        string='S3 Account',
        required=True,
        domain=[('active', '=', True)],
        default=lambda self: self.env.context.get('default_account_id'),
    )
    file = fields.Binary(string="Attachment", help="Select a file to upload")
    file_name = fields.Char(string="File Name",
                            help="Name of the file to upload")

    def action_amazon_upload(self):
        """
        Uploads file to Amazon S3
        """
        attachment = self.env["ir.attachment"].search(
            ['|', ('res_field', '!=', False), ('res_field', '=', False),
             ('res_id', '=', self.id),
             ('res_model', '=', 'amazon.upload.file')])
        try:
            s3_resource = self.account_id._get_s3_resource()
            s3_resource.Bucket(self.account_id.bucket_name).put_object(
                Key=self.file_name,
                Body=open((attachment._full_path(attachment.store_fname)),
                          'rb'))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'success',
                    'message': 'File has been uploaded successfully. '
                               'Please refresh the page.',
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
        except Exception as e:
            raise ValidationError(
                'Failed to Upload Files ( %s .)' % e)
