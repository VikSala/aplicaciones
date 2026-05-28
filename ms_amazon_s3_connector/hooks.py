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


def post_init_hook(env):
    """
    Migrate legacy single-account config to the new amazon.s3.account model.
    """
    ICP = env['ir.config_parameter'].sudo()
    access_key = ICP.get_param('ms_amazon_s3_connector.amazon_access_key')
    secret_key = ICP.get_param('ms_amazon_s3_connector.amazon_secret_key')
    bucket_name = ICP.get_param('ms_amazon_s3_connector.amazon_bucket_name')
    if access_key and secret_key and bucket_name:
        model_ids = env['ir.model'].search([
            ('model', 'in', ['res.partner', 'project.task', 'planning.role'])
        ])
        env['amazon.s3.account'].create({
            'name': f'Migrated Account ({bucket_name})',
            'access_key': access_key,
            'secret_key': secret_key,
            'bucket_name': bucket_name,
            'active': True,
            'model_ids': [(6, 0, model_ids.ids)],
        })


def uninstall_hook(env):
    """
    Deletes System Parameters
    """
    env['ir.config_parameter'].sudo().search(
        [('key', '=', 'ms_amazon_s3_connector.amazon_access_key')]).unlink()
    env['ir.config_parameter'].sudo().search(
        [('key', '=', 'ms_amazon_s3_connector.amazon_secret_key')]).unlink()
    env['ir.config_parameter'].sudo().search(
        [('key', '=', 'ms_amazon_s3_connector.amazon_bucket_name')]).unlink()
