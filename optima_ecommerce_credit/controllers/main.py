from odoo.http import Controller, request, route


class OptimaCreditController(Controller):
    _process_url = "/payment/optima_credit/process"

    @route(_process_url, type="http", auth="public", methods=["POST"], csrf=False)
    def optima_credit_process_transaction(self, **post):
        request.env["payment.transaction"].sudo()._handle_notification_data(
            "optima_credit", post
        )
        return request.redirect("/payment/status")
