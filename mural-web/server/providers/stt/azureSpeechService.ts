import { randomUUID } from 'node:crypto';
import type { UsageManager } from '../../usage/usageManager.ts';

interface ActiveSession {
  id: string;
  startedAtMs: number;
  maxSeconds: number;
}

interface FinishedSession {
  recordedSeconds: number;
  finishedAtMs: number;
}

export interface AzureSttSessionStart {
  sessionId: string;
  token: string;
  region: string;
  maxSessionSeconds: number;
  remainingSeconds: number;
}

export interface AzureSttSessionFinish {
  sessionId: string;
  recordedSeconds: number;
}

const TOKEN_ENDPOINT_SUFFIX = '.api.cognitive.microsoft.com/sts/v1.0/issueToken';

export class AzureSpeechService {
  readonly region: string;
  readonly configured: boolean;
  readonly maxSessionSeconds: number;

  private readonly primaryKey: string;
  private readonly fallbackKey: string;
  private readonly usageManager: UsageManager;
  private activeSession: ActiveSession | null = null;
  private readonly finishedSessions = new Map<string, FinishedSession>();

  constructor(usageManager: UsageManager) {
    this.usageManager = usageManager;
    this.primaryKey = process.env.AZURE_SPEECH_KEY?.trim() || '';
    this.fallbackKey = process.env.AZURE_SPEECH_FALLBACK_KEY?.trim() || '';
    this.region = process.env.AZURE_SPEECH_REGION?.trim().toLowerCase() || '';
    this.maxSessionSeconds = Math.max(10, Math.min(540, Number(process.env.AZURE_STT_MAX_SESSION_SECONDS || 300)));
    this.configured = Boolean(this.primaryKey && this.region);
  }

  private assertRegion(): void {
    if (!/^[a-z0-9-]+$/.test(this.region)) {
      throw new Error('AZURE_REGION_INVALID');
    }
  }

  private async issueTokenWithKey(key: string): Promise<string> {
    this.assertRegion();
    const response = await fetch(`https://${this.region}${TOKEN_ENDPOINT_SUFFIX}`, {
      method: 'POST',
      headers: {
        'Ocp-Apim-Subscription-Key': key,
        'Content-Type': 'application/x-www-form-urlencoded',
        'Content-Length': '0',
      },
    });

    const text = await response.text();
    if (!response.ok || !text.trim()) {
      throw new Error(`AZURE_TOKEN_FAILED:${response.status}:${text.slice(0, 180)}`);
    }

    return text.trim();
  }

  private async issueToken(): Promise<string> {
    if (!this.configured) throw new Error('AZURE_NOT_CONFIGURED');

    try {
      return await this.issueTokenWithKey(this.primaryKey);
    } catch (primaryError) {
      if (!this.fallbackKey || this.fallbackKey === this.primaryKey) throw primaryError;
      return this.issueTokenWithKey(this.fallbackKey);
    }
  }

  private cleanupFinishedSessions(): void {
    const cutoff = Date.now() - 10 * 60 * 1000;
    for (const [id, session] of this.finishedSessions.entries()) {
      if (session.finishedAtMs < cutoff) this.finishedSessions.delete(id);
    }
  }

  private async settleExpiredSession(): Promise<void> {
    if (!this.activeSession) return;

    const expiresAt = this.activeSession.startedAtMs + (this.activeSession.maxSeconds + 30) * 1000;
    if (Date.now() < expiresAt) return;

    // Si el navegador desaparece sin poder cerrar la sesión, contamos el máximo reservado.
    // Es deliberadamente conservador: prioriza no sobrepasar la cuota gratuita.
    const stale = this.activeSession;
    this.activeSession = null;
    await this.usageManager.recordSttSeconds(stale.maxSeconds);
    this.finishedSessions.set(stale.id, {
      recordedSeconds: stale.maxSeconds,
      finishedAtMs: Date.now(),
    });
  }

  async startSession(): Promise<AzureSttSessionStart> {
    if (!this.configured) throw new Error('AZURE_NOT_CONFIGURED');

    this.cleanupFinishedSessions();
    await this.settleExpiredSession();

    if (this.activeSession) throw new Error('STT_SESSION_ALREADY_ACTIVE');

    const snapshot = await this.usageManager.getSnapshot();
    if (!snapshot.stt.available || snapshot.stt.remainingSeconds < 1) {
      throw new Error('STT_QUOTA_EXHAUSTED');
    }

    const maxSessionSeconds = Math.max(1, Math.min(this.maxSessionSeconds, Math.floor(snapshot.stt.remainingSeconds)));
    const token = await this.issueToken();
    const sessionId = randomUUID();

    this.activeSession = {
      id: sessionId,
      startedAtMs: Date.now(),
      maxSeconds: maxSessionSeconds,
    };

    return {
      sessionId,
      token,
      region: this.region,
      maxSessionSeconds,
      remainingSeconds: snapshot.stt.remainingSeconds,
    };
  }

  async finishSession(sessionId: string): Promise<AzureSttSessionFinish> {
    this.cleanupFinishedSessions();

    const alreadyFinished = this.finishedSessions.get(sessionId);
    if (alreadyFinished) {
      return { sessionId, recordedSeconds: alreadyFinished.recordedSeconds };
    }

    if (!this.activeSession || this.activeSession.id !== sessionId) {
      throw new Error('STT_SESSION_NOT_FOUND');
    }

    const session = this.activeSession;
    this.activeSession = null;

    const elapsedSeconds = Math.ceil((Date.now() - session.startedAtMs) / 1000);
    const recordedSeconds = Math.min(session.maxSeconds, Math.max(1, elapsedSeconds));

    await this.usageManager.recordSttSeconds(recordedSeconds);
    this.finishedSessions.set(session.id, {
      recordedSeconds,
      finishedAtMs: Date.now(),
    });

    return { sessionId: session.id, recordedSeconds };
  }
}
