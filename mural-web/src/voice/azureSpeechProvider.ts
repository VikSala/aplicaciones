import type { PronunciationSegmentAssessment } from '../pronunciation/types';
import type { SttProvider, SttSessionOptions, SttStopReason } from './types';
import { finishAzureSttSession, startAzureSttSession } from '../services/sttSessionService';

const SPEECH_SDK_URL =
  'https://cdn.jsdelivr.net/npm/microsoft-cognitiveservices-speech-sdk@1.52.0/distrib/browser/microsoft.cognitiveservices.speech.sdk.bundle-min.js';

let speechSdkPromise: Promise<any> | null = null;

function loadSpeechSdk(): Promise<any> {
  if (window.SpeechSDK) return Promise.resolve(window.SpeechSDK);
  if (speechSdkPromise) return speechSdkPromise;

  speechSdkPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[data-mural-azure-speech-sdk="true"]');

    if (existing) {
      existing.addEventListener('load', () => (window.SpeechSDK ? resolve(window.SpeechSDK) : reject(new Error('AZURE_SDK_NOT_AVAILABLE'))), { once: true });
      existing.addEventListener('error', () => reject(new Error('AZURE_SDK_LOAD_FAILED')), { once: true });
      return;
    }

    const script = document.createElement('script');
    script.src = SPEECH_SDK_URL;
    script.async = true;
    script.dataset.muralAzureSpeechSdk = 'true';
    script.onload = () => (window.SpeechSDK ? resolve(window.SpeechSDK) : reject(new Error('AZURE_SDK_NOT_AVAILABLE')));
    script.onerror = () => reject(new Error('AZURE_SDK_LOAD_FAILED'));
    document.head.appendChild(script);
  });

  return speechSdkPromise;
}

function readableAzureError(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error || '');

  if (raw.includes('NotAllowedError') || raw.toLowerCase().includes('permission')) {
    return 'No se ha concedido permiso para usar el micrófono.';
  }
  if (raw.includes('AZURE_SDK_LOAD')) {
    return 'No se ha podido cargar el SDK de Azure Speech. Comprueba la conexión a Internet.';
  }
  if (raw.includes('STT_QUOTA_EXHAUSTED')) {
    return 'La cuota local gratuita de Azure Speech está agotada. Puedes continuar escribiendo.';
  }
  if (raw.includes('STT_SESSION_ALREADY_ACTIVE')) {
    return 'Ya hay una sesión de reconocimiento de voz activa.';
  }
  if (raw.includes('AZURE_NOT_CONFIGURED')) {
    return 'Azure Speech no está configurado en el servidor.';
  }

  return raw || 'Se ha producido un error durante el reconocimiento de voz.';
}


function scoreOrZero(value: unknown): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric < 0) return 0;
  return Math.max(0, Math.min(100, numeric));
}

function parsePronunciationWords(rawJson: string): PronunciationSegmentAssessment['words'] {
  if (!rawJson) return [];

  try {
    const parsed = JSON.parse(rawJson) as any;
    const words = parsed?.NBest?.[0]?.Words;
    if (!Array.isArray(words)) return [];

    return words
      .map((word: any) => {
        const label = String(word?.Word || word?.Display || '').trim();
        if (!label) return null;
        const pronunciation = word?.PronunciationAssessment || {};
        const phonemes = Array.isArray(word?.Phonemes)
          ? word.Phonemes
              .map((phoneme: any) => {
                const phonemeLabel = String(phoneme?.Phoneme || '').trim();
                if (!phonemeLabel) return null;
                return {
                  phoneme: phonemeLabel,
                  accuracyScore: scoreOrZero(phoneme?.PronunciationAssessment?.AccuracyScore),
                };
              })
              .filter(Boolean)
          : [];

        return {
          word: label,
          accuracyScore: scoreOrZero(pronunciation?.AccuracyScore),
          errorType: pronunciation?.ErrorType ? String(pronunciation.ErrorType) : undefined,
          phonemes,
        };
      })
      .filter(Boolean) as PronunciationSegmentAssessment['words'];
  } catch {
    return [];
  }
}

