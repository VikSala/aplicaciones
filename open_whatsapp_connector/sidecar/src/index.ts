import express from "express";
import pino from "pino";
import { SessionManager } from "./services/session-manager.js";
import { createSessionRoutes } from "./routes/session.js";
import { createSendRoutes } from "./routes/send.js";
import { createHealthRoutes } from "./routes/health.js";
import { createWhatsappRoutes } from "./routes/whatsapp.js";

const logger = pino({ level: process.env.LOG_LEVEL || "info" });
const PORT = parseInt(process.env.PORT || "3100", 10);
const API_KEY = process.env.API_KEY || "";
const SESSIONS_DIR = process.env.SESSIONS_DIR || undefined;

const app = express();
app.use(express.json({ limit: "50mb" })); // Large limit for media base64

// API key middleware
if (API_KEY) {
  app.use((req, res, next) => {
    if (req.path === "/health") return next();
    const key = req.headers["x-api-key"];
    if (key !== API_KEY) {
      res.status(401).json({ error: "Invalid API key" });
      return;
    }
    next();
  });
}

const manager = new SessionManager(SESSIONS_DIR);

app.use(createHealthRoutes(manager));
app.use(createSessionRoutes(manager));
app.use(createSendRoutes(manager));
app.use(createWhatsappRoutes(manager));

app.listen(PORT, async () => {
  logger.info({ port: PORT }, "WhatsApp Baileys sidecar started");
  await manager.restoreSessions();
});
