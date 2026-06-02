/**
 * Phase C/D — extended sidecar surface area.
 *
 * Six administrative / lifecycle routes Baileys exposes that we hadn't
 * surfaced yet. Each maps to a single SessionManager method and is
 * idempotent.
 *
 *   POST  /session/:id/groups/:jid/participants   (Phase C1: group admin)
 *   POST  /session/:id/contacts/:jid/block        (Phase C2)
 *   POST  /session/:id/contacts/:jid/unblock      (Phase C2)
 *   GET   /session/:id/blocklist                  (Phase C2)
 *   POST  /session/:id/profile/picture            (Phase C3)
 *   DELETE /session/:id/profile/picture           (Phase C3)
 *   POST  /session/:id/presence/:jid              (Phase C4: typing indicator)
 *   POST  /session/:id/messages/star              (Phase C5)
 *   POST  /session/:id/call-link                  (Phase C6)
 *   POST  /session/:id/pairing-code               (Phase D)
 */
import { Router, type Request, type Response } from "express";
import type { SessionManager } from "../services/session-manager.js";

export function createWhatsappRoutes(manager: SessionManager): Router {
  const router = Router();

  // ── Phase C1 ─────────────────────────────────────────────────────────
  router.post(
    "/session/:id/groups/:jid/participants",
    async (req: Request, res: Response) => {
      try {
        const { action, jids } = req.body || {};
        if (!["add", "remove", "promote", "demote"].includes(action)) {
          res.status(400).json({ error: "action must be add|remove|promote|demote" });
          return;
        }
        if (!Array.isArray(jids) || jids.length === 0) {
          res.status(400).json({ error: "jids must be a non-empty array" });
          return;
        }
        const result = await manager.groupParticipantsUpdate(
          req.params.id,
          req.params.jid,
          action,
          jids,
        );
        res.json({ result });
      } catch (err: any) {
        res.status(500).json({ error: err.message });
      }
    },
  );

  router.post(
    "/session/:id/groups/:jid/member-label",
    async (req: Request, res: Response) => {
      try {
        const { label } = req.body || {};
        if (typeof label !== "string") {
          res.status(400).json({ error: "label must be a string" });
          return;
        }
        const r = await manager.updateMemberLabel(req.params.id, req.params.jid, label);
        res.json(r);
      } catch (err: any) {
        res.status(500).json({ error: err.message });
      }
    },
  );

  // ── Phase F — group CRUD + invite + settings ────────────────────────
  router.get("/session/:id/groups", async (req: Request, res: Response) => {
    try {
      const r = await manager.groupFetchAllParticipating(req.params.id);
      res.json(r);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  router.post("/session/:id/groups", async (req: Request, res: Response) => {
    try {
      const { subject, participants } = req.body || {};
      if (typeof subject !== "string" || !Array.isArray(participants)) {
        res.status(400).json({ error: "subject (string) and participants (array) are required" });
        return;
      }
      const r = await manager.groupCreate(req.params.id, subject, participants);
      res.json(r);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  router.post(
    "/session/:id/groups/:jid/leave",
    async (req: Request, res: Response) => {
      try {
        const r = await manager.groupLeave(req.params.id, req.params.jid);
        res.json(r);
      } catch (err: any) {
        res.status(500).json({ error: err.message });
      }
    },
  );

  router.post(
    "/session/:id/groups/:jid/subject",
    async (req: Request, res: Response) => {
      try {
        const { subject } = req.body || {};
        if (typeof subject !== "string") {
          res.status(400).json({ error: "subject must be a string" });
          return;
        }
        const r = await manager.groupUpdateSubject(req.params.id, req.params.jid, subject);
        res.json(r);
      } catch (err: any) {
        res.status(500).json({ error: err.message });
      }
    },
  );

  router.post(
    "/session/:id/groups/:jid/description",
    async (req: Request, res: Response) => {
      try {
        const { description } = req.body || {};
        if (typeof description !== "string") {
          res.status(400).json({ error: "description must be a string" });
          return;
        }
        const r = await manager.groupUpdateDescription(req.params.id, req.params.jid, description);
        res.json(r);
      } catch (err: any) {
        res.status(500).json({ error: err.message });
      }
    },
  );

  router.post(
    "/session/:id/groups/:jid/setting",
    async (req: Request, res: Response) => {
      try {
        const { setting } = req.body || {};
        if (typeof setting !== "string") {
          res.status(400).json({ error: "setting must be a string" });
          return;
        }
        const r = await manager.groupSettingUpdate(req.params.id, req.params.jid, setting);
        res.json(r);
      } catch (err: any) {
        res.status(500).json({ error: err.message });
      }
    },
  );

  router.get(
    "/session/:id/groups/:jid/invite",
    async (req: Request, res: Response) => {
      try {
        const r = await manager.groupInviteCode(req.params.id, req.params.jid);
        res.json(r);
      } catch (err: any) {
        res.status(500).json({ error: err.message });
      }
    },
  );

  router.post(
    "/session/:id/groups/:jid/invite/revoke",
    async (req: Request, res: Response) => {
      try {
        const r = await manager.groupRevokeInvite(req.params.id, req.params.jid);
        res.json(r);
      } catch (err: any) {
        res.status(500).json({ error: err.message });
      }
    },
  );

  router.get(
    "/session/:id/invites/:code",
    async (req: Request, res: Response) => {
      try {
        const r = await manager.groupGetInviteInfo(req.params.id, req.params.code);
        res.json(r);
      } catch (err: any) {
        res.status(500).json({ error: err.message });
      }
    },
  );

  router.post(
    "/session/:id/invites/:code/accept",
    async (req: Request, res: Response) => {
      try {
        const r = await manager.groupAcceptInvite(req.params.id, req.params.code);
        res.json(r);
      } catch (err: any) {
        res.status(500).json({ error: err.message });
      }
    },
  );

  // ── Phase G — group profile picture, chat moderation, communities, newsletters, events ─

  router.post(
    "/session/:id/groups/:jid/picture",
    async (req: Request, res: Response) => {
      try {
        const { image_base64 } = req.body || {};
        const r = await manager.updateGroupProfilePicture(
          req.params.id, req.params.jid, image_base64 || null);
        res.json(r);
      } catch (err: any) { res.status(500).json({ error: err.message }); }
    },
  );

  router.delete(
    "/session/:id/groups/:jid/picture",
    async (req: Request, res: Response) => {
      try {
        const r = await manager.updateGroupProfilePicture(req.params.id, req.params.jid, null);
        res.json(r);
      } catch (err: any) { res.status(500).json({ error: err.message }); }
    },
  );

  router.post(
    "/session/:id/messages/forward",
    async (req: Request, res: Response) => {
      try {
        const { from_jid, msg_id, to_jid } = req.body || {};
        if (!from_jid || !msg_id || !to_jid) {
          res.status(400).json({ error: "from_jid, msg_id, and to_jid are required" });
          return;
        }
        const r = await manager.forwardMessage(req.params.id, from_jid, msg_id, to_jid);
        res.json(r);
      } catch (err: any) { res.status(500).json({ error: err.message }); }
    },
  );

  router.post(
    "/session/:id/messages/react",
    async (req: Request, res: Response) => {
      try {
        const { to, target_message_id, emoji, target_from_me, target_participant } = req.body || {};
        if (!to || !target_message_id) {
          res.status(400).json({ error: "to and target_message_id required" });
          return;
        }
        const r = await manager.sendReaction(
          req.params.id, to, target_message_id, emoji || "",
          !!target_from_me, target_participant || undefined);
        res.json(r);
      } catch (err: any) { res.status(500).json({ error: err.message }); }
    },
  );

  router.post(
    "/session/:id/messages/sticker",
    async (req: Request, res: Response) => {
      try {
        const { to, sticker_base64, mimetype } = req.body || {};
        if (!to || !sticker_base64) {
          res.status(400).json({ error: "to and sticker_base64 required" });
          return;
        }
        const r = await manager.sendSticker(req.params.id, to, sticker_base64, mimetype || "image/webp");
        res.json(r);
      } catch (err: any) { res.status(500).json({ error: err.message }); }
    },
  );

  // Phase G bug-fix: /messages/live-location removed. The previous handler
  // sent a static location with a misnamed sequenceNumber arg. Use the
  // existing /send/location route instead.

  router.post(
    "/session/:id/messages/event",
    async (req: Request, res: Response) => {
      try {
        const { to, name, description, start_unix, location } = req.body || {};
        if (!to || !name || !start_unix) {
          res.status(400).json({ error: "to, name, start_unix required" });
          return;
        }
        const r = await manager.sendEvent(
          req.params.id, to, name, description || "",
          Math.floor(start_unix), location);
        res.json(r);
      } catch (err: any) { res.status(500).json({ error: err.message }); }
    },
  );

  // Phase G bug-fix: /messages/native-flow-single-select removed. The
  // previous handler called a method that never produced a Native Flow
  // dropdown — it silently degraded to a plain text message. Use the
  // existing `list` template type for section/rows menus.

  router.post(
    "/session/:id/chats/:jid/modify",
    async (req: Request, res: Response) => {
      try {
        const { action, mute_end_timestamp } = req.body || {};
        if (!["archive", "unarchive", "pin", "unpin", "mute", "unmute"].includes(action)) {
          res.status(400).json({ error: "action must be archive|unarchive|pin|unpin|mute|unmute" });
          return;
        }
        const r = await manager.chatModifyAction(
          req.params.id, req.params.jid, action, mute_end_timestamp);
        res.json(r);
      } catch (err: any) { res.status(500).json({ error: err.message }); }
    },
  );

  // ── Communities ─────────────────────────────────────────────────────
  router.get("/session/:id/communities", async (req: Request, res: Response) => {
    try {
      const r = await manager.communityFetchAllParticipating(req.params.id);
      res.json(r);
    } catch (err: any) { res.status(500).json({ error: err.message }); }
  });

  router.post("/session/:id/communities", async (req: Request, res: Response) => {
    try {
      const { subject, body } = req.body || {};
      if (!subject) { res.status(400).json({ error: "subject required" }); return; }
      const r = await manager.communityCreate(req.params.id, subject, body);
      res.json(r);
    } catch (err: any) { res.status(500).json({ error: err.message }); }
  });

  router.post(
    "/session/:id/communities/:jid/groups",
    async (req: Request, res: Response) => {
      try {
        const { subject, participants } = req.body || {};
        if (!subject || !Array.isArray(participants)) {
          res.status(400).json({ error: "subject and participants[] required" });
          return;
        }
        const r = await manager.communityCreateGroup(
          req.params.id, subject, participants, req.params.jid);
        res.json(r);
      } catch (err: any) { res.status(500).json({ error: err.message }); }
    },
  );

  router.post(
    "/session/:id/communities/:jid/leave",
    async (req: Request, res: Response) => {
      try {
        const r = await manager.communityLeave(req.params.id, req.params.jid);
        res.json(r);
      } catch (err: any) { res.status(500).json({ error: err.message }); }
    },
  );

  router.post(
    "/session/:id/communities/:jid/subject",
    async (req: Request, res: Response) => {
      try {
        const { subject } = req.body || {};
        if (typeof subject !== "string") { res.status(400).json({ error: "subject required" }); return; }
        const r = await manager.communityUpdateSubject(req.params.id, req.params.jid, subject);
        res.json(r);
      } catch (err: any) { res.status(500).json({ error: err.message }); }
    },
  );

  router.get(
    "/session/:id/communities/:jid",
    async (req: Request, res: Response) => {
      try {
        const r = await manager.communityMetadata(req.params.id, req.params.jid);
        res.json(r);
      } catch (err: any) { res.status(500).json({ error: err.message }); }
    },
  );

  router.get(
    "/session/:id/communities/:jid/groups",
    async (req: Request, res: Response) => {
      try {
        const r = await manager.communityFetchLinkedGroups(req.params.id, req.params.jid);
        res.json(r);
      } catch (err: any) { res.status(500).json({ error: err.message }); }
    },
  );

  // ── Newsletters ─────────────────────────────────────────────────────
  router.post("/session/:id/newsletters", async (req: Request, res: Response) => {
    try {
      const { name, description } = req.body || {};
      if (!name) { res.status(400).json({ error: "name required" }); return; }
      const r = await manager.newsletterCreate(req.params.id, name, description);
      res.json(r);
    } catch (err: any) { res.status(500).json({ error: err.message }); }
  });

  router.post(
    "/session/:id/newsletters/:jid/follow",
    async (req: Request, res: Response) => {
      try {
        const r = await manager.newsletterFollow(req.params.id, req.params.jid);
        res.json(r);
      } catch (err: any) { res.status(500).json({ error: err.message }); }
    },
  );

  router.post(
    "/session/:id/newsletters/:jid/unfollow",
    async (req: Request, res: Response) => {
      try {
        const r = await manager.newsletterUnfollow(req.params.id, req.params.jid);
        res.json(r);
      } catch (err: any) { res.status(500).json({ error: err.message }); }
    },
  );

  router.post(
    "/session/:id/newsletters/:jid/mute",
    async (req: Request, res: Response) => {
      try {
        const { mute } = req.body || {};
        const r = await manager.newsletterMute(req.params.id, req.params.jid, !!mute);
        res.json(r);
      } catch (err: any) { res.status(500).json({ error: err.message }); }
    },
  );

  router.post(
    "/session/:id/newsletters/:jid/update",
    async (req: Request, res: Response) => {
      try {
        const { name, description, picture_base64 } = req.body || {};
        const r = await manager.newsletterUpdate(req.params.id, req.params.jid, {
          name, description, pictureBase64: picture_base64,
        });
        res.json(r);
      } catch (err: any) { res.status(500).json({ error: err.message }); }
    },
  );

  router.get(
    "/session/:id/newsletters/:jid",
    async (req: Request, res: Response) => {
      try {
        const r = await manager.newsletterMetadata(req.params.id, req.params.jid);
        res.json(r);
      } catch (err: any) { res.status(500).json({ error: err.message }); }
    },
  );

  router.get(
    "/session/:id/newsletter-invites/:code",
    async (req: Request, res: Response) => {
      try {
        const r = await manager.newsletterMetadataByInvite(req.params.id, req.params.code);
        res.json(r);
      } catch (err: any) { res.status(500).json({ error: err.message }); }
    },
  );

  // ── V4 invite (embedded) ───────────────────────────────────────────
  router.post(
    "/session/:id/invites/v4/accept",
    async (req: Request, res: Response) => {
      try {
        const { source_jid, invite_message } = req.body || {};
        if (!source_jid || !invite_message) {
          res.status(400).json({ error: "source_jid and invite_message required" });
          return;
        }
        const r = await manager.groupAcceptInviteV4(req.params.id, source_jid, invite_message);
        res.json({ result: r });
      } catch (err: any) { res.status(500).json({ error: err.message }); }
    },
  );

  // ── Phase C2 ─────────────────────────────────────────────────────────
  router.post(
    "/session/:id/contacts/:jid/block",
    async (req: Request, res: Response) => {
      try {
        const r = await manager.updateBlockStatus(req.params.id, req.params.jid, true);
        res.json(r);
      } catch (err: any) {
        res.status(500).json({ error: err.message });
      }
    },
  );

  router.post(
    "/session/:id/contacts/:jid/unblock",
    async (req: Request, res: Response) => {
      try {
        const r = await manager.updateBlockStatus(req.params.id, req.params.jid, false);
        res.json(r);
      } catch (err: any) {
        res.status(500).json({ error: err.message });
      }
    },
  );

  router.get("/session/:id/blocklist", async (req: Request, res: Response) => {
    try {
      const r = await manager.fetchBlocklist(req.params.id);
      res.json(r);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  // ── Phase C3 ─────────────────────────────────────────────────────────
  router.post("/session/:id/profile/picture", async (req: Request, res: Response) => {
    try {
      const { image_base64 } = req.body || {};
      if (!image_base64) {
        res.status(400).json({ error: "image_base64 is required" });
        return;
      }
      const r = await manager.updateProfilePicture(req.params.id, image_base64);
      res.json(r);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  router.delete("/session/:id/profile/picture", async (req: Request, res: Response) => {
    try {
      const r = await manager.removeProfilePicture(req.params.id);
      res.json(r);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  // ── Phase B3 — subscribe to contact(s) presence (online/typing) ─────
  router.post("/session/:id/presence/subscribe", async (req: Request, res: Response) => {
    try {
      const { jid, jids } = req.body || {};
      if (jid && typeof jid === "string") {
        const r = await manager.subscribePresence(req.params.id, jid);
        res.json(r);
        return;
      }
      if (Array.isArray(jids)) {
        const r = await manager.subscribePresenceBulk(req.params.id, jids);
        res.json(r);
        return;
      }
      res.status(400).json({ error: "body must include 'jid' (string) or 'jids' (array)" });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  // ── Phase C4 ─────────────────────────────────────────────────────────
  router.post("/session/:id/presence/:jid", async (req: Request, res: Response) => {
    try {
      const { state } = req.body || {};
      const allowed = ["available", "unavailable", "composing", "recording", "paused"];
      if (!allowed.includes(state)) {
        res.status(400).json({ error: `state must be one of ${allowed.join("|")}` });
        return;
      }
      const r = await manager.sendPresenceUpdate(req.params.id, req.params.jid, state);
      res.json(r);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  // ── Phase C5 ─────────────────────────────────────────────────────────
  router.post("/session/:id/messages/star", async (req: Request, res: Response) => {
    try {
      const { jid, msg_id, from_me, star } = req.body || {};
      if (!jid || !msg_id) {
        res.status(400).json({ error: "jid and msg_id are required" });
        return;
      }
      const r = await manager.starMessage(
        req.params.id, jid, msg_id, !!from_me, star !== false,
      );
      res.json(r);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  // ── Phase C6 ─────────────────────────────────────────────────────────
  router.post("/session/:id/call-link", async (req: Request, res: Response) => {
    try {
      const { type } = req.body || {};
      if (!["audio", "video"].includes(type)) {
        res.status(400).json({ error: "type must be 'audio' or 'video'" });
        return;
      }
      const r = await manager.createCallLink(req.params.id, type);
      res.json(r);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  // ── Reject incoming WhatsApp call ────────────────────────────────────
  router.post(
    "/session/:id/calls/:callId/reject",
    async (req: Request, res: Response) => {
      try {
        const { from } = req.body || {};
        if (!from) {
          res.status(400).json({ error: "from is required" });
          return;
        }
        const r = await manager.rejectCall(req.params.id, req.params.callId, from);
        res.json(r);
      } catch (err: any) {
        res.status(500).json({ error: err.message });
      }
    },
  );

  // ── Phase D ──────────────────────────────────────────────────────────
  router.post("/session/:id/pairing-code", async (req: Request, res: Response) => {
    try {
      const { phone } = req.body || {};
      if (!phone) {
        res.status(400).json({ error: "phone is required" });
        return;
      }
      const r = await manager.requestPairingCode(req.params.id, phone);
      res.json(r);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  return router;
}