declare global {
  interface Window {
    SpeechSDK?: any;
  }
}

export class AzureSpeechProvider implements SttProvider {
  readonly id = 'azure' as const;

  private recognizer: any | null = null;
  private audioConfig: any | null = null;
  private pronunciationConfig: any | null = null;
  private sessionId: string | null = null;
  private autoStopTimer: number | null = null;
  private stoppingPromise: Promise<void> | null = null;
  private partialListeners = new Set<(text: string) => void>();
  private finalListeners = new Set<(text: string) => void>();
  private pronunciationListeners = new Set<(assessment: PronunciationSegmentAssessment) => void>();
  private errorListeners = new Set<(message: string) => void>();
  private stoppedListeners = new Set<(reason: SttStopReason) => void>();

  onPartialTranscript(callback: (text: string) => void): () => void {
    this.partialListeners.add(callback);
    return () => this.partialListeners.delete(callback);
  }

  onFinalTranscript(callback: (text: string) => void): () => void {
    this.finalListeners.add(callback);
    return () => this.finalListeners.delete(callback);
  }

  onPronunciationAssessment(callback: (assessment: PronunciationSegmentAssessment) => void): () => void {
    this.pronunciationListeners.add(callback);
    return () => this.pronunciationListeners.delete(callback);
  }

  onError(callback: (message: string) => void): () => void {
    this.errorListeners.add(callback);
    return () => this.errorListeners.delete(callback);
  }

  onStopped(callback: (reason: SttStopReason) => void): () => void {
    this.stoppedListeners.add(callback);
    return () => this.stoppedListeners.delete(callback);
  }

  private emitError(error: unknown): void {
    const message = readableAzureError(error);
    this.errorListeners.forEach((listener) => listener(message));
  }

  private emitStopped(reason: SttStopReason): void {
    this.stoppedListeners.forEach((listener) => listener(reason));
  }

  async start(options: SttSessionOptions): Promise<void> {
    if (this.recognizer || this.sessionId) throw new Error('Ya hay una sesión de voz activa.');
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('Este navegador no ofrece acceso al micrófono mediante MediaDevices.');
    }

    const SpeechSDK = await loadSpeechSdk();
    const session = await startAzureSttSession();
    this.sessionId = session.sessionId;

