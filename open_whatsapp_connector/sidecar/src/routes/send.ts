import { Router, type Request, type Response } from "express";
import type { SessionManager } from "../services/session-manager.js";

export function createSendRoutes(manager: SessionManager): Router {
  const router = Router();

  router.post("/send/text", async (req: Request, res: Response) => {
    try {
      const { account_id, to, body, reply_to, mention_all, mentions } = req.body;
      if (!account_id || !to || !body) {
        res.status(400).json({ error: "account_id, to, and body are required" });
        return;
      }
      const result = await manager.sendText(account_id, to, body, reply_to, {
        mentionAll: !!mention_all,
        mentions: Array.isArray(mentions) ? mentions : undefined,
      });
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  router.post("/send/media", async (req: Request, res: Response) => {
    try {
      const { account_id, to, media_base64, mimetype, filename, caption, ptt, gif_playback } = req.body;
      if (!account_id || !to || !media_base64 || !mimetype) {
        res.status(400).json({ error: "account_id, to, media_base64, and mimetype are required" });
        return;
      }
      const result = await manager.sendMedia(account_id, to, media_base64, mimetype, filename, caption, {
        ptt: !!ptt,
        gifPlayback: !!gif_playback,
      });
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  router.post("/send/album", async (req: Request, res: Response) => {
    try {
      const { account_id, to, items } = req.body;
      if (!account_id || !to || !Array.isArray(items) || items.length < 2) {
        res.status(400).json({ error: "account_id, to, and items[] (>=2) are required" });
        return;
      }
      const result = await manager.sendAlbum(account_id, to, items);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  router.post("/send/poll", async (req: Request, res: Response) => {
    try {
      const { account_id, to, name, options, selectable_count } = req.body;
      if (!account_id || !to || !name || !Array.isArray(options) || !options.length) {
        res.status(400).json({ error: "account_id, to, name, and options[] are required" });
        return;
      }
      const result = await manager.sendPoll(account_id, to, name, options, selectable_count ?? 1);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  router.post("/send/contact", async (req: Request, res: Response) => {
    try {
      const { account_id, to, contacts } = req.body;
      if (!account_id || !to || !Array.isArray(contacts) || !contacts.length) {
        res.status(400).json({ error: "account_id, to, and contacts[] are required" });
        return;
      }
      const result = await manager.sendContact(account_id, to, contacts);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  router.post("/send/location", async (req: Request, res: Response) => {
    try {
      const { account_id, to, latitude, longitude, name, address } = req.body;
      if (!account_id || !to || latitude === undefined || longitude === undefined) {
        res.status(400).json({ error: "account_id, to, latitude, and longitude are required" });
        return;
      }
      const result = await manager.sendLocation(account_id, to, latitude, longitude, name, address);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  router.post("/send/reaction", async (req: Request, res: Response) => {
    try {
      const { account_id, chat_jid, message_id, emoji, from_me } = req.body;
      if (!account_id || !chat_jid || !message_id || !emoji) {
        res.status(400).json({ error: "account_id, chat_jid, message_id, and emoji are required" });
        return;
      }
      await manager.sendReaction(account_id, chat_jid, message_id, emoji, from_me ?? false);
      res.json({ success: true });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  router.post("/send/buttons", async (req: Request, res: Response) => {
    try {
      const { account_id, to, body, footer, buttons, header } = req.body;
      if (!account_id || !to || !body || !buttons || !buttons.length) {
        res.status(400).json({ error: "account_id, to, body, and buttons are required" });
        return;
      }
      if (buttons.length > 3) {
        res.status(400).json({ error: "Maximum 3 buttons allowed" });
        return;
      }
      const result = await manager.sendButtons(account_id, to, body, buttons, header, footer);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  router.post("/send/list", async (req: Request, res: Response) => {
    try {
      const { account_id, to, body, footer, button_text, sections } = req.body;
      if (!account_id || !to || !body || !sections || !sections.length) {
        res.status(400).json({ error: "account_id, to, body, and sections are required" });
        return;
      }
      const result = await manager.sendList(account_id, to, body, button_text || "Menu", sections, footer);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  router.post("/status/broadcast", async (req: Request, res: Response) => {
    try {
      const { account_id, type, text, attachment_b64, mimetype, recipients } = req.body;
      if (!account_id || !type) {
        res.status(400).json({ error: "account_id and type are required" });
        return;
      }
      if (!["text", "image", "video"].includes(type)) {
        res.status(400).json({ error: "type must be text, image, or video" });
        return;
      }
      const result = await manager.sendStatusBroadcast(
        account_id,
        type,
        text,
        attachment_b64,
        mimetype,
        Array.isArray(recipients) ? recipients : [],
      );
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  router.get("/groups/:account_id", async (req: Request, res: Response) => {
    try {
      const groups = await manager.getGroups(req.params.account_id);
      res.json({ groups });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  return router;
}
