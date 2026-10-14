import { synthesizeWithGoogle } from '../services/ttsService';
import type { SynthesizedAudio, TtsProvider, TtsSynthesisOptions } from './types';

export class GoogleChirpProvider implements TtsProvider {
  readonly id = 'google-chirp-3-hd' as const;
  private currentAudio: HTMLAudioElement | null = null;
  private currentUrl: string | null = null;
  private currentResolve: (() => void) | null = null;

  async synthesize(text: string, options: TtsSynthesisOptions): Promise<SynthesizedAudio> {
    return synthesizeWithGoogle(text, {
      language: options.language,
      voice: options.voice,
    });
  }

  async play(audio: SynthesizedAudio): Promise<void> {
    this.stop();

    return new Promise<void>((resolve, reject) => {
      const url = URL.createObjectURL(audio.blob);
      const element = new Audio(url);
      this.currentAudio = element;
      this.currentUrl = url;
      this.currentResolve = resolve;

      const cleanup = () => {
        element.onended = null;
        element.onerror = null;
        if (this.currentUrl === url) {
          URL.revokeObjectURL(url);
          this.currentUrl = null;
        }
        if (this.currentAudio === element) this.currentAudio = null;
        if (this.currentResolve === resolve) this.currentResolve = null;
      };

      element.onended = () => {
        cleanup();
        resolve();
      };
      element.onerror = () => {
        cleanup();
        reject(new Error('El navegador no ha podido reproducir el audio generado por Google Chirp.'));
      };

      element.play().catch((error) => {
        cleanup();
        reject(
          error instanceof Error
            ? error
            : new Error('El navegador ha bloqueado la reproducción del audio.'),
        );
      });
    });
  }

  stop(): void {
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio.currentTime = 0;
      this.currentAudio.onended = null;
      this.currentAudio.onerror = null;
      this.currentAudio = null;
    }
    if (this.currentUrl) {
      URL.revokeObjectURL(this.currentUrl);
      this.currentUrl = null;
    }
    if (this.currentResolve) {
      const resolve = this.currentResolve;
      this.currentResolve = null;
      resolve();
    }
  }
}
