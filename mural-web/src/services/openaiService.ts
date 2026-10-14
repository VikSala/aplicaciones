import type { ConversationMessage } from '../core/types';

interface ChatResponse {
  reply?: string;
  model?: string;
  error?: string;
}

export async function sendChatMessage(
  messages: ConversationMessage[],
  themeId: number,
  languageId = 'en',
): Promise<string> {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      messages,
      themeId,
      languageId,
    }),
  });

  const data = (await response.json().catch(() => ({}))) as ChatResponse;

  if (!response.ok) {
    throw new Error(data.error || 'No se ha podido completar la petición a OpenAI.');
  }

  if (!data.reply) {
    throw new Error('OpenAI no ha devuelto una respuesta de texto.');
  }

  return data.reply;
}
