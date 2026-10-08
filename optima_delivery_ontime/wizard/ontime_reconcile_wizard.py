from odoo import _, fields, models
from odoo.exceptions import UserError


class OnTimeReconcileWizard(models.TransientModel):
    _name = "delivery.ontime.reconcile.wizard"
    _description = "Reconcile uncertain OnTime operation"

    picking_id = fields.Many2one(
        "stock.picking",
        string="Delivery Order",
        required=True,
        readonly=True,
    )
    operation_state = fields.Selection(
        related="picking_id.ontime_operation_state",
        string="Current OnTime State",
        readonly=True,
    )
    resolution = fields.Selection(
        [
            ("link_existing", "Creation succeeded: link existing OnTime reference"),
            ("allow_create_retry", "Creation did not happen: allow creation retry"),
            ("confirm_cancelled", "Cancellation succeeded: mark shipment cancelled"),
            ("allow_cancel_retry", "Cancellation did not happen: allow cancellation retry"),
        ],
        string="Resolution",
        required=True,
    )
    reference = fields.Char(
        string="OnTime Shipment Reference",
        help="Required when linking a shipment that was created remotely after an uncertain response.",
    )
    note = fields.Text(
        string="Reconciliation Note",
        required=True,
        help="Record how the result was verified in OnTime before resolving the uncertain state.",
    )

    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group("base.group_system"):
            raise UserError(_("Only an administrator can reconcile uncertain OnTime operations."))

        picking = self.picking_id
        carrier = picking.carrier_id
        if not carrier or carrier.delivery_type != "ontime":
            raise UserError(_("This delivery order is not assigned to an OnTime carrier."))

        carrier._ontime_validate_company(picking)
        carrier._ontime_lock_picking(picking)
        state = picking.ontime_operation_state
        note = (self.note or "").strip()
        now = fields.Datetime.now()

        if self.resolution == "link_existing":
            if state != "create_uncertain":
                raise UserError(_("This resolution is only valid for an uncertain creation."))
            reference = (self.reference or "").strip()
            if not reference:
                raise UserError(_("Enter the OnTime shipment reference confirmed in OnTime."))
            carrier._ontime_assert_reference_available(picking, reference)
            picking.write(
                {
                    "ontime_shipment_reference": reference,
                    "carrier_tracking_ref": reference,
                    "ontime_shipment_status": "RECONCILED",
                    "ontime_shipment_created_at": picking.ontime_shipment_created_at or now,
                    "ontime_operation_state": "created",
                    "ontime_last_api_error": False,
                    "ontime_reconciled_at": now,
                    "ontime_reconciliation_note": note,
                }
            )
            picking.message_post(
                body=_(
                    "OnTime uncertain creation reconciled manually. Existing shipment reference "
                    "%(reference)s was linked. Note: %(note)s"
                )
                % {"reference": reference, "note": note}
            )

        elif self.resolution == "allow_create_retry":
            if state != "create_uncertain":
                raise UserError(_("This resolution is only valid for an uncertain creation."))
            if picking.ontime_shipment_reference:
                raise UserError(
                    _("A shipment reference is already linked; creation retry cannot be enabled.")
                )
            picking.write(
                {
                    "ontime_operation_state": "none",
                    "ontime_last_api_error": False,
                    "ontime_reconciled_at": now,
                    "ontime_reconciliation_note": note,
                }
            )
            picking.message_post(
                body=_(
                    "OnTime uncertain creation reconciled manually: the operator confirmed that "
                    "no remote shipment exists, so a new creation attempt is allowed. Note: %s"
                )
                % note
            )

        elif self.resolution == "confirm_cancelled":
            if state != "cancel_uncertain":
                raise UserError(_("This resolution is only valid for an uncertain cancellation."))
            carrier._ontime_mark_cancelled(picking)
            picking.write(
                {
                    "ontime_reconciled_at": now,
                    "ontime_reconciliation_note": note,
                }
            )
            picking.message_post(
                body=_("OnTime uncertain cancellation was confirmed manually. Note: %s") % note
            )

        elif self.resolution == "allow_cancel_retry":
            if state != "cancel_uncertain":
                raise UserError(_("This resolution is only valid for an uncertain cancellation."))
            picking.write(
                {
                    "ontime_operation_state": "created",
                    "ontime_last_api_error": False,
                    "ontime_reconciled_at": now,
                    "ontime_reconciliation_note": note,
                }
            )
            picking.message_post(
                body=_(
                    "OnTime uncertain cancellation reconciled manually: the operator confirmed "
                    "that the shipment remains active, so cancellation may be retried. Note: %s"
                )
                % note
            )
        else:
            raise UserError(_("Select a valid OnTime reconciliation resolution."))

        return {"type": "ir.actions.act_window_close"}
