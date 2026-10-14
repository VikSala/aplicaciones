import type { TurnLearningAnalysis } from '../learning/types';

interface LearningAnalysisResponse {
  analysis?: TurnLearningAnalysis;
  error?: string;
}

export async function analyzeLearningTurn(
  userText: string,
  assistantText: string,
  themeId: number,
  languageId = 'en',
): Promise<TurnLearningAnalysis> {
  const response = await fetch('/api/learning/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ userText, assistantText, themeId, languageId }),
  });

  const data = (await response.json().catch(() => ({}))) as LearningAnalysisResponse;

  if (!response.ok) {
    throw new Error(data.error || 'No se ha podido analizar el turno pedagógicamente.');
  }

  return data.analysis ?? { vocabulary: [], skills: [] };
}
