export interface UsageSnapshot {
  period: string;
  safetyMarginPercent: number;
  providers: {
    llm: { id: string; label: string; model: string; configured: boolean };
    stt: { id: 'azure'; configured: boolean; region?: string; maxSessionSeconds?: number };
    tts: { id: 'google-chirp-3-hd'; configured: boolean; language?: string; voice?: string };
  };
  stt: {
    usedSeconds: number;
    freeLimitSeconds: number;
    enforcedLimitSeconds: number;
    remainingSeconds: number;
    percentage: number;
    available: boolean;
  };
  tts: {
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

export async function fetchUsageSnapshot(): Promise<UsageSnapshot> {
  const response = await fetch('/api/usage', { cache: 'no-store' });
  const data = await response.json().catch(() => null);

  if (!response.ok || !data) {
    throw new Error(data?.error || 'No se ha podido cargar el control de uso.');
  }

  return data as UsageSnapshot;
}
