export type PronunciationAssessmentMode = 'off' | 'basic';

export interface PronunciationPhonemeFeedback {
  phoneme: string;
  accuracyScore: number;
}

export interface PronunciationWordFeedback {
  word: string;
  accuracyScore: number;
  errorType?: string;
  phonemes: PronunciationPhonemeFeedback[];
}

export interface PronunciationSegmentAssessment {
  text: string;
  accuracyScore: number;
  fluencyScore: number;
  pronunciationScore: number;
  words: PronunciationWordFeedback[];
}

export interface PronunciationAssessmentSummary {
  text: string;
  accuracyScore: number;
  fluencyScore: number;
  pronunciationScore: number;
  weakWords: PronunciationWordFeedback[];
  assessedAt: string;
}

export interface PronunciationWeakWordMemory {
  word: string;
  normalizedWord: string;
  attempts: number;
  weakAttempts: number;
  averageAccuracy: number;
  lastAccuracy: number;
  weakestPhonemes: PronunciationPhonemeFeedback[];
  lastSeenAt: string;
}

export interface PronunciationMemorySnapshot {
  languageId: string;
  assessmentCount: number;
  averageAccuracy: number;
  averageFluency: number;
  averagePronunciation: number;
  weakWords: PronunciationWeakWordMemory[];
  latestAssessment?: PronunciationAssessmentSummary;
  updatedAt?: string;
}
