export type ChatRole = 'user' | 'assistant';

export interface ConversationMessage {
  role: ChatRole;
  text: string;
}

export interface ConversationTheme {
  id: number;
  title: string;
  description: string;
  culturalContext: string;
}

export interface LearningStage {
  id: string;
  title: string;
  description: string;
  guidance: string;
}

export interface LanguageModule {
  id: string;
  name: string;
  locale: string;
  nativeLanguage: string;
  greeting: string;
  pronunciationGuidance: string;
  writingGuidance: string;
  stages: LearningStage[];
  themes: ConversationTheme[];
  normalizeWord: (word: string) => string;
}
