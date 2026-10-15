import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ConversationOrb } from './ConversationOrb';
import { SettingsModal } from './SettingsModal';
import { ProgressDashboard } from './ProgressDashboard';
import { ThemePickerSheet } from './ThemePickerSheet';
import { WordsView } from './WordsView';
import { AppIcon } from './AppIcon';
import { getLanguageModule } from '../core/languageModules';
import type { ConversationMessage } from '../core/types';
import { buildLearningContext } from '../learning/memory';
import type { LearningMemorySnapshot } from '../learning/types';
import { emptyPronunciationMemory, summarizePronunciationSegments } from '../pronunciation/memory';
import { buildProgressOverview } from '../progress/analytics';
import type { ProgressActivitySnapshot } from '../progress/types';
import { usePwaInstall } from '../pwa/usePwaInstall';
import type {
  PronunciationAssessmentSummary,
  PronunciationMemorySnapshot,
  PronunciationSegmentAssessment,
} from '../pronunciation/types';
import { analyzeLearningTurn } from '../services/learningService';
import { sendChatMessage } from '../services/llmService';
import { fetchUsageSnapshot, type UsageSnapshot } from '../services/usageService';
import { loadVoicePreferences, normalizeVoicePreferences, saveVoicePreferences } from '../services/voicePreferences';
import { AzureSpeechProvider } from '../voice/azureSpeechProvider';
import { GoogleChirpProvider } from '../voice/googleChirpProvider';
import type { SttStopReason, SynthesizedAudio, VoicePreferences } from '../voice/types';
import { applyAppearance, cacheAppearancePreference, loadAppearancePreference, type AppearanceMode } from '../theme/appearance';
import {
  applyLearningAnalysis,
  applyPronunciationAssessment,
  clearLearningMemory,
  clearPronunciationMemory,
  clearProgressActivity,
  loadActiveConversation,
  loadLearningMemory,
  loadPronunciationMemory,
  loadProgressActivity,
  loadSetting,
  recordProgressSessionStart,
  recordProgressTurn,
  resetActiveConversation,
  saveActiveConversation,
  saveSetting,
  STORAGE_SETTING_KEYS,
} from '../storage/muralDb';

type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking';
type TurnSource = 'keyboard' | 'voice';
type MainSection = 'conversation' | 'progress' | 'words';

function joinTranscript(parts: string[]): string {
  return parts.map((part) => part.trim()).filter(Boolean).join(' ').replace(/\s+/g, ' ').trim();
}

const SPEECH_HINT_STOP_WORDS = new Set([
  'about', 'after', 'again', 'also', 'because', 'before', 'being', 'could', 'every', 'from', 'have', 'into',
  'just', 'like', 'more', 'other', 'really', 'some', 'than', 'that', 'their', 'there', 'these', 'they',
  'this', 'those', 'very', 'what', 'when', 'where', 'which', 'while', 'with', 'would', 'your',
]);

