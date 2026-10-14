import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';

interface UsagePeriod {
  azureSttSeconds: number;
  googleTtsCharacters: number;
  llmInputTokens: number;
  llmOutputTokens: number;
  llmEstimatedCostUsd: number;
}

interface UsageFile {
  periods: Record<string, UsagePeriod>;
}

export interface UsageSnapshot {
  period: string;
  safetyMarginPercent: number;
  stt: {
    provider: 'azure';
    usedSeconds: number;
    freeLimitSeconds: number;
    enforcedLimitSeconds: number;
    remainingSeconds: number;
    percentage: number;
    available: boolean;
  };
  tts: {
    provider: 'google-chirp-3-hd';
    usedCharacters: number;
    freeLimitCharacters: number;
    enforcedLimitCharacters: number;
    remainingCharacters: number;
    percentage: number;
    available: boolean;
  };
  llm: {
    inputTokens: number;
    outputTokens: number;
    estimatedCostUsd: number;
    referenceCreditUsd: number;
    percentageOfReference: number;
  };
}

const DEFAULT_PERIOD: UsagePeriod = {
  azureSttSeconds: 0,
  googleTtsCharacters: 0,
  llmInputTokens: 0,
  llmOutputTokens: 0,
  llmEstimatedCostUsd: 0,
};

function currentPeriod(): string {
  const now = new Date();
  const year = now.getUTCFullYear();
  const month = String(now.getUTCMonth() + 1).padStart(2, '0');
  return `${year}-${month}`;
}

function clampPercentage(value: number): number {
  return Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
}

export class UsageManager {
  private readonly filePath: string;
  private readonly azureFreeSeconds: number;
  private readonly googleFreeCharacters: number;
  private readonly safetyMarginPercent: number;
  private readonly llmInputUsdPerMillion: number;
  private readonly llmOutputUsdPerMillion: number;
  private readonly llmReferenceCreditUsd: number;
  private writeQueue: Promise<void> = Promise.resolve();

  constructor() {
    this.filePath = resolve(process.env.USAGE_DATA_FILE?.trim() || './data/usage.json');
    this.azureFreeSeconds = Number(process.env.AZURE_STT_FREE_SECONDS || 18_000);
    this.googleFreeCharacters = Number(process.env.GOOGLE_TTS_FREE_CHARACTERS || 1_000_000);
    this.safetyMarginPercent = Number(process.env.USAGE_SAFETY_PERCENT || 98);
    this.llmInputUsdPerMillion = Number(process.env.LLM_INPUT_USD_PER_M || 0.10);
    this.llmOutputUsdPerMillion = Number(process.env.LLM_OUTPUT_USD_PER_M || 0.50);
    this.llmReferenceCreditUsd = Number(process.env.LLM_REFERENCE_CREDIT_USD || 5);
  }

  private async load(): Promise<UsageFile> {
    try {
      const raw = await readFile(this.filePath, 'utf8');
      const parsed = JSON.parse(raw) as UsageFile;
      return parsed && parsed.periods ? parsed : { periods: {} };
    } catch (error: any) {
      if (error?.code === 'ENOENT') return { periods: {} };
      console.warn('No se pudo leer el fichero de uso. Se parte de cero:', error?.message || error);
      return { periods: {} };
    }
  }

  private async save(data: UsageFile): Promise<void> {
    await mkdir(dirname(this.filePath), { recursive: true });
    await writeFile(this.filePath, `${JSON.stringify(data, null, 2)}\n`, 'utf8');
  }

  private normalizePeriod(value?: Partial<UsagePeriod>): UsagePeriod {
    return {
      azureSttSeconds: Number(value?.azureSttSeconds) || 0,
      googleTtsCharacters: Number(value?.googleTtsCharacters) || 0,
      llmInputTokens: Number(value?.llmInputTokens) || 0,
      llmOutputTokens: Number(value?.llmOutputTokens) || 0,
      llmEstimatedCostUsd: Number(value?.llmEstimatedCostUsd) || 0,
    };
  }