    try {
      const speechConfig = SpeechSDK.SpeechConfig.fromAuthorizationToken(session.token, session.region);
      speechConfig.speechRecognitionLanguage = options.language;
      if (options.pronunciationAssessmentMode === 'basic' && SpeechSDK.OutputFormat?.Detailed !== undefined) {
        speechConfig.outputFormat = SpeechSDK.OutputFormat.Detailed;
      }
      if (typeof speechConfig.enableDictation === 'function') speechConfig.enableDictation();

      this.audioConfig = SpeechSDK.AudioConfig.fromDefaultMicrophoneInput();
      const recognizer = new SpeechSDK.SpeechRecognizer(speechConfig, this.audioConfig);
      this.recognizer = recognizer;

      if (options.pronunciationAssessmentMode === 'basic') {
        const pronunciationConfig = new SpeechSDK.PronunciationAssessmentConfig(
          '',
          SpeechSDK.PronunciationAssessmentGradingSystem.HundredMark,
          SpeechSDK.PronunciationAssessmentGranularity.Phoneme,
          false,
        );
        // IPA es más útil pedagógicamente que el alfabeto SAPI. No activamos Prosody:
        // Azure lo factura como add-on, mientras Accuracy/Fluency forman parte de la evaluación base.
        pronunciationConfig.phonemeAlphabet = 'IPA';
        pronunciationConfig.nbestPhonemeCount = 3;
        pronunciationConfig.applyTo(recognizer);
        this.pronunciationConfig = pronunciationConfig;
      }

      recognizer.recognizing = (_sender: unknown, event: any) => {
        const text = event?.result?.text?.trim();
        if (text) this.partialListeners.forEach((listener) => listener(text));
      };

      recognizer.recognized = (_sender: unknown, event: any) => {
        if (event?.result?.reason !== SpeechSDK.ResultReason.RecognizedSpeech) return;
        const text = event?.result?.text?.trim();
        if (text) this.finalListeners.forEach((listener) => listener(text));

        if (text && this.pronunciationConfig) {
          try {
            const assessment = SpeechSDK.PronunciationAssessmentResult.fromResult(event.result);
            const rawJson = event.result.properties?.getProperty?.(
              SpeechSDK.PropertyId.SpeechServiceResponse_JsonResult,
            ) || '';
            const accuracyScore = scoreOrZero(assessment?.accuracyScore);
            const fluencyScore = scoreOrZero(assessment?.fluencyScore);
            let pronunciationScore = scoreOrZero(assessment?.pronunciationScore);
            if (pronunciationScore === 0 && accuracyScore > 0 && fluencyScore > 0) {
              const lower = Math.min(accuracyScore, fluencyScore);
              const higher = Math.max(accuracyScore, fluencyScore);
              pronunciationScore = (0.6 * lower) + (0.4 * higher);
            }
            const segment: PronunciationSegmentAssessment = {
              text,
              accuracyScore,
              fluencyScore,
              pronunciationScore,
              words: parsePronunciationWords(rawJson),
            };
            this.pronunciationListeners.forEach((listener) => listener(segment));
          } catch (assessmentError) {
            // La evaluación es complementaria: nunca debe romper la transcripción normal.
            console.warn('Pronunciation Assessment no disponible para este segmento:', assessmentError);
          }
        }
      };

      recognizer.canceled = (_sender: unknown, event: any) => {
        const details = event?.errorDetails || event?.reason || 'Azure Speech canceló el reconocimiento.';
        this.emitError(details);
        void this.stopInternal('service');
      };

      recognizer.sessionStopped = () => {
        if (!this.stoppingPromise) void this.stopInternal('service');
      };

      await new Promise<void>((resolve, reject) => {
        recognizer.startContinuousRecognitionAsync(resolve, (error: string) => reject(new Error(error)));
      });

      this.autoStopTimer = window.setTimeout(() => {
        void this.stopInternal('limit');
      }, session.maxSessionSeconds * 1000);
    } catch (error) {
      this.emitError(error);
      await this.stopInternal('error', false);
      throw new Error(readableAzureError(error));
    }
  }

  async stop(): Promise<void> {
    return this.stopInternal('manual');
  }

  private async stopInternal(reason: SttStopReason, emitStopped = true): Promise<void> {
    if (this.stoppingPromise) return this.stoppingPromise;

    this.stoppingPromise = (async () => {
      if (this.autoStopTimer !== null) {
        window.clearTimeout(this.autoStopTimer);
        this.autoStopTimer = null;
      }

      const recognizer = this.recognizer;
      const audioConfig = this.audioConfig;
      const pronunciationConfig = this.pronunciationConfig;
      const sessionId = this.sessionId;

      this.recognizer = null;
      this.audioConfig = null;
      this.pronunciationConfig = null;
      this.sessionId = null;

      if (recognizer) {
        try {
          await new Promise<void>((resolve) => {
            recognizer.stopContinuousRecognitionAsync(resolve, resolve);
          });
        } catch {
          // El cierre del backend sigue siendo prioritario aunque Azure ya haya cortado la conexión.
        }

        try {
          recognizer.close();
        } catch {
          // Nada que liberar adicionalmente.
        }
      }

      if (audioConfig && typeof audioConfig.close === 'function') {
        try {
          audioConfig.close();
        } catch {
          // Nada que liberar adicionalmente.
        }
      }

      if (pronunciationConfig && typeof pronunciationConfig.close === 'function') {
        try {
          pronunciationConfig.close();
        } catch {
          // Nada que liberar adicionalmente.
        }
      }

      if (sessionId) {
        try {
          await finishAzureSttSession(sessionId);
        } catch (error) {
          this.emitError(error);
        }
      }

      if (emitStopped) this.emitStopped(reason);
    })();

    try {
      await this.stoppingPromise;
    } finally {
      this.stoppingPromise = null;
    }
  }
}
