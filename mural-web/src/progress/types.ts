import type { LearningCategory, LearningEvidenceItem, VocabularyMemoryItem } from '../learning/types';
import type { PronunciationWeakWordMemory } from '../pronunciation/types';

export interface DailyProgressRecord {
  id: string;
  languageId: string;
  date: string;
  turns: number;
  voiceTurns: number;
  keyboardTurns: number;
  userWords: number;
  assistantWords: number;
  sessionsStarted: number;
  themeTurns: Record<string, number>;
  updatedAt: string;
}

export interface ProgressActivitySnapshot {
  daily: DailyProgressRecord[];
}

export interface ProgressDay {
  date: string;
  label: string;
  turns: number;
  words: number;
}

export interface ProgressOverview {
  last7Days: {
    turns: number;
    voiceTurns: number;
    keyboardTurns: number;
    userWords: number;
    assistantWords: number;
    sessionsStarted: number;
    activeDays: number;
    themesPracticed: number;
    days: ProgressDay[];
  };
  retained: {
    turns: number;
    activeDays: number;
    sessionsStarted: number;
  };
  streakDays: number;
  vocabulary: {
    total: number;
    mastered: number;
    review: number;
    introduced: number;
    topReview: VocabularyMemoryItem[];
  };
  skills: {
    total: number;
    strengths: number;
    review: number;
    categories: Record<LearningCategory, { strengths: number; review: number }>;
    topReview: LearningEvidenceItem[];
    topStrengths: LearningEvidenceItem[];
  };
  pronunciation: {
    assessmentCount: number;
    averageAccuracy: number;
    averageFluency: number;
    averagePronunciation: number;
    weakWords: PronunciationWeakWordMemory[];
  };
}
