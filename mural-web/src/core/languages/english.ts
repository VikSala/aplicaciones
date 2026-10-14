import { CONVERSATION_THEMES } from '../prompts.ts';
import type { LanguageModule } from '../types.ts';

export const englishLanguageModule: LanguageModule = {
  id: 'en',
  name: 'Inglés',
  locale: 'en-US',
  nativeLanguage: 'Español',
  greeting: 'Hi! What would you like to talk about today?',
  pronunciationGuidance: 'Prioriza pronunciación natural y frases habituales del inglés moderno.',
  writingGuidance: 'Usa inglés claro y natural, evitando construcciones innecesariamente rebuscadas.',
  stages: [
    { id: 'a1', title: 'A1', description: 'Inicial', guidance: 'Usa vocabulario básico, frases cortas y estructuras muy frecuentes.' },
    { id: 'a2', title: 'A2', description: 'Básico', guidance: 'Usa lenguaje cotidiano y amplía poco a poco las estructuras.' },
    { id: 'b1', title: 'B1', description: 'Intermedio', guidance: 'Mantén conversación cotidiana con variedad moderada de tiempos y vocabulario.' },
    { id: 'b2', title: 'B2', description: 'Intermedio alto', guidance: 'Introduce matices, expresiones naturales y temas más abstractos.' },
    { id: 'c1', title: 'C1', description: 'Avanzado', guidance: 'Usa lenguaje idiomático, preciso y flexible.' },
    { id: 'c2', title: 'C2', description: 'Dominio', guidance: 'Conversa con máxima naturalidad, precisión y riqueza expresiva.' },
  ],
  themes: CONVERSATION_THEMES,
  normalizeWord: (word: string) => word.trim().toLocaleLowerCase('en-US'),
};
