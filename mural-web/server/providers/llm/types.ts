import type { ConversationMessage } from '../../../src/core/types.ts';

export interface LlmUsage {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}

export interface LlmGenerateRequest {
  instructions: string;
  messages: ConversationMessage[];
  maxOutputTokens?: number;
}

export interface LlmGenerateResult {
  text: string;
  model: string;
  provider: string;
  usage: LlmUsage;
}

export interface LlmProvider {
  readonly id: string;
  readonly label: string;
  readonly model: string;
  readonly configured: boolean;
  generate(request: LlmGenerateRequest): Promise<LlmGenerateResult>;
}
