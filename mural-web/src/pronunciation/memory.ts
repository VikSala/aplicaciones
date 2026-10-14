import type {
  PronunciationAssessmentSummary,
  PronunciationMemorySnapshot,
  PronunciationSegmentAssessment,
  PronunciationWordFeedback,
} from './types';

const MISPRONUNCIATION_THRESHOLD = 60;
const MAX_WEAK_WORDS_PER_ASSESSMENT = 8;

function finiteScore(value: number | undefined): number | null {
  if (!Number.isFinite(value)) return null;
  return Math.max(0, Math.min(100, Number(value)));
}

function weightedAverage(
  segments: PronunciationSegmentAssessment[],
  selector: (segment: PronunciationSegmentAssessment) => number,
): number {
  let weighted = 0;
  let totalWeight = 0;

  for (const segment of segments) {
    const score = finiteScore(selector(segment));
    if (score === null) continue;
    const weight = Math.max(1, segment.text.trim().split(/\s+/).filter(Boolean).length);
    weighted += score * weight;
    totalWeight += weight;
  }

  return totalWeight > 0 ? weighted / totalWeight : 0;
}

function weakWordKey(word: PronunciationWordFeedback): string {
  return word.word.trim().toLocaleLowerCase('en-US');
}

function mergeWeakWords(segments: PronunciationSegmentAssessment[]): PronunciationWordFeedback[] {
  const byWord = new Map<string, PronunciationWordFeedback>();

  for (const segment of segments) {
    for (const word of segment.words) {
      const accuracy = finiteScore(word.accuracyScore);
      if (accuracy === null) continue;
      const explicitMispronunciation = word.errorType?.toLowerCase() === 'mispronunciation';
      if (!explicitMispronunciation && accuracy >= MISPRONUNCIATION_THRESHOLD) continue;

      const key = weakWordKey(word);
      if (!key) continue;
      const current = byWord.get(key);
      if (!current || accuracy < current.accuracyScore) {
        byWord.set(key, {
          ...word,
          accuracyScore: accuracy,
          phonemes: [...word.phonemes]
            .filter((phoneme) => finiteScore(phoneme.accuracyScore) !== null)
            .sort((a, b) => a.accuracyScore - b.accuracyScore)
            .slice(0, 3),
        });
      }
    }
  }

  return [...byWord.values()]
    .sort((a, b) => a.accuracyScore - b.accuracyScore)
    .slice(0, MAX_WEAK_WORDS_PER_ASSESSMENT);
}

export function summarizePronunciationSegments(
  segments: PronunciationSegmentAssessment[],
): PronunciationAssessmentSummary | null {
  const useful = segments.filter((segment) => segment.text.trim());
  if (useful.length === 0) return null;

  const text = useful.map((segment) => segment.text.trim()).filter(Boolean).join(' ').replace(/\s+/g, ' ').trim();
  if (!text) return null;

  return {
    text,
    accuracyScore: weightedAverage(useful, (segment) => segment.accuracyScore),
    fluencyScore: weightedAverage(useful, (segment) => segment.fluencyScore),
    pronunciationScore: weightedAverage(useful, (segment) => segment.pronunciationScore),
    weakWords: mergeWeakWords(useful),
    assessedAt: new Date().toISOString(),
  };
}

export function emptyPronunciationMemory(languageId: string): PronunciationMemorySnapshot {
  return {
    languageId,
    assessmentCount: 0,
    averageAccuracy: 0,
    averageFluency: 0,
    averagePronunciation: 0,
    weakWords: [],
  };
}

export function buildPronunciationContext(memory: PronunciationMemorySnapshot): string {
  if (!memory.assessmentCount || memory.weakWords.length === 0) return '';

  const repeatedWeakWords = [...memory.weakWords]
    .filter((word) => word.weakAttempts >= 2 || word.lastAccuracy < MISPRONUNCIATION_THRESHOLD)
    .sort((a, b) => {
      const aPriority = a.weakAttempts * 10 - a.averageAccuracy;
      const bPriority = b.weakAttempts * 10 - b.averageAccuracy;
      return bPriority - aPriority;
    })
    .slice(0, 6);

  if (repeatedWeakWords.length === 0) return '';

  return [
    'Pronunciación a reciclar con discreción (datos de Azure Speech):',
    ...repeatedWeakWords.map((item) => {
      const phonemes = item.weakestPhonemes.length
        ? `; fonemas a vigilar: ${item.weakestPhonemes.map((phoneme) => phoneme.phoneme).join(', ')}`
        : '';
      return `- ${item.word}: precisión media ${Math.round(item.averageAccuracy)}/100, ${item.weakAttempts} intento(s) débil(es)${phonemes}`;
    }),
    'Reutiliza estas palabras de forma natural cuando encajen. No menciones puntuaciones salvo que el usuario pregunte explícitamente por pronunciación.',
  ].join('\n').slice(0, 1800);
}
