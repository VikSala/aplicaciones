import { BASE_PEDAGOGICAL_RULES } from './prompts.ts';
import type { ConversationTheme, LanguageModule } from './types.ts';

interface PromptContext {
  language: LanguageModule;
  theme: ConversationTheme;
  learningContext?: string;
}

export function buildConversationInstructions({ language, theme, learningContext }: PromptContext): string {
  const memorySection = learningContext?.trim()
    ? `\nMemoria pedagógica agregada proporcionada por Mural:\n${learningContext.trim()}\n\nUsa esta memoria con discreción. No enumeres métricas ni digas que tienes una base de datos sobre el usuario. Recicla vocabulario y refuerza puntos débiles de forma natural, sin convertir cada turno en un examen.`
    : '\nNo hay memoria pedagógica suficiente todavía. No inventes progreso, nivel ni errores anteriores.';

  return `
${BASE_PEDAGOGICAL_RULES}

Configuración actual:
- Idioma nativo del usuario: ${language.nativeLanguage}.
- Idioma que practica: ${language.name} (${language.locale}).
- Responde principalmente en ${language.name}.
- Guía de pronunciación: ${language.pronunciationGuidance}
- Guía de escritura: ${language.writingGuidance}

Tema actual: ${theme.title}
Objetivo del tema: ${theme.description}
Contexto cultural orientativo: ${theme.culturalContext}
${memorySection}
`.trim();
}
