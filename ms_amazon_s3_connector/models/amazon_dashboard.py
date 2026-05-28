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
import os
import logging
from odoo import models
from datetime import datetime, timedelta


_logger = logging.getLogger(__name__)


class AmazonDashboard(models.Model):
    """
    Amazon dashboard Model to connect with amazon S3
    """
    _name = 'amazon.dashboard'
    _description = "Amazon Dashboard"

    def get_s3_accounts(self):
        """Return list of active S3 accounts for the dashboard dropdown."""
        accounts = self.env['amazon.s3.account'].search_read(
            [('active', '=', True)],
            ['id', 'name', 'bucket_name'],
        )
        return accounts

    PAGE_SIZE = 100

    def _parse_s3_contents(self, account, client, contents):
        """Parse S3 object list into file dicts."""
        files = []
        image_extensions = {
            'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg'}
        for data in contents:
            if data['Size'] == 0:
                continue
            url = client.generate_presigned_url(
                ClientMethod='get_object',
                Params={
                    'Bucket': account.bucket_name,
                    'Key': data['Key'],
                })
            size_bytes = data['Size'] / 1024
            if size_bytes > 1024:
                size = str(
                    round(data['Size'] / (1024 * 1024), 1)) + ' MB'
            else:
                size = str(round(data['Size'] / 1024, 1)) + ' KB'
            ext = os.path.splitext(
                data['Key'])[1].replace('.', '').lower()
            file_type = ext.upper()
            is_image = ext in image_extensions
            is_pdf = ext == 'pdf'
            files.append({
                'name': data['Key'],
                'url': url,
                'file_type': file_type,
                'last_modified': str(data['LastModified']),
                'size': size,
                'is_image': is_image,
                'is_pdf': is_pdf,
                'extension': ext,
                'account_name': account.name,
                'bucket_name': account.bucket_name,
            })
        return files

    def _fetch_files_paginated(self, account, max_keys,
                               continuation_token=None):
        """
        Fetch up to max_keys files from a single S3 account.
        Returns (files, next_continuation_token or None).
        """
        client = account._get_s3_client()
        kwargs = {
            'Bucket': account.bucket_name,
            'MaxKeys': max_keys,
        }
        if continuation_token:
            kwargs['ContinuationToken'] = continuation_token
        response = client.list_objects_v2(**kwargs)
        files = self._parse_s3_contents(
            account, client, response.get('Contents', []))
        next_token = response.get('NextContinuationToken')
        return files, next_token

    def amazon_view_files(self, account_id=None, page_tokens=None):
        """
        Fetch files from S3 with pagination (PAGE_SIZE files per page).

        :param account_id: specific account id, 'all', or None (= all)
        :param page_tokens: dict {str(account_id): token} for continuation,
                            None for first page
        :returns: dict with 'files', 'has_next', 'next_tokens'
        """
        if account_id and account_id != 'all':
            accounts = self.env['amazon.s3.account'].browse(int(account_id))
        else:
            accounts = self.env['amazon.s3.account'].search(
                [('active', '=', True)])
        if not accounts:
            return False

        # On subsequent pages, only fetch accounts still in page_tokens
        if page_tokens is not None:
            candidate_ids = [int(k) for k in page_tokens.keys()]
            accounts = accounts.filtered(lambda a: a.id in candidate_ids)

        all_files = []
        next_tokens = {}
        errors = []
        remaining = self.PAGE_SIZE

        for account in accounts:
            if remaining <= 0:
                # Carry forward this account's token for the next page
                token = (page_tokens or {}).get(str(account.id), '')
                next_tokens[str(account.id)] = token
                continue

            current_token = (page_tokens or {}).get(str(account.id))
            if current_token == '':
                current_token = None

            try:
                files, new_token = self._fetch_files_paginated(
                    account, remaining, current_token)
                all_files.extend(files)
                remaining -= len(files)
                if new_token:
                    next_tokens[str(account.id)] = new_token
            except Exception as e:
                errors.append(f"{account.name}: {e}")

        if errors and not all_files:
            return {'error': '; '.join(errors)}

        return {
            'files': all_files,
            'has_next': bool(next_tokens),
            'next_tokens': next_tokens if next_tokens else None,
        }

    def scheduler_action_amazon_upload(self):
        """
        Scheduled action: uploads attachments to S3 for each active account
        based on the models selected on that account.
        """
        last_24_hours = datetime.now() - timedelta(hours=24)
        accounts = self.env['amazon.s3.account'].sudo().search(
            [('active', '=', True)])
        for account in accounts:
            model_names = account.model_ids.mapped('model')
            if not model_names:
                continue
            attachments = self.env['ir.attachment'].search([
                ('res_model', 'in', model_names),
                ('create_date', '>=', last_24_hours),
                ('s3_uploaded_account_ids', 'not in', [account.id]),
            ])
            if not attachments:
                continue
            try:
                s3_resource = account._get_s3_resource()
                bucket = s3_resource.Bucket(account.bucket_name)
                for attachment in attachments:
                    key = (
                        attachment.res_model.replace('.', '_')
                        + '_pr0ffyd0c_'
                        + str(attachment.res_id)
                        + '_pr0ffyd0c_'
                        + attachment.name
                    )
                    bucket.put_object(
                        Key=key,
                        Body=open(
                            attachment._full_path(attachment.store_fname),
                            'rb'),
                    )
                    record = self.env[attachment.res_model].browse(
                        attachment.res_id)
                    if hasattr(record, 'message_post'):
                        record.message_post(
                            body=(
                                f"File {attachment.name} has been "
                                f"successfully uploaded to S3 Bucket "
                                f"'{account.bucket_name}'"
                            ),
                            subtype_xmlid='mail.mt_note',
                        )
                    attachment.s3_uploaded_account_ids = [(4, account.id)]
                    attachment.is_file_uploaded = True
            except Exception as e:
                _logger.warning(
                    'Failed to upload files for account %s: %s',
                    account.name, e)
