import type { LearningMemorySnapshot, LearningCategory } from '../learning/types';
import type { PronunciationMemorySnapshot } from '../pronunciation/types';
import type { DailyProgressRecord, ProgressActivitySnapshot, ProgressOverview } from './types';

export function countWords(text: string): number {
  return text.trim().split(/\s+/u).filter(Boolean).length;
}

function localDateKey(date = new Date()): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function dateFromKey(key: string): Date {
  const [year, month, day] = key.split('-').map(Number);
  return new Date(year, Math.max(0, month - 1), day, 12, 0, 0, 0);
}

function shiftDateKey(key: string, days: number): string {
  const date = dateFromKey(key);
  date.setDate(date.getDate() + days);
  return localDateKey(date);
}

function dayLabel(key: string): string {
  return new Intl.DateTimeFormat('es-ES', { weekday: 'short' })
    .format(dateFromKey(key))
    .replace('.', '')
    .slice(0, 3);
}

function aggregate(records: DailyProgressRecord[]) {
  return records.reduce(
    (total, item) => ({
      turns: total.turns + item.turns,
      voiceTurns: total.voiceTurns + item.voiceTurns,
      keyboardTurns: total.keyboardTurns + item.keyboardTurns,
      userWords: total.userWords + item.userWords,
      assistantWords: total.assistantWords + item.assistantWords,
      sessionsStarted: total.sessionsStarted + item.sessionsStarted,
    }),
    { turns: 0, voiceTurns: 0, keyboardTurns: 0, userWords: 0, assistantWords: 0, sessionsStarted: 0 },
  );
}

function calculateStreak(records: DailyProgressRecord[]): number {
  const active = new Set(records.filter((item) => item.turns > 0).map((item) => item.date));
  if (active.size === 0) return 0;

  const today = localDateKey();
  let cursor = active.has(today) ? today : shiftDateKey(today, -1);
  if (!active.has(cursor)) return 0;

  let streak = 0;
  while (active.has(cursor)) {
    streak += 1;
    cursor = shiftDateKey(cursor, -1);
  }
  return streak;
}

function vocabularyPriority(item: LearningMemorySnapshot['vocabulary'][number]): number {
  return item.needsWorkUses * 4 + item.introducedCount - item.correctUses;
}

function skillPriority(item: LearningMemorySnapshot['evidence'][number]): number {
  return item.needsWorkCount * 4 - item.correctCount;
}

export function buildProgressOverview(
  activity: ProgressActivitySnapshot,
  learning: LearningMemorySnapshot,
  pronunciation: PronunciationMemorySnapshot,
): ProgressOverview {
  const byDate = new Map(activity.daily.map((item) => [item.date, item]));
  const today = localDateKey();
  const last7Keys = Array.from({ length: 7 }, (_, index) => shiftDateKey(today, index - 6));
  const last7Records = last7Keys.map((key) => byDate.get(key)).filter((item): item is DailyProgressRecord => Boolean(item));
  const last7Totals = aggregate(last7Records);
  const retainedTotals = aggregate(activity.daily);
  const themesPracticed = new Set<string>();
  last7Records.forEach((record) => {
    Object.entries(record.themeTurns).forEach(([themeId, turns]) => {
      if (turns > 0) themesPracticed.add(themeId);
    });
  });

  const masteredVocabulary = learning.vocabulary.filter(
    (item) => item.correctUses >= 2 && item.correctUses > item.needsWorkUses,
  );
  const reviewVocabulary = learning.vocabulary.filter(
    (item) => item.needsWorkUses > 0 && item.needsWorkUses >= item.correctUses,
  );
  const introducedVocabulary = learning.vocabulary.filter(
    (item) => !masteredVocabulary.includes(item) && !reviewVocabulary.includes(item),
  );

  const strengths = learning.evidence.filter(
    (item) => item.correctCount >= 2 && item.correctCount > item.needsWorkCount,
  );
  const reviewSkills = learning.evidence.filter(
    (item) => item.needsWorkCount > 0 && item.needsWorkCount >= item.correctCount,
  );

  const emptyCategory = () => ({ strengths: 0, review: 0 });
  const categories: Record<LearningCategory, { strengths: number; review: number }> = {
    grammar: emptyCategory(),
    vocabulary: emptyCategory(),
    usage: emptyCategory(),
    spelling: emptyCategory(),
  };
  strengths.forEach((item) => { categories[item.category].strengths += 1; });
  reviewSkills.forEach((item) => { categories[item.category].review += 1; });

  return {
    last7Days: {
      ...last7Totals,
      activeDays: last7Records.filter((item) => item.turns > 0).length,
      themesPracticed: themesPracticed.size,
      days: last7Keys.map((key) => {
        const record = byDate.get(key);
        return {
          date: key,
          label: dayLabel(key),
          turns: record?.turns ?? 0,
          words: (record?.userWords ?? 0) + (record?.assistantWords ?? 0),
        };
      }),
    },
    retained: {
      turns: retainedTotals.turns,
      activeDays: activity.daily.filter((item) => item.turns > 0).length,
      sessionsStarted: retainedTotals.sessionsStarted,
    },
    streakDays: calculateStreak(activity.daily),
    vocabulary: {
      total: learning.vocabulary.length,
      mastered: masteredVocabulary.length,
      review: reviewVocabulary.length,
      introduced: introducedVocabulary.length,
      topReview: [...reviewVocabulary].sort((a, b) => vocabularyPriority(b) - vocabularyPriority(a)).slice(0, 8),
    },
    skills: {
      total: learning.evidence.length,
      strengths: strengths.length,
      review: reviewSkills.length,
      categories,
      topReview: [...reviewSkills].sort((a, b) => skillPriority(b) - skillPriority(a)).slice(0, 8),
      topStrengths: [...strengths].sort((a, b) => b.correctCount - a.correctCount).slice(0, 6),
    },
    pronunciation: {
      assessmentCount: pronunciation.assessmentCount,
      averageAccuracy: pronunciation.averageAccuracy,
      averageFluency: pronunciation.averageFluency,
      averagePronunciation: pronunciation.averagePronunciation,
      weakWords: [...pronunciation.weakWords]
        .sort((a, b) => (b.weakAttempts * 10 - b.averageAccuracy) - (a.weakAttempts * 10 - a.averageAccuracy))
        .slice(0, 8),
    },
  };
}
