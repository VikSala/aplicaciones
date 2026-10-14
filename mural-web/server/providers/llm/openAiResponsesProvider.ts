import type { LlmGenerateRequest, LlmGenerateResult, LlmProvider, LlmUsage } from './types.ts';

interface OpenAiResponsesProviderOptions {
  id: string;
  label: string;
  apiKey?: string;
  baseUrl: string;
  model: string;
  reasoningEffort?: string;
}

function extractOutputText(response: any): string {
  if (!Array.isArray(response?.output)) return '';

  const parts: string[] = [];

  for (const item of response.output) {
    if (item?.type !== 'message' || !Array.isArray(item.content)) continue;

    for (const content of item.content) {
      if (content?.type === 'output_text' && typeof content.text === 'string') {
        parts.push(content.text);
      } else if (content?.type === 'refusal' && typeof content.refusal === 'string') {
        parts.push(content.refusal);
      }
    }
  }

  return parts.join('\n').trim();
}

function extractUsage(response: any): LlmUsage {
  const inputTokens = Number(response?.usage?.input_tokens) || 0;
  const outputTokens = Number(response?.usage?.output_tokens) || 0;
  const totalTokens = Number(response?.usage?.total_tokens) || inputTokens + outputTokens;

  return { inputTokens, outputTokens, totalTokens };
}

export class OpenAiResponsesProvider implements LlmProvider {
  readonly id: string;
  readonly label: string;
  readonly model: string;
  readonly configured: boolean;

  private readonly apiKey?: string;
  private readonly baseUrl: string;
  private readonly reasoningEffort: string;

  constructor(options: OpenAiResponsesProviderOptions) {
    this.id = options.id;
    this.label = options.label;
    this.apiKey = options.apiKey?.trim();
    this.baseUrl = options.baseUrl.replace(/\/$/, '');
    this.model = options.model;
    this.reasoningEffort = options.reasoningEffort || 'none';
    this.configured = Boolean(this.apiKey);
  }

  async generate(request: LlmGenerateRequest): Promise<LlmGenerateResult> {
    if (!this.apiKey) {
      throw new Error(`${this.label} no está configurado. Falta su API key en el servidor.`);
    }

    const response = await fetch(`${this.baseUrl}/responses`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify({
        model: this.model,
        instructions: request.instructions,
        input: request.messages.map((message) => ({
          role: message.role,
          content: message.text,
        })),
        reasoning: { effort: this.reasoningEffort },
        max_output_tokens: request.maxOutputTokens ?? 220,
        store: false,
      }),
    });

    const data = await response.json().catch(() => null);

    if (!response.ok) {
      const apiMessage = data?.error?.message;
      throw new Error(apiMessage ? `${this.label}: ${apiMessage}` : `${this.label} ha devuelto HTTP ${response.status}.`);
    }

    const text = extractOutputText(data);
    if (!text) {
      throw new Error(`${this.label} no ha devuelto contenido de texto.`);
    }

    return {
      text,
      model: this.model,
      provider: this.id,
      usage: extractUsage(data),
    };
  }
}