  private async mutate(mutator: (period: UsagePeriod) => void): Promise<void> {
    this.writeQueue = this.writeQueue.then(async () => {
      const data = await this.load();
      const key = currentPeriod();
      const period = this.normalizePeriod(data.periods[key] || DEFAULT_PERIOD);
      mutator(period);
      data.periods[key] = period;
      await this.save(data);
    });

    return this.writeQueue;
  }

  async canUseSttSeconds(additionalSeconds = 0): Promise<boolean> {
    const snapshot = await this.getSnapshot();
    const requested = Math.max(0, Number(additionalSeconds) || 0);
    return snapshot.stt.remainingSeconds >= requested && snapshot.stt.available;
  }

  async canUseTtsCharacters(characters: number): Promise<boolean> {
    const snapshot = await this.getSnapshot();
    const requested = Math.max(0, Math.floor(Number(characters) || 0));
    return snapshot.tts.remainingCharacters >= requested && snapshot.tts.available;
  }

  async recordLlmUsage(inputTokens: number, outputTokens: number): Promise<void> {
    const safeInput = Math.max(0, Number(inputTokens) || 0);
    const safeOutput = Math.max(0, Number(outputTokens) || 0);
    const estimatedCost =
      (safeInput / 1_000_000) * this.llmInputUsdPerMillion +
      (safeOutput / 1_000_000) * this.llmOutputUsdPerMillion;

    await this.mutate((period) => {
      period.llmInputTokens += safeInput;
      period.llmOutputTokens += safeOutput;
      period.llmEstimatedCostUsd += estimatedCost;
    });
  }

  async recordSttSeconds(seconds: number): Promise<void> {
    const safeSeconds = Math.max(0, Number(seconds) || 0);
    await this.mutate((period) => {
      period.azureSttSeconds += safeSeconds;
    });
  }

  async recordTtsCharacters(characters: number): Promise<void> {
    const safeCharacters = Math.max(0, Math.floor(Number(characters) || 0));
    await this.mutate((period) => {
      period.googleTtsCharacters += safeCharacters;
    });
  }

  async getSnapshot(): Promise<UsageSnapshot> {
    await this.writeQueue;
    const data = await this.load();
    const periodKey = currentPeriod();
    const period = this.normalizePeriod(data.periods[periodKey] || DEFAULT_PERIOD);

    const marginRatio = Math.max(0, Math.min(1, this.safetyMarginPercent / 100));
    const sttEnforced = Math.floor(this.azureFreeSeconds * marginRatio);
    const ttsEnforced = Math.floor(this.googleFreeCharacters * marginRatio);
    const sttRemaining = Math.max(0, sttEnforced - period.azureSttSeconds);
    const ttsRemaining = Math.max(0, ttsEnforced - period.googleTtsCharacters);

    return {
      period: periodKey,
      safetyMarginPercent: this.safetyMarginPercent,
      stt: {
        provider: 'azure',
        usedSeconds: period.azureSttSeconds,
        freeLimitSeconds: this.azureFreeSeconds,
        enforcedLimitSeconds: sttEnforced,
        remainingSeconds: sttRemaining,
        percentage: clampPercentage((period.azureSttSeconds / Math.max(1, sttEnforced)) * 100),
        available: sttRemaining > 0,
      },
      tts: {
        provider: 'google-chirp-3-hd',
        usedCharacters: period.googleTtsCharacters,
        freeLimitCharacters: this.googleFreeCharacters,
        enforcedLimitCharacters: ttsEnforced,
        remainingCharacters: ttsRemaining,
        percentage: clampPercentage((period.googleTtsCharacters / Math.max(1, ttsEnforced)) * 100),
        available: ttsRemaining > 0,
      },
      llm: {
        inputTokens: period.llmInputTokens,
        outputTokens: period.llmOutputTokens,
        estimatedCostUsd: period.llmEstimatedCostUsd,
        referenceCreditUsd: this.llmReferenceCreditUsd,
        percentageOfReference: clampPercentage(
          (period.llmEstimatedCostUsd / Math.max(0.000001, this.llmReferenceCreditUsd)) * 100,
        ),
      },
    };
  }
}
