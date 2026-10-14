import { englishLanguageModule } from './languages/english.ts';
import type { LanguageModule } from './types.ts';

const modules: Record<string, LanguageModule> = {
  [englishLanguageModule.id]: englishLanguageModule,
};

export const DEFAULT_LANGUAGE_ID = englishLanguageModule.id;

export function getLanguageModule(languageId: string = DEFAULT_LANGUAGE_ID): LanguageModule {
  return modules[languageId] ?? englishLanguageModule;
}

export const AVAILABLE_LANGUAGE_MODULES = Object.values(modules);
