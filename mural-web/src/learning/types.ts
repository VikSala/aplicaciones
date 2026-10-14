export type LearningStatus = 'correct' | 'needs_work' | 'introduced';
export type LearningCategory = 'grammar' | 'vocabulary' | 'usage' | 'spelling';

export interface VocabularyObservation {
  term: string;
  status: LearningStatus;
  meaningEs?: string;
  confidence?: number;
}

export interface SkillObservation {
  category: LearningCategory;
  key: string;
  label: string;
  status: Exclude<LearningStatus, 'introduced'>;
  correction?: string;
  note?: string;
  confidence?: number;
}

export interface TurnLearningAnalysis {
  vocabulary: VocabularyObservation[];
  skills: SkillObservation[];
}

export interface VocabularyMemoryItem {
  id: string;
  languageId: string;
  term: string;
  normalizedTerm: string;
  meaningEs?: string;
  correctUses: number;
  needsWorkUses: number;
  introducedCount: number;
  lastSeenAt: string;
}

export interface LearningEvidenceExample {
  text: string;
  status: 'correct' | 'needs_work';
  at: string;
}

export interface LearningEvidenceItem {
  id: string;
  languageId: string;
  category: LearningCategory;
  key: string;
  label: string;
  correctCount: number;
  needsWorkCount: number;
  correction?: string;
  note?: string;
  recentExamples: LearningEvidenceExample[];
  lastSeenAt: string;
}

export interface LearningMemorySnapshot {
  vocabulary: VocabularyMemoryItem[];
  evidence: LearningEvidenceItem[];
}
