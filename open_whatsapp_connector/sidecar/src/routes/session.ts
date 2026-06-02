import { Router, type Request, type Response } from "express";
import type { SessionManager } from "../services/session-manager.js";

export function createSessionRoutes(manager: SessionManager): Router {
  const router = Router();

  router.post("/session/create", async (req: Request, res: Response) => {
    try {
      const { account_id, odoo_base_url, callback_url, webhook_secret, send_read_receipts } = req.body;
      if (!account_id || !odoo_base_url || !webhook_secret) {
        res.status(400).json({ error: "account_id, odoo_base_url, and webhook_secret are required" });
        return;
      }
      const result = await manager.createSession(
        account_id, odoo_base_url, webhook_secret, callback_url,
        send_read_receipts !== false,
      );
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  router.post("/session/:id/config", (req: Request, res: Response) => {
    const { send_read_receipts } = req.body || {};
    const result = manager.updateSessionConfig(req.params.id, {
      sendReadReceipts: typeof send_read_receipts === "boolean" ? send_read_receipts : undefined,
    });
    if (!result.ok) {
      res.status(404).json({ error: "Session not found" });
      return;
    }
    res.json(result);
  });

  router.get("/session/:id/status", (req: Request, res: Response) => {
    const session = manager.getSession(req.params.id);
    if (!session) {
      res.status(404).json({ error: "Session not found" });
      return;
    }
    res.json(session);
  });

  router.get("/session/:id/qr", (req: Request, res: Response) => {
    const session = manager.getSession(req.params.id);
    if (!session?.qr_base64) {
      res.status(404).json({ error: "No QR code available" });
      return;
    }
    res.json({ qr_base64: session.qr_base64 });
  });

  router.post("/session/:id/disconnect", async (req: Request, res: Response) => {
    const ok = await manager.disconnect(req.params.id);
    res.json({ success: ok });
  });

  router.post("/session/:id/logout", async (req: Request, res: Response) => {
    const ok = await manager.logout(req.params.id);
    res.json({ success: ok });
  });

  return router;
}
