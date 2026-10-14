import { createSign } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { UsageManager } from '../../usage/usageManager.ts';

interface ServiceAccountCredentials {
  type?: string;
  project_id?: string;
  private_key?: string;
  client_email?: string;
  token_uri?: string;
}

interface CachedToken {
  value: string;
  expiresAtMs: number;
}

export interface GoogleChirpSynthesisResult {
  audio: Buffer;
  contentType: 'audio/mpeg';
  characters: number;
  voice: string;
  language: string;
}

function base64Url(input: string | Buffer): string {
  return Buffer.from(input)
    .toString('base64')
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_');
}

function countCharacters(text: string): number {
  return Array.from(text).length;
}

function validateLocale(value: string): boolean {
  return /^[a-z]{2,3}(?:-[A-Z]{2})?$/.test(value);
}

function validateVoice(value: string): boolean {
  return /^[A-Za-z0-9-]{3,100}$/.test(value);
}

export class GoogleChirpService {
  private readonly credentialsPath: string;
  private readonly projectId: string;
  private readonly defaultLanguage: string;
  private readonly defaultVoice: string;
  private readonly usageManager: UsageManager;
  private credentialsCache: ServiceAccountCredentials | null = null;
  private tokenCache: CachedToken | null = null;

  constructor(usageManager: UsageManager) {
    this.usageManager = usageManager;
    this.credentialsPath = resolve(process.env.GOOGLE_APPLICATION_CREDENTIALS?.trim() || '');
    this.projectId = process.env.GOOGLE_CLOUD_PROJECT?.trim() || '';
    this.defaultLanguage = process.env.GOOGLE_TTS_LANGUAGE?.trim() || 'en-US';
    this.defaultVoice = process.env.GOOGLE_TTS_VOICE?.trim() || 'en-US-Chirp3-HD-Charon';
  }

  get configured(): boolean {
    return Boolean(process.env.GOOGLE_APPLICATION_CREDENTIALS?.trim() && this.projectId);
  }

  get language(): string {
    return this.defaultLanguage;
  }

  get voice(): string {
    return this.defaultVoice;
  }

  private async loadCredentials(): Promise<ServiceAccountCredentials> {
    if (!this.configured) throw new Error('GOOGLE_TTS_NOT_CONFIGURED');
    if (this.credentialsCache) return this.credentialsCache;

    try {
      const raw = await readFile(this.credentialsPath, 'utf8');
      const parsed = JSON.parse(raw) as ServiceAccountCredentials;
      if (
        parsed.type !== 'service_account' ||
        !parsed.client_email ||
        !parsed.private_key ||
        !parsed.token_uri
      ) {
        throw new Error('GOOGLE_CREDENTIALS_INVALID');
      }
      if (parsed.project_id && parsed.project_id !== this.projectId) {
        console.warn(
          `GOOGLE_CLOUD_PROJECT (${this.projectId}) no coincide con project_id de la service account (${parsed.project_id}).`,
        );
      }
      this.credentialsCache = parsed;
      return parsed;
    } catch (error) {
      if (error instanceof Error && error.message === 'GOOGLE_CREDENTIALS_INVALID') throw error;
      console.error('No se pudo leer GOOGLE_APPLICATION_CREDENTIALS:', error);
      throw new Error('GOOGLE_CREDENTIALS_INVALID');
    }
  }

  private async getAccessToken(): Promise<string> {
    const now = Date.now();
    if (this.tokenCache && this.tokenCache.expiresAtMs - now > 5 * 60 * 1000) {
      return this.tokenCache.value;
    }

    const credentials = await this.loadCredentials();
    const issuedAt = Math.floor(now / 1000);
    const expiresAt = issuedAt + 3600;
    const header = base64Url(JSON.stringify({ alg: 'RS256', typ: 'JWT' }));
    const payload = base64Url(
      JSON.stringify({
        iss: credentials.client_email,
        scope: 'https://www.googleapis.com/auth/cloud-platform',
        aud: credentials.token_uri,
        iat: issuedAt,
        exp: expiresAt,
      }),
    );
    const unsigned = `${header}.${payload}`;
    const signer = createSign('RSA-SHA256');
    signer.update(unsigned);
    signer.end();
    const signature = base64Url(signer.sign(credentials.private_key!));
    const assertion = `${unsigned}.${signature}`;

    const response = await fetch(credentials.token_uri!, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
        assertion,
      }),
    });

    const data = (await response.json().catch(() => ({}))) as {
      access_token?: string;
      expires_in?: number;
      error?: string;
      error_description?: string;
    };

    if (!response.ok || !data.access_token) {
      console.error('Google OAuth error:', response.status, data.error, data.error_description);
      throw new Error('GOOGLE_AUTH_FAILED');
    }

    const expiresInSeconds = Math.max(300, Number(data.expires_in) || 3600);
    this.tokenCache = {
      value: data.access_token,
      expiresAtMs: now + expiresInSeconds * 1000,
    };
    return data.access_token;
  }

  async synthesize(
    text: string,
    options?: { language?: string; voice?: string },
  ): Promise<GoogleChirpSynthesisResult> {
    if (!this.configured) throw new Error('GOOGLE_TTS_NOT_CONFIGURED');

    const cleanText = text.trim();
    if (!cleanText) throw new Error('TTS_TEXT_REQUIRED');
    if (cleanText.length > 4500) throw new Error('TTS_TEXT_TOO_LONG');

    const characters = countCharacters(cleanText);
    if (!(await this.usageManager.canUseTtsCharacters(characters))) {
      throw new Error('TTS_QUOTA_EXHAUSTED');
    }

    const language = options?.language?.trim() || this.defaultLanguage;
    const voice = options?.voice?.trim() || this.defaultVoice;
    if (!validateLocale(language) || !validateVoice(voice)) throw new Error('TTS_OPTIONS_INVALID');

    const token = await this.getAccessToken();
    const response = await fetch('https://texttospeech.googleapis.com/v1/text:synthesize', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        input: { text: cleanText },
        voice: {
          languageCode: language,
          name: voice,
        },
        audioConfig: {
          audioEncoding: 'MP3',
        },
      }),
    });

    const data = (await response.json().catch(() => ({}))) as {
      audioContent?: string;
      error?: { message?: string; status?: string; code?: number };
    };

    if (!response.ok || !data.audioContent) {
      console.error('Google TTS error:', response.status, data.error?.status, data.error?.message);
      const detail = data.error?.message?.slice(0, 300) || `HTTP ${response.status}`;
      throw new Error(`GOOGLE_TTS_FAILED:${detail}`);
    }

    const audio = Buffer.from(data.audioContent, 'base64');
    if (audio.length === 0) throw new Error('GOOGLE_TTS_EMPTY_AUDIO');

    // Solo contabilizamos texto que Google ha sintetizado correctamente.
    await this.usageManager.recordTtsCharacters(characters);

    return {
      audio,
      contentType: 'audio/mpeg',
      characters,
      voice,
      language,
    };
  }
}
