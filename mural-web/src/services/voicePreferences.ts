import type { VoicePreferences } from '../voice/types';

const STORAGE_KEY = 'mural-web.voice-preferences.v1';

export const DEFAULT_VOICE_PREFERENCES: VoicePreferences = {
  sttMode: 'auto',
  voiceSubmitMode: 'manual',
  ttsMode: 'auto',
  responseDisplayMode: 'auto',
  pronunciationAssessmentMode: 'basic',
};

export function normalizeVoicePreferences(value: Partial<VoicePreferences> | null | undefined): VoicePreferences {
  const parsed = value ?? {};
  return {
    sttMode: parsed.sttMode === 'azure' || parsed.sttMode === 'text' ? parsed.sttMode : 'auto',
    voiceSubmitMode: parsed.voiceSubmitMode === 'auto' ? 'auto' : 'manual',
    ttsMode: parsed.ttsMode === 'google' || parsed.ttsMode === 'text' ? parsed.ttsMode : 'auto',
    responseDisplayMode:
      parsed.responseDisplayMode === 'listening' ||
      parsed.responseDisplayMode === 'reading' ||
      parsed.responseDisplayMode === 'mixed'
        ? parsed.responseDisplayMode
        : 'auto',
    pronunciationAssessmentMode: parsed.pronunciationAssessmentMode === 'off' ? 'off' : 'basic',
  };
}

export function loadVoicePreferences(): VoicePreferences {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_VOICE_PREFERENCES;
    return normalizeVoicePreferences(JSON.parse(raw) as Partial<VoicePreferences>);
  } catch {
    return DEFAULT_VOICE_PREFERENCES;
  }
}

export function saveVoicePreferences(preferences: VoicePreferences): void {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
}
