import type { PronunciationAssessmentMode, PronunciationSegmentAssessment } from '../pronunciation/types';

export type SttProviderId = 'azure';
export type TtsProviderId = 'google-chirp-3-hd';

export type SttMode = 'auto' | 'azure' | 'text';
export type VoiceSubmitMode = 'auto' | 'manual';
export type TtsMode = 'auto' | 'google' | 'text';
export type ResponseDisplayMode = 'auto' | 'listening' | 'reading' | 'mixed';
export type SttStopReason = 'manual' | 'limit' | 'service' | 'error';

export interface VoicePreferences {
  sttMode: SttMode;
  voiceSubmitMode: VoiceSubmitMode;
  ttsMode: TtsMode;
  responseDisplayMode: ResponseDisplayMode;
  pronunciationAssessmentMode: PronunciationAssessmentMode;
}

export interface SttSessionOptions {
  language: string;
  pronunciationAssessmentMode?: PronunciationAssessmentMode;
  phraseHints?: string[];
}

export interface SttProvider {
  readonly id: SttProviderId;
  start(options: SttSessionOptions): Promise<void>;
  stop(): Promise<void>;
  onPartialTranscript(callback: (text: string) => void): () => void;
  onFinalTranscript(callback: (text: string) => void): () => void;
  onPronunciationAssessment(callback: (assessment: PronunciationSegmentAssessment) => void): () => void;
  onError(callback: (message: string) => void): () => void;
  onStopped(callback: (reason: SttStopReason) => void): () => void;
}

export interface TtsSynthesisOptions {
  language: string;
  voice?: string;
  speed?: number;
}

export interface SynthesizedAudio {
  blob: Blob;
  characters: number;
  voice?: string;
  language?: string;
}

export interface TtsProvider {
  readonly id: TtsProviderId;
  synthesize(text: string, options: TtsSynthesisOptions): Promise<SynthesizedAudio>;
  play(audio: SynthesizedAudio): Promise<void>;
  stop(): void;
}
