import type { LearningEvidenceItem, LearningMemorySnapshot, VocabularyMemoryItem } from './types';
import { buildPronunciationContext } from '../pronunciation/memory';
import type { PronunciationMemorySnapshot } from '../pronunciation/types';

const MAX_CONTEXT_ITEMS = 8;

function evidencePriority(item: LearningEvidenceItem): number {
  return item.needsWorkCount * 3 - item.correctCount + new Date(item.lastSeenAt).getTime() / 1e13;
}

function vocabularyPriority(item: VocabularyMemoryItem): number {
  return item.needsWorkUses * 3 + item.introducedCount - item.correctUses + new Date(item.lastSeenAt).getTime() / 1e13;
}

export function buildLearningContext(
  memory: LearningMemorySnapshot,
  pronunciation?: PronunciationMemorySnapshot,
): string {
  const pronunciationContext = pronunciation ? buildPronunciationContext(pronunciation) : '';
  if (memory.vocabulary.length === 0 && memory.evidence.length === 0 && !pronunciationContext) return '';

  const needsWork = [...memory.evidence]
    .filter((item) => item.needsWorkCount > 0)
    .sort((a, b) => evidencePriority(b) - evidencePriority(a))
    .slice(0, MAX_CONTEXT_ITEMS);

  const strengths = [...memory.evidence]
    .filter((item) => item.correctCount >= 2 && item.correctCount > item.needsWorkCount)
    .sort((a, b) => b.correctCount - a.correctCount)
    .slice(0, 4);

  const vocabulary = [...memory.vocabulary]
    .filter((item) => item.needsWorkUses > 0 || item.introducedCount > 0)
    .sort((a, b) => vocabularyPriority(b) - vocabularyPriority(a))
    .slice(0, MAX_CONTEXT_ITEMS);

  const sections: string[] = [];

  if (needsWork.length > 0) {
    sections.push([
      'Puntos a reforzar:',
      ...needsWork.map((item) => {
        const correction = item.correction ? `; corrección útil: ${item.correction}` : '';
        return `- ${item.label}: ${item.needsWorkCount} dificultad(es), ${item.correctCount} uso(s) correcto(s)${correction}`;
      }),
    ].join('\n'));
  }

  if (vocabulary.length > 0) {
    sections.push([
      'Vocabulario a reciclar de forma natural:',
      ...vocabulary.map((item) => {
        const meaning = item.meaningEs ? ` (${item.meaningEs})` : '';
        return `- ${item.term}${meaning}: ${item.correctUses} uso(s) correcto(s), ${item.needsWorkUses} dificultad(es)`;
      }),
    ].join('\n'));
  }

  if (strengths.length > 0) {
    sections.push([
      'Fortalezas observadas:',
      ...strengths.map((item) => `- ${item.label}: ${item.correctCount} evidencias correctas`),
    ].join('\n'));
  }

  if (pronunciationContext) sections.push(pronunciationContext);

  return sections.join('\n\n').slice(0, 4500);
}