function buildSpeechPhraseHints(
  memory: LearningMemorySnapshot,
  messages: ConversationMessage[],
  draftText: string,
): string[] {
  const hints = new Set<string>();

  [...memory.vocabulary]
    .sort((a, b) => new Date(b.lastSeenAt).getTime() - new Date(a.lastSeenAt).getTime())
    .slice(0, 24)
    .forEach((item) => {
      const term = item.term.trim();
      if (term.length >= 2 && term.length <= 80) hints.add(term);
    });

  const lastAssistant = [...messages].reverse().find((message) => message.role === 'assistant')?.text || '';
  const contextualText = `${lastAssistant} ${draftText}`;
  const contextualWords = contextualText.match(/[A-Za-z][A-Za-z'’-]{4,}/g) || [];

  contextualWords.forEach((word) => {
    const clean = word.replace(/[’]/g, "'").trim();
    const normalized = clean.toLowerCase();
    if (!SPEECH_HINT_STOP_WORDS.has(normalized) && hints.size < 40) hints.add(clean);
  });

  return Array.from(hints).slice(0, 40);
}

function addSetValue(current: Set<number>, value: number): Set<number> {
  const next = new Set(current);
  next.add(value);
  return next;
}

function removeSetValue(current: Set<number>, value: number): Set<number> {
  const next = new Set(current);
  next.delete(value);
  return next;
}

interface OutputPlan {
  synthesizeAudio: boolean;
  hideText: boolean;
  fallbackToReading: boolean;
}

function resolveOutputPlan(
  preferences: VoicePreferences,
  snapshot: UsageSnapshot | null,
): OutputPlan {
  const googleAvailable = Boolean(
    snapshot?.providers.tts.configured && snapshot.tts.available && preferences.ttsMode !== 'text',
  );

  if (preferences.responseDisplayMode === 'reading') {
    return { synthesizeAudio: false, hideText: false, fallbackToReading: false };
  }

  if (preferences.responseDisplayMode === 'mixed') {
    return {
      synthesizeAudio: googleAvailable,
      hideText: false,
      fallbackToReading: !googleAvailable && preferences.ttsMode !== 'text',
    };
  }

  if (preferences.responseDisplayMode === 'listening') {
    return googleAvailable
      ? { synthesizeAudio: true, hideText: true, fallbackToReading: false }
      : { synthesizeAudio: false, hideText: false, fallbackToReading: true };
  }

  // Automático: Listening mientras Chirp esté disponible; Reading si no lo está.
  return googleAvailable
    ? { synthesizeAudio: true, hideText: true, fallbackToReading: false }
    : { synthesizeAudio: false, hideText: false, fallbackToReading: preferences.ttsMode !== 'text' };
}

export const MainView: React.FC = () => {
  const language = useMemo(() => getLanguageModule('en'), []);
  const pwaInstall = usePwaInstall();
  const [mainSection, setMainSection] = useState<MainSection>('conversation');
  const [themePickerOpen, setThemePickerOpen] = useState(false);
  const [appearanceMode, setAppearanceMode] = useState<AppearanceMode>(() => loadAppearancePreference());
  const [isOnline, setIsOnline] = useState(() => (typeof navigator === 'undefined' ? true : navigator.onLine));
  const [orbState, setOrbState] = useState<OrbState>('idle');
  const [selectedThemeId, setSelectedThemeId] = useState(language.themes[0].id);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [inputText, setInputText] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sttNotice, setSttNotice] = useState<string | null>(null);
  const [ttsNotice, setTtsNotice] = useState<string | null>(null);
  const [generalNotice, setGeneralNotice] = useState<string | null>(null);
  const [usage, setUsage] = useState<UsageSnapshot | null>(null);
  const [voicePreferences, setVoicePreferences] = useState<VoicePreferences>(() => loadVoicePreferences());
  const [hiddenAssistantIndexes, setHiddenAssistantIndexes] = useState<Set<number>>(() => new Set());
  const [audioReadyIndexes, setAudioReadyIndexes] = useState<Set<number>>(() => new Set());
  const [persistenceStatus, setPersistenceStatus] = useState<'loading' | 'ready' | 'unavailable'>('loading');
  const [persistenceError, setPersistenceError] = useState<string | null>(null);
  const [learningMemory, setLearningMemory] = useState<LearningMemorySnapshot>({ vocabulary: [], evidence: [] });
  const [learningStatus, setLearningStatus] = useState<'loading' | 'ready' | 'updating' | 'error'>('loading');
  const [learningError, setLearningError] = useState<string | null>(null);
  const [pronunciationMemory, setPronunciationMemory] = useState<PronunciationMemorySnapshot>(() => emptyPronunciationMemory(language.id));
  const [lastPronunciationAssessment, setLastPronunciationAssessment] = useState<PronunciationAssessmentSummary | null>(null);
  const [pronunciationStatus, setPronunciationStatus] = useState<'loading' | 'ready' | 'updating' | 'error'>('loading');
  const [pronunciationError, setPronunciationError] = useState<string | null>(null);
  const [progressActivity, setProgressActivity] = useState<ProgressActivitySnapshot>({ daily: [] });
  const [progressStatus, setProgressStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [progressError, setProgressError] = useState<string | null>(null);

  const sttProviderRef = useRef<AzureSpeechProvider | null>(null);
  const ttsProviderRef = useRef<GoogleChirpProvider | null>(null);
  const audioCacheRef = useRef<Map<number, SynthesizedAudio>>(new Map());
  const dictationBaseRef = useRef('');
  const finalTranscriptRef = useRef<string[]>([]);
  const latestPartialRef = useRef('');
  const messagesRef = useRef<ConversationMessage[]>([]);
  const selectedThemeIdRef = useRef(selectedThemeId);
  const isSendingRef = useRef(false);
  const isListeningRef = useRef(false);
  const voicePreferencesRef = useRef(voicePreferences);
  const usageRef = useRef<UsageSnapshot | null>(null);
  const persistenceStatusRef = useRef<'loading' | 'ready' | 'unavailable'>('loading');
  const learningMemoryRef = useRef<LearningMemorySnapshot>({ vocabulary: [], evidence: [] });
  const learningPipelineRef = useRef<Promise<void>>(Promise.resolve());
  const pronunciationMemoryRef = useRef<PronunciationMemorySnapshot>(emptyPronunciationMemory(language.id));
  const pronunciationSegmentsRef = useRef<PronunciationSegmentAssessment[]>([]);
  const sessionStartedAtRef = useRef(new Date().toISOString());
  const draftSourceRef = useRef<TurnSource>('keyboard');
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  if (!sttProviderRef.current) sttProviderRef.current = new AzureSpeechProvider();
  if (!ttsProviderRef.current) ttsProviderRef.current = new GoogleChirpProvider();

  const selectedTheme = language.themes.find((theme) => theme.id === selectedThemeId) ?? language.themes[0];
  const progressOverview = useMemo(
    () => buildProgressOverview(progressActivity, learningMemory, pronunciationMemory),
    [progressActivity, learningMemory, pronunciationMemory],
  );

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    selectedThemeIdRef.current = selectedThemeId;
  }, [selectedThemeId]);

  useEffect(() => {
    voicePreferencesRef.current = voicePreferences;
  }, [voicePreferences]);

  useEffect(() => {
    persistenceStatusRef.current = persistenceStatus;
  }, [persistenceStatus]);

  useEffect(() => {
    const updateOnlineState = () => setIsOnline(navigator.onLine);
    window.addEventListener('online', updateOnlineState);
    window.addEventListener('offline', updateOnlineState);
    return () => {
      window.removeEventListener('online', updateOnlineState);
      window.removeEventListener('offline', updateOnlineState);
    };
  }, []);

  useEffect(() => {
    applyAppearance(appearanceMode);
    if (appearanceMode !== 'system' || typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const media = window.matchMedia('(prefers-color-scheme: light)');
    const handleSystemTheme = () => applyAppearance('system');
    media.addEventListener?.('change', handleSystemTheme);
    return () => media.removeEventListener?.('change', handleSystemTheme);
  }, [appearanceMode]);

  useEffect(() => {
    let cancelled = false;

    const hydrate = async () => {
      try {
        const [conversation, storedVoicePreferences, storedAppearanceMode, storedLearningMemory, storedPronunciationMemory, storedProgressActivity] = await Promise.all([
          loadActiveConversation(),
          loadSetting<Partial<VoicePreferences>>(STORAGE_SETTING_KEYS.voicePreferences),
          loadSetting<AppearanceMode>(STORAGE_SETTING_KEYS.appearanceMode),
          loadLearningMemory(language.id),
          loadPronunciationMemory(language.id),
          loadProgressActivity(language.id),
        ]);

        if (cancelled) return;

        learningMemoryRef.current = storedLearningMemory;
        setLearningMemory(storedLearningMemory);
        setLearningStatus('ready');
        setLearningError(null);

        pronunciationMemoryRef.current = storedPronunciationMemory;
        setPronunciationMemory(storedPronunciationMemory);
        setLastPronunciationAssessment(storedPronunciationMemory.latestAssessment ?? null);
        setPronunciationStatus('ready');
        setPronunciationError(null);

        setProgressActivity(storedProgressActivity);
        setProgressStatus('ready');
        setProgressError(null);

        const nextAppearanceMode: AppearanceMode = storedAppearanceMode === 'light' || storedAppearanceMode === 'dark' || storedAppearanceMode === 'system' ? storedAppearanceMode : loadAppearancePreference();
        setAppearanceMode(nextAppearanceMode);
        cacheAppearancePreference(nextAppearanceMode);
        applyAppearance(nextAppearanceMode);
        if (!storedAppearanceMode) await saveSetting(STORAGE_SETTING_KEYS.appearanceMode, nextAppearanceMode);

        if (storedVoicePreferences) {
          const normalized = normalizeVoicePreferences(storedVoicePreferences);
          voicePreferencesRef.current = normalized;
          setVoicePreferences(normalized);
          saveVoicePreferences(normalized);
        } else {
          await saveSetting(STORAGE_SETTING_KEYS.voicePreferences, voicePreferencesRef.current);
        }

        const restoredTheme = conversation
          ? language.themes.find((theme) => theme.id === conversation.themeId)
          : null;

        if (conversation && conversation.languageId === language.id && restoredTheme) {
          sessionStartedAtRef.current = conversation.startedAt;
          selectedThemeIdRef.current = conversation.themeId;
          messagesRef.current = conversation.messages;
          setSelectedThemeId(conversation.themeId);
          setMessages(conversation.messages);
        } else {
          const defaultThemeId = language.themes[0].id;
          sessionStartedAtRef.current = await resetActiveConversation(language.id, defaultThemeId);
          const activity = await recordProgressSessionStart(language.id, defaultThemeId);
          setProgressActivity(activity);
          selectedThemeIdRef.current = defaultThemeId;
          messagesRef.current = [];
          setSelectedThemeId(defaultThemeId);
          setMessages([]);
        }

        if (!cancelled) {
          persistenceStatusRef.current = 'ready';
          setPersistenceStatus('ready');
          setPersistenceError(null);
        }
      } catch (storageError) {
        if (cancelled) return;
        persistenceStatusRef.current = 'unavailable';
        setPersistenceStatus('unavailable');
        setLearningStatus('error');
        setPronunciationStatus('error');
        setProgressStatus('error');
        setPersistenceError(
          storageError instanceof Error
            ? storageError.message
            : 'La persistencia local no está disponible. La conversación seguirá funcionando sin guardado.',
        );
      }
    };

    void hydrate();
    return () => {
      cancelled = true;
    };
  }, [language.id, language.themes]);

  const persistConversation = useCallback(
    async (nextMessages: ConversationMessage[], themeId = selectedThemeIdRef.current) => {
      if (persistenceStatusRef.current !== 'ready') return;

      try {
        await saveActiveConversation(
          language.id,
          themeId,
          nextMessages,
          sessionStartedAtRef.current,
        );
        setPersistenceError(null);
      } catch (storageError) {
        setPersistenceError(
          storageError instanceof Error
            ? storageError.message
            : 'No se ha podido guardar la conversación localmente.',
        );
      }
    },
    [language.id],
  );

  const refreshUsage = useCallback(async (): Promise<UsageSnapshot | null> => {
    try {
      const snapshot = await fetchUsageSnapshot();
      usageRef.current = snapshot;
      setUsage(snapshot);
      return snapshot;
    } catch {
      return null;
    }
  }, []);

  const playCachedAudio = useCallback(async (messageIndex: number) => {
    const cached = audioCacheRef.current.get(messageIndex);
    if (!cached || isListeningRef.current || isSendingRef.current) return;

    const provider = ttsProviderRef.current!;
    setError(null);
    setTtsNotice('Reproduciendo el audio ya generado. No consume caracteres adicionales.');
    setIsSpeaking(true);
    setOrbState('speaking');

    try {
      await provider.play(cached);
    } catch (playbackError) {
      setError(
        playbackError instanceof Error
          ? playbackError.message
          : 'El navegador no ha podido reproducir el audio.',
      );
    } finally {
      setIsSpeaking(false);
      if (!isListeningRef.current && !isSendingRef.current) setOrbState('idle');
    }
  }, []);

  const submitTurn = useCallback(
    async (rawText: string, source: TurnSource = 'keyboard'): Promise<boolean> => {
      const text = rawText.trim();
      if (!text || isSendingRef.current || isListeningRef.current || persistenceStatusRef.current === 'loading') return false;
      if (!navigator.onLine) {
        setError('Sin conexión. Puedes consultar tu progreso, pero no enviar nuevos mensajes.');
        return false;
      }

      ttsProviderRef.current?.stop();
      setIsSpeaking(false);

      const newMessages: ConversationMessage[] = [...messagesRef.current, { role: 'user', text }];
      messagesRef.current = newMessages;
      setMessages(newMessages);
      setInputText('');
      draftSourceRef.current = 'keyboard';
      dictationBaseRef.current = '';
      finalTranscriptRef.current = [];
      latestPartialRef.current = '';
      setError(null);
      setTtsNotice(null);
      setSttNotice(source === 'voice' ? 'Transcripción enviada.' : null);
      isSendingRef.current = true;
      setIsSending(true);
      setOrbState('thinking');

      await persistConversation(newMessages);

      try {
        const learningContext = buildLearningContext(learningMemoryRef.current, pronunciationMemoryRef.current);
        const reply = await sendChatMessage(
          newMessages,
          selectedThemeIdRef.current,
          language.id,
          learningContext,
        );
        const withReply: ConversationMessage[] = [...messagesRef.current, { role: 'assistant', text: reply }];
        const assistantIndex = withReply.length - 1;
        messagesRef.current = withReply;
        setMessages(withReply);
        await persistConversation(withReply);

        if (persistenceStatusRef.current === 'ready') {
          try {
            const activity = await recordProgressTurn(
              language.id,
              selectedThemeIdRef.current,
              source,
              text,
              reply,
            );
            setProgressActivity(activity);
            setProgressStatus('ready');
            setProgressError(null);
          } catch (progressStorageError) {
            setProgressStatus('error');
            setProgressError(
              progressStorageError instanceof Error
                ? progressStorageError.message
                : 'No se ha podido actualizar la actividad de progreso.',
            );
          }
        }

        setLearningStatus('updating');
        learningPipelineRef.current = learningPipelineRef.current
          .catch(() => undefined)
          .then(async () => {
            const analysis = await analyzeLearningTurn(text, reply, selectedThemeIdRef.current, language.id);
            const memory = await applyLearningAnalysis(language.id, text, analysis);
            learningMemoryRef.current = memory;
            setLearningMemory(memory);
            setLearningStatus('ready');
            setLearningError(null);
            void refreshUsage();
          })
          .catch((learningAnalysisError) => {
            setLearningStatus('error');
            setLearningError(
              learningAnalysisError instanceof Error
                ? learningAnalysisError.message
                : 'No se ha podido actualizar la memoria pedagógica.',
            );
            // El análisis pedagógico nunca interrumpe la conversación principal.
            console.warn('Análisis pedagógico no disponible:', learningAnalysisError);
          });

        const freshUsage = (await refreshUsage()) ?? usageRef.current;
        const plan = resolveOutputPlan(voicePreferencesRef.current, freshUsage);

        if (plan.fallbackToReading) {
          setTtsNotice(
            freshUsage && !freshUsage.providers.tts.configured
              ? 'El audio no está disponible. Mostrando la respuesta en texto.'
              : freshUsage && !freshUsage.tts.available
                ? 'El audio no está disponible por ahora. Mostrando la respuesta en texto.'
                : 'Audio desactivado. Mostrando la respuesta en texto.',
          );
        }

        if (!plan.synthesizeAudio) {
          setOrbState('idle');
          return true;
        }

        if (plan.hideText) {
          setHiddenAssistantIndexes((current) => addSetValue(current, assistantIndex));
        }

        setTtsNotice('Preparando audio…');
        const provider = ttsProviderRef.current!;

        let synthesized: SynthesizedAudio;
        try {
          synthesized = await provider.synthesize(reply, { language: language.locale });
          audioCacheRef.current.set(assistantIndex, synthesized);
          setAudioReadyIndexes((current) => addSetValue(current, assistantIndex));
          void refreshUsage();
        } catch (ttsError) {
          if (plan.hideText) {
            setHiddenAssistantIndexes((current) => removeSetValue(current, assistantIndex));
          }
          setTtsNotice(
            `${ttsError instanceof Error ? ttsError.message : 'No se ha podido generar el audio.'} Se muestra la respuesta en texto.`,
          );
          setOrbState('idle');
          void refreshUsage();
          return true;
        }

        setIsSpeaking(true);
        setOrbState('speaking');
        setTtsNotice(
          plan.hideText
            ? 'Listening activo: escucha la respuesta. Puedes mostrar el texto cuando quieras.'
            : 'Reproduciendo respuesta.',
        );

        try {
          await provider.play(synthesized);
        } catch (playbackError) {
          // El audio ya está generado y cacheado: conservamos Listening y ofrecemos reproducción manual.
          setTtsNotice(
            `El audio se ha generado, pero el navegador no lo ha reproducido automáticamente. Pulsa “Escuchar” para reproducirlo.`,
          );
          if (!(playbackError instanceof Error)) {
            console.warn('Error de reproducción TTS:', playbackError);
          }
        } finally {
          setIsSpeaking(false);
          setOrbState('idle');
        }

        return true;
      } catch (requestError) {
        setOrbState('idle');
        setError(requestError instanceof Error ? requestError.message : 'Se ha producido un error inesperado.');
        return false;
      } finally {
        isSendingRef.current = false;
        setIsSending(false);
      }
    },
    [language.id, language.locale, persistConversation, refreshUsage],
  );

  const commitPronunciationSession = useCallback(() => {
    const segments = pronunciationSegmentsRef.current;
    pronunciationSegmentsRef.current = [];
    const summary = summarizePronunciationSegments(segments);
    if (!summary) return;

    setLastPronunciationAssessment(summary);
    setPronunciationStatus('updating');
    setPronunciationError(null);

    if (persistenceStatusRef.current !== 'ready') {
      setPronunciationStatus('ready');
      return;
    }

    void applyPronunciationAssessment(language.id, summary)
      .then((memory) => {
        pronunciationMemoryRef.current = memory;
        setPronunciationMemory(memory);
        setPronunciationStatus('ready');
        setPronunciationError(null);
      })
      .catch((storageError) => {
        setPronunciationStatus('error');
        setPronunciationError(
          storageError instanceof Error
            ? storageError.message
            : 'No se ha podido guardar el resumen de pronunciación.',
        );
      });
  }, [language.id]);

  useEffect(() => {
    void refreshUsage();

    const provider = sttProviderRef.current!;
    const removePartial = provider.onPartialTranscript((partial) => {
      draftSourceRef.current = 'voice';
      latestPartialRef.current = partial;
      setInputText(joinTranscript([dictationBaseRef.current, ...finalTranscriptRef.current, partial]));
    });
    const removeFinal = provider.onFinalTranscript((finalText) => {
      draftSourceRef.current = 'voice';
      finalTranscriptRef.current = [...finalTranscriptRef.current, finalText];
      latestPartialRef.current = '';
      setInputText(joinTranscript([dictationBaseRef.current, ...finalTranscriptRef.current]));
    });
    const removePronunciation = provider.onPronunciationAssessment((assessment) => {
      pronunciationSegmentsRef.current = [...pronunciationSegmentsRef.current, assessment];
    });
    const removeError = provider.onError((message) => {
      setError(message);
    });
    const removeStopped = provider.onStopped((reason: SttStopReason) => {
      isListeningRef.current = false;
      setIsListening(false);
      setOrbState('idle');
      void refreshUsage();
      commitPronunciationSession();

      const transcript = joinTranscript([
        dictationBaseRef.current,
        ...finalTranscriptRef.current,
        latestPartialRef.current,
      ]);
      setInputText(transcript);

      const shouldAutoSubmit =
        voicePreferencesRef.current.voiceSubmitMode === 'auto' &&
        (reason === 'manual' || reason === 'limit') &&
        transcript.length > 0;

      if (shouldAutoSubmit) {
        setSttNotice(
          reason === 'limit'
            ? 'Límite de voz alcanzado. Enviando la transcripción…'
            : 'Transcripción completada. Enviando…',
        );
        void submitTurn(transcript, 'voice');
        return;
      }

      if (reason === 'limit') {
        setSttNotice('La sesión de voz se ha detenido. Puedes enviar o editar la transcripción.');
      } else if (reason === 'manual') {
        setSttNotice(
          transcript
            ? 'Transcripción detenida. Puedes editar el texto o enviarlo cuando quieras.'
            : 'Transcripción detenida. No se ha reconocido ningún texto.',
        );
      } else if (reason === 'service') {
        setSttNotice('La sesión de voz ha finalizado. La transcripción sigue disponible para revisión.');
      }
    });

    return () => {
      removePartial();
      removeFinal();
      removePronunciation();
      removeError();
      removeStopped();
      void provider.stop();
      ttsProviderRef.current?.stop();
    };
  }, [commitPronunciationSession, refreshUsage, submitTurn]);

  const handleSend = (event: React.FormEvent) => {
    event.preventDefault();
    void submitTurn(inputText, draftSourceRef.current);
  };

  const handleToggleMicrophone = async () => {
    const provider = sttProviderRef.current!;

    if (isListeningRef.current) {
      setSttNotice(
        voicePreferencesRef.current.voiceSubmitMode === 'auto'
          ? 'Deteniendo reconocimiento para enviar la transcripción…'
          : 'Deteniendo reconocimiento…',
      );
      await provider.stop();
      return;
    }

    ttsProviderRef.current?.stop();
    setIsSpeaking(false);
    if (!navigator.onLine) {
      setError('Sin conexión. Puedes seguir escribiendo cuando vuelvas a tener Internet.');
      return;
    }
    setError(null);
    setSttNotice(null);
    setTtsNotice(null);

    if (voicePreferences.sttMode === 'text') {
      setError('La entrada de voz está desactivada en Ajustes.');
      return;
    }

    const currentUsage = (await refreshUsage()) ?? usage;
    if (!currentUsage?.providers.stt.configured) {
      setError('La entrada de voz no está disponible en este momento.');
      return;
    }
    if (!currentUsage.stt.available) {
      setError('La entrada de voz no está disponible ahora mismo. Puedes seguir escribiendo.');
      return;
    }

    dictationBaseRef.current = inputText.trim();
    finalTranscriptRef.current = [];
    latestPartialRef.current = '';
    pronunciationSegmentsRef.current = [];
    setLastPronunciationAssessment(null);
    setPronunciationError(null);
    isListeningRef.current = true;
    setIsListening(true);
    setOrbState('listening');
    setSttNotice('Activando micrófono…');

    try {
      await provider.start({
        language: language.locale,
        pronunciationAssessmentMode: voicePreferencesRef.current.pronunciationAssessmentMode,
        phraseHints: buildSpeechPhraseHints(
          learningMemoryRef.current,
          messagesRef.current,
          inputText,
        ),
      });
      setSttNotice(
        voicePreferencesRef.current.voiceSubmitMode === 'auto'
          ? `Escuchando… Pulsa Detener cuando termines; la transcripción se enviará automáticamente${voicePreferencesRef.current.pronunciationAssessmentMode === 'basic' ? ' y evaluaremos tu pronunciación' : ''}.`
          : `Escuchando… Pulsa Detener cuando termines; podrás revisar la transcripción${voicePreferencesRef.current.pronunciationAssessmentMode === 'basic' ? ' y ver la evaluación de pronunciación' : ''}.`,
      );
    } catch (sttError) {
      isListeningRef.current = false;
      setIsListening(false);
      setOrbState('idle');
      setError(sttError instanceof Error ? sttError.message : 'No se ha podido iniciar el reconocimiento de voz.');
      void refreshUsage();
    }
  };

  const resetConversationState = () => {
    ttsProviderRef.current?.stop();
    audioCacheRef.current.clear();
    setAudioReadyIndexes(new Set());
    setHiddenAssistantIndexes(new Set());
    setIsSpeaking(false);
    messagesRef.current = [];
    setMessages([]);
    setInputText('');
    draftSourceRef.current = 'keyboard';
    dictationBaseRef.current = '';
    finalTranscriptRef.current = [];
    latestPartialRef.current = '';
    setError(null);
    setSttNotice(null);
    setTtsNotice(null);
    setLastPronunciationAssessment(null);
    pronunciationSegmentsRef.current = [];
    setOrbState('idle');
  };

  const handleThemeChange = (themeId: number) => {
    if (themeId === selectedThemeIdRef.current) return;
    if (isSendingRef.current || isListeningRef.current) return;

    selectedThemeIdRef.current = themeId;
    setSelectedThemeId(themeId);
    resetConversationState();

    const startedAt = new Date().toISOString();
    sessionStartedAtRef.current = startedAt;

    const nextTheme = language.themes.find((theme) => theme.id === themeId);
    setGeneralNotice(`Tema cambiado a ${nextTheme?.title ?? 'nuevo tema'}. La conversación anterior se ha eliminado.`);
    setMainSection('conversation');

    if (persistenceStatusRef.current === 'ready') {
      void Promise.all([
        saveActiveConversation(language.id, themeId, [], startedAt),
        recordProgressSessionStart(language.id, themeId),
      ])
        .then(([, activity]) => {
          setPersistenceError(null);
          setProgressActivity(activity);
          setProgressStatus('ready');
          setProgressError(null);
        })
        .catch((storageError) => {
          setPersistenceError(
            storageError instanceof Error
              ? storageError.message
              : 'No se ha podido iniciar la nueva conversación local.',
          );
        });
    }
  };

  const handleVoicePreferencesChange = (preferences: VoicePreferences) => {
    voicePreferencesRef.current = preferences;
    setVoicePreferences(preferences);
    saveVoicePreferences(preferences);

    if (persistenceStatusRef.current === 'ready') {
      void saveSetting(STORAGE_SETTING_KEYS.voicePreferences, preferences).catch((storageError) => {
        setPersistenceError(
          storageError instanceof Error
            ? storageError.message
            : 'No se han podido guardar los ajustes.',
        );
      });
    }
  };

  const handleAppearanceModeChange = (mode: AppearanceMode) => {
    setAppearanceMode(mode);
    cacheAppearancePreference(mode);
    applyAppearance(mode);
    if (persistenceStatusRef.current === 'ready') {
      void saveSetting(STORAGE_SETTING_KEYS.appearanceMode, mode).catch(() => undefined);
    }
  };

  const clearConversation = () => {
    if (isSendingRef.current || isListeningRef.current) return;
    resetConversationState();

    const startedAt = new Date().toISOString();
    sessionStartedAtRef.current = startedAt;

    setGeneralNotice('Nueva conversación iniciada. La anterior se ha eliminado; el aprendizaje agregado se conserva.');

    if (persistenceStatusRef.current === 'ready') {
      void Promise.all([
        saveActiveConversation(language.id, selectedThemeIdRef.current, [], startedAt),
        recordProgressSessionStart(language.id, selectedThemeIdRef.current),
      ])
        .then(([, activity]) => {
          setPersistenceError(null);
          setProgressActivity(activity);
          setProgressStatus('ready');
          setProgressError(null);
        })
        .catch((storageError) => {
          setPersistenceError(
            storageError instanceof Error
              ? storageError.message
              : 'No se ha podido reiniciar la conversación local.',
          );
        });
    }
  };

  const handleClearLearningMemory = async () => {
    if (isSendingRef.current || isListeningRef.current) return;
    if (!window.confirm('¿Borrar la memoria pedagógica agregada de este idioma? La conversación activa no se borrará.')) return;

    try {
      await clearLearningMemory(language.id);
      const emptyMemory: LearningMemorySnapshot = { vocabulary: [], evidence: [] };
      learningMemoryRef.current = emptyMemory;
      setLearningMemory(emptyMemory);
      setLearningStatus('ready');
      setLearningError(null);
    } catch (storageError) {
      setLearningStatus('error');
      setLearningError(
        storageError instanceof Error ? storageError.message : 'No se ha podido borrar la memoria pedagógica.',
      );
    }
  };

  const handleClearPronunciationMemory = async () => {
    if (isSendingRef.current || isListeningRef.current) return;
    if (!window.confirm('¿Borrar la memoria agregada de pronunciación de este idioma?')) return;

    try {
      await clearPronunciationMemory(language.id);
      const emptyMemory = emptyPronunciationMemory(language.id);
      pronunciationMemoryRef.current = emptyMemory;
      setPronunciationMemory(emptyMemory);
      setLastPronunciationAssessment(null);
      setPronunciationStatus('ready');
      setPronunciationError(null);
    } catch (storageError) {
      setPronunciationStatus('error');
      setPronunciationError(
        storageError instanceof Error ? storageError.message : 'No se ha podido borrar la memoria de pronunciación.',
      );
    }
  };

  const handleClearProgressActivity = async () => {
    if (isSendingRef.current || isListeningRef.current) return;
    if (!window.confirm('¿Borrar los agregados diarios de actividad? El aprendizaje, la pronunciación y la conversación activa se conservarán.')) return;

    try {
      await clearProgressActivity(language.id);
      setProgressActivity({ daily: [] });
      setProgressStatus('ready');
      setProgressError(null);
    } catch (storageError) {
      setProgressStatus('error');
      setProgressError(storageError instanceof Error ? storageError.message : 'No se ha podido borrar la actividad.');
    }
  };

  const handleInstallPwa = () => {
    void pwaInstall.install().then((result) => {
      if (result === 'accepted') setGeneralNotice('Mural se ha añadido como aplicación.');
    });
  };

  const sttDisabled =
    !isOnline ||
    persistenceStatus === 'loading' ||
    isSending ||
    (!isListening &&
      (voicePreferences.sttMode === 'text' ||
        usage === null ||
        !usage.providers.stt.configured ||
        !usage.stt.available));

  const sttButtonTitle = !isOnline
    ? 'Sin conexión: la voz necesita Internet'
    : isListening
      ? voicePreferences.voiceSubmitMode === 'auto'
        ? 'Detener y enviar'
        : 'Detener reconocimiento de voz'
      : voicePreferences.sttMode === 'text'
        ? 'La entrada de voz está desactivada en Ajustes'
        : usage && !usage.providers.stt.configured
          ? 'Voz no disponible'
          : usage && !usage.stt.available
            ? 'Voz no disponible'
            : 'Hablar';



  return (
    <div className="app-shell">
      <div className={`app-frame ${mainSection === 'conversation' && messages.length > 0 ? 'app-frame--conversation-active' : ''}`}>
        <header className="app-header">
          <button type="button" className="brand-mark" onClick={() => setMainSection('conversation')} aria-label="Ir a conversación">
            <span className="brand-mark__dot" aria-hidden="true" />
            <span>mural</span>
          </button>

          <div className="app-header__actions">
            {!isOnline && <span className="offline-pill">Offline</span>}
            <button
              type="button"
              onClick={() => setSettingsOpen(true)}
              disabled={isListening}
              className="icon-button icon-button--strong"
              aria-label="Ajustes"
            >
              <AppIcon name="settings" size={22} />
            </button>
          </div>
        </header>

        {mainSection === 'conversation' && (
          <div className="theme-pill-row">
            <button
              type="button"
              className="theme-pill"
              onClick={() => setThemePickerOpen(true)}
              disabled={isSending || isListening}
              title="Cambiar de tema reinicia la conversación actual"
            >
              <span>{selectedTheme.title}</span>
              <span className="theme-pill__chevron" aria-hidden="true"><AppIcon name="chevronDown" size={16} strokeWidth={1.4} /></span>
            </button>
          </div>
        )}

        <div className="notice-stack" aria-live="polite">
          {!isOnline && (
            <div className="soft-notice">
              Sin conexión. Tu progreso sigue disponible.
            </div>
          )}
          {generalNotice && (
            <div className="soft-notice soft-notice--dismissible">
              <span>{generalNotice}</span>
              <button type="button" onClick={() => setGeneralNotice(null)} aria-label="Cerrar aviso"><AppIcon name="close" size={16} /></button>
            </div>
          )}
        </div>

        {mainSection === 'conversation' ? (
          <>
            <main className="talk-screen">
              <ConversationOrb
                state={orbState}
                onClick={sttDisabled ? undefined : () => void handleToggleMicrophone()}
                showLabel={messages.length === 0 || orbState !== 'idle'}
              />

              {messages.length === 0 && (
                <section className="conversation-hero" aria-live="polite">
                  <p className="conversation-hero__kicker">Speak English whenever you want</p>
                  <h1>Hi.</h1>
                  <p>Habla o escribe cuando quieras.</p>
                </section>
              )}

              <section className={`conversation-stream ${messages.length === 0 ? 'is-empty' : ''}`}>
                {messages.length > 0 && (
                  <div className="message-list" aria-live="polite">
                    {messages.map((message, index) => {
                      const isAssistant = message.role === 'assistant';
                      const hidden = isAssistant && hiddenAssistantIndexes.has(index);
                      const hasAudio = isAssistant && audioReadyIndexes.has(index);

                      return (
                        <article key={`${message.role}-${index}`} className={`message-bubble message-bubble--${message.role}`}>
                          <span className="message-bubble__role">{isAssistant ? 'Mural' : 'Tú'}</span>
                          {hidden ? (
                            <div>
                              <p className="message-muted">Respuesta oculta para practicar listening.</p>
                              <div className="message-actions">
                                {hasAudio && (
                                  <button type="button" onClick={() => void playCachedAudio(index)} disabled={isSending || isListening || isSpeaking}>
                                    <AppIcon name="play" size={14} /> Escuchar
                                  </button>
                                )}
                                <button type="button" onClick={() => setHiddenAssistantIndexes((current) => removeSetValue(current, index))}>Mostrar texto</button>
                              </div>
                            </div>
                          ) : (
                            <div>
                              <p className="message-bubble__text">{message.text}</p>
                              {hasAudio && (
                                <button type="button" className="message-audio" onClick={() => void playCachedAudio(index)} disabled={isSending || isListening || isSpeaking}>
                                  <AppIcon name="play" size={13} /> Repetir audio
                                </button>
                              )}
                            </div>
                          )}
                        </article>
                      );
                    })}
                  </div>
                )}
              </section>

              {lastPronunciationAssessment && voicePreferences.pronunciationAssessmentMode === 'basic' && (
                <section className="pronunciation-strip">
                  <div><span>Pronunciation</span><strong>{Math.round(lastPronunciationAssessment.pronunciationScore)}</strong></div>
                  <div><span>Accuracy</span><strong>{Math.round(lastPronunciationAssessment.accuracyScore)}</strong></div>
                  <div><span>Fluency</span><strong>{Math.round(lastPronunciationAssessment.fluencyScore)}</strong></div>
                  {lastPronunciationAssessment.weakWords.length > 0 && (
                    <p>Review: {lastPronunciationAssessment.weakWords.slice(0, 4).map((word) => word.word).join(' · ')}</p>
                  )}
                </section>
              )}

              {(persistenceError || error || pronunciationError) && (
                <div className="error-stack">
                  {persistenceError && <div className="error-note">{persistenceError}</div>}
                  {error && <div className="error-note">{error}</div>}
                  {pronunciationError && <div className="error-note">{pronunciationError}</div>}
                </div>
              )}
            </main>

            <section className="voice-controls" aria-label="Conversation controls">
              <button
                type="button"
                className="side-action"
                onClick={clearConversation}
                disabled={messages.length === 0 || isSending || isListening || persistenceStatus === 'loading'}
              >
                <span className="side-action__icon"><AppIcon name="newConversation" /></span>
                <span>New</span>
              </button>

              <button
                type="button"
                onClick={() => void handleToggleMicrophone()}
                disabled={sttDisabled}
                title={sttButtonTitle}
                className={`microphone-button ${isListening ? 'is-listening' : ''}`}
                aria-label={isListening ? 'Stop microphone' : 'Talk'}
              >
                {isListening ? <span className="stop-mark" /> : <AppIcon name="talk" size={32} strokeWidth={1.65} />}
              </button>

              <button type="button" className="side-action" onClick={() => inputRef.current?.focus()} disabled={isSending || isListening}>
                <span className="side-action__icon"><AppIcon name="keyboard" /></span>
                <span>Write</span>
              </button>
            </section>

            <p className="microphone-caption">
              {isListening ? 'Microphone on' : voicePreferences.sttMode === 'text' ? 'Voice input off' : 'Microphone off'}
            </p>

            <footer className="composer-zone">
              <form onSubmit={handleSend} className="minimal-composer">
                <textarea
                  ref={inputRef}
                  value={inputText}
                  onChange={(event) => setInputText(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault();
                      if (inputText.trim() && !isSending && !isListening && isOnline) void submitTurn(inputText, draftSourceRef.current);
                    }
                  }}
                  rows={1}
                  placeholder={isListening ? 'Transcribing…' : isSending ? 'Waiting for response…' : 'Write something…'}
                  disabled={persistenceStatus === 'loading' || isSending || isListening}
                  aria-label="Message for Mural"
                />
                <button
                  type="submit"
                  className="composer-send"
                  disabled={!isOnline || persistenceStatus === 'loading' || isSending || isListening || !inputText.trim()}
                  aria-label="Send"
                >
                  <AppIcon name="send" size={19} />
                </button>
              </form>
              {(sttNotice || ttsNotice) && (
                <div className="inline-status" aria-live="polite">{sttNotice || ttsNotice}</div>
              )}
            </footer>
          </>
        ) : mainSection === 'words' ? (
          <main className="secondary-screen"><WordsView memory={learningMemory} /></main>
        ) : (
          <main className="secondary-screen">
            <ProgressDashboard
              overview={progressOverview}
              status={progressStatus}
              error={progressError}
              onClearActivity={() => void handleClearProgressActivity()}
              clearDisabled={isSending || isListening}
            />
          </main>
        )}

        <nav className="bottom-dock" aria-label="Navegación principal">
          <button type="button" className={mainSection === 'conversation' && !themePickerOpen ? 'is-active' : ''} onClick={() => { setMainSection('conversation'); setThemePickerOpen(false); }}>
            <AppIcon name="talk" /><span>Talk</span>
          </button>
          <button type="button" className={themePickerOpen ? 'is-active' : ''} onClick={() => setThemePickerOpen(true)}>
            <AppIcon name="themes" /><span>Themes</span>
          </button>
          <button type="button" className={mainSection === 'words' ? 'is-active' : ''} onClick={() => { setMainSection('words'); setThemePickerOpen(false); }}>
            <AppIcon name="words" /><span>Words</span>
          </button>
          <button type="button" className={mainSection === 'progress' ? 'is-active' : ''} onClick={() => { setMainSection('progress'); setThemePickerOpen(false); }}>
            <AppIcon name="progress" /><span>Progress</span>
          </button>
        </nav>
      </div>

      <ThemePickerSheet
        open={themePickerOpen}
        themes={language.themes}
        selectedThemeId={selectedThemeId}
        disabled={isSending || isListening}
        onSelect={handleThemeChange}
        onClose={() => setThemePickerOpen(false)}
      />

      <SettingsModal
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        themes={language.themes}
        selectedThemeId={selectedThemeId}
        onSelectTheme={handleThemeChange}
        themeChangeDisabled={isSending || isListening}
        persistenceStatus={persistenceStatus}
        persistedMessageCount={messages.length}
        learningMemory={learningMemory}
        learningStatus={learningStatus}
        learningError={learningError}
        onClearLearningMemory={() => void handleClearLearningMemory()}
        learningResetDisabled={isSending || isListening}
        pronunciationMemory={pronunciationMemory}
        pronunciationStatus={pronunciationStatus}
        pronunciationError={pronunciationError}
        onClearPronunciationMemory={() => void handleClearPronunciationMemory()}
        pronunciationResetDisabled={isSending || isListening}
        voicePreferences={voicePreferences}
        onUpdateVoicePreferences={handleVoicePreferencesChange}
        pwaCanInstall={pwaInstall.canInstall}
        pwaIsIos={pwaInstall.isIos}
        pwaIsStandalone={pwaInstall.isStandalone}
        pwaInstalled={pwaInstall.installed}
        onInstallPwa={handleInstallPwa}
        appearanceMode={appearanceMode}
        onAppearanceModeChange={handleAppearanceModeChange}
      />
    </div>
  );
};
