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
import boto3
import logging
from odoo import fields, models

_logger = logging.getLogger(__name__)


class AmazonS3Account(models.Model):
    _name = 'amazon.s3.account'
    _description = 'Amazon S3 Account'

    name = fields.Char(string='Account Name', required=True)
    access_key = fields.Char(string='Access Key', required=True)
    secret_key = fields.Char(string='Secret Key', required=True)
    bucket_name = fields.Char(string='Bucket Name', required=True)
    active = fields.Boolean(string='Active', default=True)
    model_ids = fields.Many2many(
        'ir.model',
        'amazon_s3_account_model_rel',
        'account_id',
        'model_id',
        string='Models to Sync',
        domain=[('transient', '=', False)],
        help='Attachments belonging to these models will be '
             'auto-uploaded to this S3 bucket by the scheduler.',
    )

    def _get_s3_resource(self):
        self.ensure_one()
        return boto3.resource(
            's3',
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        )

    def _get_s3_client(self):
        self.ensure_one()
        client = boto3.client(
            's3',
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        )
        region = client.get_bucket_location(Bucket=self.bucket_name)
        return boto3.client(
            's3',
            region_name=region['LocationConstraint'],
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        )

    def action_test_connection(self):
        self.ensure_one()
        try:
            client = self._get_s3_client()
            client.list_objects(Bucket=self.bucket_name, MaxKeys=1)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'success',
                    'message': 'Connection successful!',
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'danger',
                    'message': f'Connection failed: {e}',
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
