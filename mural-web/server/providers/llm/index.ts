import { OpenAiResponsesProvider } from './openAiResponsesProvider.ts';
import type { LlmProvider } from './types.ts';

export function createLlmProvider(): LlmProvider {
  const providerId = (process.env.LLM_PROVIDER?.trim() || 'vercel').toLowerCase();
  const reasoningEffort = process.env.LLM_REASONING_EFFORT?.trim() || 'none';

  if (providerId === 'openai') {
    return new OpenAiResponsesProvider({
      id: 'openai',
      label: 'OpenAI',
      apiKey: process.env.OPENAI_API_KEY,
      baseUrl: process.env.OPENAI_BASE_URL?.trim() || 'https://api.openai.com/v1',
      model: process.env.LLM_MODEL?.trim() || process.env.OPENAI_TEXT_MODEL?.trim() || 'gpt-6-luna',
      reasoningEffort,
    });
  }

  if (providerId !== 'vercel') {
    throw new Error(`LLM_PROVIDER no soportado: ${providerId}`);
  }

  return new OpenAiResponsesProvider({
    id: 'vercel',
    label: 'Vercel AI Gateway',
    apiKey: process.env.AI_GATEWAY_API_KEY,
    baseUrl: process.env.LLM_BASE_URL?.trim() || 'https://ai-gateway.vercel.sh/v1',
    model: process.env.LLM_MODEL?.trim() || 'openai/gpt-6-luna',
    reasoningEffort,
  });
}
