from urllib.parse import urlparse

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SendcloudZonalTestWizard(models.TransientModel):
    _name = "sendcloud.zonal.test.wizard"
    _description = "Sendcloud Zonal Shipping Methods Test"

    integration_id = fields.Many2one(
        "sendcloud.integration",
        string="Integration",
        required=True,
        default=lambda self: self.env.company.sendcloud_default_integration_id,
        domain="[('company_id', '=', company_id)]",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        readonly=True,
    )
    sender_address_id = fields.Many2one(
        "sendcloud.sender.address",
        string="Sender Address",
        required=True,
        domain="[('company_id', '=', company_id)]",
        default=lambda self: self._default_sender_address(),
    )
    from_postal_code = fields.Char(
        string="From Postal Code",
        required=True,
        default=lambda self: self._default_from_postal_code(),
    )
    to_country_id = fields.Many2one(
        "res.country",
        string="Destination Country",
        required=True,
        default=lambda self: self.env.ref("base.es", raise_if_not_found=False),
    )
    to_postal_code = fields.Char(
        string="To Postal Code",
        required=True,
        default="28001",
        help="Use a real destination postal code. 28001 (Madrid) is only a diagnostic default.",
    )
    service_point_id = fields.Integer(
        string="Service Point ID",
        help="Optional. Leave empty for the first test. It can be filled later to test a specific pickup point.",
    )
    carrier_filter = fields.Char(
        string="Carrier Filter",
        default="correos",
        help="Only affects the displayed diagnostic matches, not the Sendcloud request.",
    )
    name_filter = fields.Char(
        string="Name Filter",
        default="pudo",
        help="Only affects the displayed diagnostic matches, not the Sendcloud request.",
    )

    baseline_count = fields.Integer(string="Baseline Methods", readonly=True)
    zonal_count = fields.Integer(string="Zonal Methods", readonly=True)
    baseline_match_count = fields.Integer(string="Baseline Matches", readonly=True)
    zonal_match_count = fields.Integer(string="Zonal Matches", readonly=True)
    baseline_params = fields.Text(string="Baseline Parameters", readonly=True)
    zonal_params = fields.Text(string="Zonal Parameters", readonly=True)
    baseline_results = fields.Text(string="Baseline Matching Methods", readonly=True)
    zonal_results = fields.Text(string="Zonal Matching Methods", readonly=True)
    conclusion = fields.Text(string="Diagnostic Conclusion", readonly=True)

    @api.model
    def _default_sender_address(self):
        return self.env["sendcloud.sender.address"].search(
            [("company_id", "=", self.env.company.id), ("active", "=", True)],
            limit=1,
        )

    @api.model
    def _default_from_postal_code(self):
        sender = self._default_sender_address()
        return sender.postal_code if sender else False

    @api.onchange("sender_address_id")
    def _onchange_sender_address_id(self):
        if self.sender_address_id and self.sender_address_id.postal_code:
            self.from_postal_code = self.sender_address_id.postal_code

    def _get_all_methods(self, params):
        """Call the v2 endpoint and follow pagination if Sendcloud returns it."""
        self.ensure_one()
        integration = self.integration_id
        urlpath = "/shipping_methods"
        response = integration._get_panel_request(urlpath, params)
        methods = list(response.get("shipping_methods") or [])
        next_url = response.get("next")
        while next_url:
            parsed = urlparse(next_url)
            response = integration._get_panel_request(urlpath + "?" + parsed.query)
            methods.extend(response.get("shipping_methods") or [])
            next_url = response.get("next")
        return methods

    def _method_matches(self, method):
        carrier_filter = (self.carrier_filter or "").strip().lower()
        name_filter = (self.name_filter or "").strip().lower()
        carrier = str(method.get("carrier") or "").lower()
        name = str(method.get("name") or "").lower()
        return (not carrier_filter or carrier_filter in carrier) and (
            not name_filter or name_filter in name
        )

    def _format_methods(self, methods):
        matches = [method for method in methods if self._method_matches(method)]
        if not matches:
            return 0, _("No matching methods returned by Sendcloud.")

        lines = []
        for method in matches:
            countries = []
            for country in method.get("countries") or []:
                from_iso = country.get("from_iso_2") or "?"
                to_iso = country.get("iso_2") or "?"
                price = country.get("price")
                countries.append(f"{from_iso}->{to_iso} (price={price})")
            route_text = ", ".join(countries) if countries else "-"
            lines.append(
                "ID: {id}\n"
                "Name: {name}\n"
                "Carrier: {carrier}\n"
                "Service Point: {sp}\n"
                "Weight: {min_w} - {max_w} kg\n"
                "Routes: {routes}\n".format(
                    id=method.get("id"),
                    name=method.get("name"),
                    carrier=method.get("carrier"),
                    sp=method.get("service_point_input"),
                    min_w=method.get("min_weight"),
                    max_w=method.get("max_weight"),
                    routes=route_text,
                )
            )
        return len(matches), "\n------------------------------\n".join(lines)

    def action_run_test(self):
        self.ensure_one()
        if not self.integration_id:
            raise UserError(_("No Sendcloud integration selected."))
        if not self.sender_address_id:
            raise UserError(_("Select a Sendcloud sender address."))
        if not self.from_postal_code or not self.to_postal_code:
            raise UserError(_("Origin and destination postal codes are required."))
        if not self.to_country_id.code:
            raise UserError(_("The destination country needs an ISO-2 code."))

        baseline_params = {"sender_address": "all"}
        zonal_params = {
            "sender_address": str(self.sender_address_id.sendcloud_code),
            "from_postal_code": self.from_postal_code.strip(),
            "to_postal_code": self.to_postal_code.strip(),
            "to_country": self.to_country_id.code,
        }
        if self.service_point_id:
            zonal_params["service_point_id"] = self.service_point_id

        baseline_methods = self._get_all_methods(baseline_params)
        zonal_methods = self._get_all_methods(zonal_params)

        baseline_match_count, baseline_results = self._format_methods(baseline_methods)
        zonal_match_count, zonal_results = self._format_methods(zonal_methods)

        if zonal_match_count > baseline_match_count:
            conclusion = _(
                "The zonal query returns more matching methods than the current OCA-style query. "
                "This confirms that postal/country parameters materially affect the available methods."
            )
        elif zonal_match_count and not baseline_match_count:
            conclusion = _(
                "The requested method only appears in the zonal query. This confirms the missing "
                "Spain-to-Spain method is caused by the parameters used during synchronization."
            )
        elif zonal_match_count:
            conclusion = _(
                "Matching methods are returned by both queries. Compare the IDs, routes and service-point flags below."
            )
        else:
            conclusion = _(
                "No matching method was returned by the zonal query. Try another real Spanish destination postal code "
                "or clear the name filter to inspect all Correos methods. The full API responses are also recorded in Sendcloud Logging."
            )

        self.write(
            {
                "baseline_count": len(baseline_methods),
                "zonal_count": len(zonal_methods),
                "baseline_match_count": baseline_match_count,
                "zonal_match_count": zonal_match_count,
                "baseline_params": str(baseline_params),
                "zonal_params": str(zonal_params),
                "baseline_results": baseline_results,
                "zonal_results": zonal_results,
                "conclusion": conclusion,
            }
        )

        return {
            "type": "ir.actions.act_window",
            "name": _("Test Spain Shipping Methods"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
