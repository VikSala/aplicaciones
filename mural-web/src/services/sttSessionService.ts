export interface StartSttSessionResponse {
  sessionId: string;
  token: string;
  region: string;
  maxSessionSeconds: number;
  remainingSeconds: number;
}

export interface FinishSttSessionResponse {
  sessionId: string;
  recordedSeconds: number;
}

async function parseJson(response: Response): Promise<any> {
  return response.json().catch(() => null);
}

export async function startAzureSttSession(): Promise<StartSttSessionResponse> {
  const response = await fetch('/api/stt/session/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  });
  const data = await parseJson(response);

  if (!response.ok || !data) {
    throw new Error(data?.error || 'No se ha podido iniciar Azure Speech.');
  }

  return data as StartSttSessionResponse;
}

export async function finishAzureSttSession(sessionId: string): Promise<FinishSttSessionResponse> {
  const response = await fetch('/api/stt/session/finish', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId }),
  });
  const data = await parseJson(response);

  if (!response.ok || !data) {
    throw new Error(data?.error || 'No se ha podido cerrar la sesión de Azure Speech.');
  }

  return data as FinishSttSessionResponse;
}
