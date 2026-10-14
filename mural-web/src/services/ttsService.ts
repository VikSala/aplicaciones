import type { SynthesizedAudio } from '../voice/types';

export async function synthesizeWithGoogle(
  text: string,
  options: { language: string; voice?: string },
): Promise<SynthesizedAudio> {
  const response = await fetch('/api/tts/synthesize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text,
      language: options.language,
      voice: options.voice,
    }),
  });

  if (!response.ok) {
    const data = (await response.json().catch(() => ({}))) as { error?: string };
    throw new Error(data.error || 'No se ha podido generar el audio con Google Chirp.');
  }

  const blob = await response.blob();
  if (!blob.size) throw new Error('Google Chirp no ha devuelto audio reproducible.');

  return {
    blob,
    characters: Number(response.headers.get('X-Mural-TTS-Characters') || 0),
    voice: response.headers.get('X-Mural-TTS-Voice') || undefined,
    language: response.headers.get('X-Mural-TTS-Language') || undefined,
  };
}
