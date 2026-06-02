import { Router, type Request, type Response } from "express";
import type { SessionManager } from "../services/session-manager.js";

export function createHealthRoutes(manager: SessionManager): Router {
  const router = Router();

  router.get("/health", (_req: Request, res: Response) => {
    res.json(manager.getHealthStatus());
  });

  return router;
}
