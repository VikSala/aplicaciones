import React, { useEffect, useState } from 'react';
import type { ConversationTheme } from '../core/types';
import type { LearningMemorySnapshot } from '../learning/types';
import type { PronunciationMemorySnapshot } from '../pronunciation/types';
import type { VoicePreferences } from '../voice/types';
import { fetchUsageSnapshot, type UsageSnapshot } from '../services/usageService';
import type { AppearanceMode } from '../theme/appearance';
import { AppIcon } from './AppIcon';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  themes: ConversationTheme[];
  selectedThemeId: number;
  onSelectTheme: (themeId: number) => void;
  themeChangeDisabled: boolean;
  persistenceStatus: 'loading' | 'ready' | 'unavailable';
  persistedMessageCount: number;
  learningMemory: LearningMemorySnapshot;
  learningStatus: 'loading' | 'ready' | 'updating' | 'error';
  learningError: string | null;
  onClearLearningMemory: () => void;
  learningResetDisabled: boolean;
  pronunciationMemory: PronunciationMemorySnapshot;
  pronunciationStatus: 'loading' | 'ready' | 'updating' | 'error';
  pronunciationError: string | null;
  onClearPronunciationMemory: () => void;
  pronunciationResetDisabled: boolean;
  voicePreferences: VoicePreferences;
  onUpdateVoicePreferences: (preferences: VoicePreferences) => void;
  pwaCanInstall: boolean;
  pwaIsIos: boolean;
  pwaIsStandalone: boolean;
  pwaInstalled: boolean;
  onInstallPwa: () => void;
  appearanceMode: AppearanceMode;
  onAppearanceModeChange: (mode: AppearanceMode) => void;
}

function formatDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);

  if (hours > 0) return `${hours} h ${minutes} min`;
  return `${minutes} min`;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat('es-ES').format(Math.max(0, Math.round(value)));
}

function UsageBar({ percentage }: { percentage: number }) {
  const safePercentage = Math.max(0, Math.min(100, percentage));

  return (
    <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-800" aria-hidden="true">
      <div className="h-full rounded-full bg-indigo-500 transition-all" style={{ width: `${safePercentage}%` }} />
    </div>
  );
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  themes,
  selectedThemeId,
  onSelectTheme,
  themeChangeDisabled,
  persistenceStatus,
  persistedMessageCount,
  learningMemory,
  learningStatus,
  learningError,
  onClearLearningMemory,
  learningResetDisabled,
  pronunciationMemory,
  pronunciationStatus,
  pronunciationError,
  onClearPronunciationMemory,
  pronunciationResetDisabled,
  voicePreferences,
  onUpdateVoicePreferences,
  pwaCanInstall,
  pwaIsIos,
  pwaIsStandalone,
  pwaInstalled,
  onInstallPwa,
  appearanceMode,
  onAppearanceModeChange,
}) => {
  const [usage, setUsage] = useState<UsageSnapshot | null>(null);
  const [usageError, setUsageError] = useState<string | null>(null);
  const [loadingUsage, setLoadingUsage] = useState(false);

  useEffect(() => {
    if (!isOpen) return;

    let cancelled = false;
    setLoadingUsage(true);
    setUsageError(null);

    fetchUsageSnapshot()
      .then((snapshot) => {
        if (!cancelled) setUsage(snapshot);
      })
      .catch((error) => {
        if (!cancelled) {
          setUsageError(error instanceof Error ? error.message : 'No se ha podido cargar el uso.');
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingUsage(false);
      });

    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const updatePreference = <K extends keyof VoicePreferences>(key: K, value: VoicePreferences[K]) => {
    onUpdateVoicePreferences({ ...voicePreferences, [key]: value });
  };

  return (
    <div className="settings-backdrop">
      <div className="settings-panel">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">Ajustes</h2>
            <p className="mt-1 text-sm text-slate-400">Personaliza tu experiencia.</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="icon-button"
            aria-label="Cerrar ajustes"
          >
            <AppIcon name="close" />
          </button>
        </div>

        <div className="space-y-6">
          <section className="appearance-section">
            <label className="settings-kicker">Apariencia</label>
            <div className="appearance-switch" role="group" aria-label="Apariencia">
              {([
                ['system', 'auto', 'Automático'],
                ['light', 'sun', 'Claro'],
                ['dark', 'moon', 'Oscuro'],
              ] as const).map(([mode, icon, label]) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => onAppearanceModeChange(mode)}
                  className={`appearance-option ${appearanceMode === mode ? 'is-active' : ''}`}
                >
                  <AppIcon name={icon} size={18} />
                  <span>{label}</span>
                </button>
              ))}
            </div>
            <p className="settings-help">Automático usa la apariencia de tu dispositivo.</p>
          </section>

          <section>
            <label className="mb-2 block text-xs font-semibold uppercase tracking-wider text-slate-400">Idioma</label>
            <div className="rounded-xl border border-slate-800 bg-slate-950 px-4 py-3 text-sm">
              <span className="font-medium text-white">Español → Inglés</span>
              <p className="mt-1 text-xs text-slate-500">Más idiomas próximamente.</p>
            </div>
          </section>

          <section>
            <label htmlFor="theme" className="mb-2 block text-xs font-semibold uppercase tracking-wider text-slate-400">Tema</label>
            <select
              id="theme"
              value={selectedThemeId}
              onChange={(event) => onSelectTheme(Number(event.target.value))}
              disabled={themeChangeDisabled}
              className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-indigo-500"
            >
              {themes.map((theme) => (
                <option key={theme.id} value={theme.id}>{theme.title}</option>
              ))}
            </select>
            <p className="mt-2 text-[11px] leading-4 text-slate-500">
              Cambiar de tema empieza una conversación nueva.
            </p>
          </section>

          <section className="rounded-xl border border-slate-800 bg-slate-950 p-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">Persistencia local</h3>
                <p className="mt-1 text-sm text-slate-200">{persistedMessageCount} mensajes guardados en este dispositivo</p>
              </div>
              <span className={`text-[10px] ${persistenceStatus === 'ready' ? 'text-emerald-400' : persistenceStatus === 'loading' ? 'text-slate-400' : 'text-amber-400'}`}>
                {persistenceStatus === 'ready' ? 'Activa' : persistenceStatus === 'loading' ? 'Cargando' : 'No disponible'}
              </span>
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-500">
              Se guardan el tema actual, la conversación activa, el progreso y tus ajustes.
            </p>
          </section>


          <section className="rounded-xl border border-indigo-900/50 bg-indigo-950/20 p-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-indigo-300">Memoria pedagógica</h3>
                <p className="mt-1 text-sm text-slate-200">{learningMemory.vocabulary.length} elementos de vocabulario · {learningMemory.evidence.length} puntos de aprendizaje</p>
              </div>
              <span className={`text-[10px] ${learningStatus === 'ready' ? 'text-emerald-400' : learningStatus === 'updating' ? 'text-indigo-300' : learningStatus === 'loading' ? 'text-slate-400' : 'text-amber-400'}`}>
                {learningStatus === 'ready' ? 'Activa' : learningStatus === 'updating' ? 'Actualizando' : learningStatus === 'loading' ? 'Cargando' : 'Con aviso'}
              </span>
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-500">
              Resume tu vocabulario y los puntos que conviene reforzar.
            </p>
            {learningError && (
              <p className="mt-2 text-[11px] leading-4 text-amber-300">{learningError}</p>
            )}
            <button
              type="button"
              onClick={onClearLearningMemory}
              disabled={learningResetDisabled || learningStatus === 'loading' || learningStatus === 'updating'}
              className="mt-3 rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-300 transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Borrar memoria pedagógica
            </button>
          </section>

          <section className="rounded-xl border border-cyan-900/50 bg-cyan-950/20 p-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-cyan-300">Pronunciación</h3>
                <p className="mt-1 text-sm text-slate-200">
                  {pronunciationMemory.assessmentCount} evaluaciones · precisión media {Math.round(pronunciationMemory.averageAccuracy)}/100 · fluidez {Math.round(pronunciationMemory.averageFluency)}/100
                </p>
              </div>
              <span className={`text-[10px] ${pronunciationStatus === 'ready' ? 'text-emerald-400' : pronunciationStatus === 'updating' ? 'text-cyan-300' : pronunciationStatus === 'loading' ? 'text-slate-400' : 'text-amber-400'}`}>
                {pronunciationStatus === 'ready' ? 'Activa' : pronunciationStatus === 'updating' ? 'Actualizando' : pronunciationStatus === 'loading' ? 'Cargando' : 'Con aviso'}
              </span>
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-500">
              Guarda un resumen de tus últimas evaluaciones de voz.
            </p>
            {pronunciationMemory.weakWords.length > 0 && (
              <div className="mt-3 rounded-lg border border-slate-800 bg-slate-950/70 p-3">
                <p className="text-[11px] font-medium text-slate-300">Palabras a vigilar</p>
                <p className="mt-1 text-[11px] leading-5 text-slate-500">
                  {pronunciationMemory.weakWords.slice(0, 8).map((item) => `${item.word} (${Math.round(item.averageAccuracy)}/100)`).join(' · ')}
                </p>
              </div>
            )}
            {pronunciationError && (
              <p className="mt-2 text-[11px] leading-4 text-amber-300">{pronunciationError}</p>
            )}
            <button
              type="button"
              onClick={onClearPronunciationMemory}
              disabled={pronunciationResetDisabled || pronunciationStatus === 'loading' || pronunciationStatus === 'updating'}
              className="mt-3 rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-300 transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Borrar memoria de pronunciación
            </button>
          </section>

          <section>
            <div className="mb-3 flex items-end justify-between gap-4">
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">Control de uso</h3>
                <p className="mt-1 text-xs text-slate-500">Referencia de uso del mes.</p>
              </div>
              {usage && <span className="text-[11px] text-slate-600">{usage.period}</span>}
            </div>

            {loadingUsage && <div className="rounded-xl border border-slate-800 bg-slate-950 p-4 text-sm text-slate-400">Cargando uso…</div>}
            {usageError && <div className="rounded-xl border border-red-900/60 bg-red-950/40 p-3 text-sm text-red-200">{usageError}</div>}

            {usage && (
              <div className="grid gap-3 md:grid-cols-3">
                <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold text-white">Voz</span>
                    <span className={`text-[10px] ${usage.stt.available ? 'text-emerald-400' : 'text-amber-400'}`}>
                      {!usage.providers.stt.configured ? 'No disponible' : usage.stt.available ? 'Disponible' : 'Límite'}
                    </span>
                  </div>
                  <p className="mt-2 text-lg font-semibold">{formatDuration(usage.stt.usedSeconds)} <span className="text-xs font-normal text-slate-500">/ {formatDuration(usage.stt.freeLimitSeconds)}</span></p>
                  <UsageBar percentage={usage.stt.percentage} />
                  <p className="mt-2 text-[11px] text-slate-500">Disponible: {formatDuration(usage.stt.remainingSeconds)}</p>
                  {usage.providers.stt.maxSessionSeconds && (
                    <p className="mt-1 text-[11px] text-slate-600">Máximo por sesión: {formatDuration(usage.providers.stt.maxSessionSeconds)} · {usage.providers.stt.region || 'región no disponible'}</p>
                  )}
                </div>

                <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold text-white">Audio</span>
                    <span className={`text-[10px] ${usage.tts.available ? 'text-emerald-400' : 'text-amber-400'}`}>
                      {!usage.providers.tts.configured ? 'No disponible' : usage.tts.available ? 'Disponible' : 'Límite'}
                    </span>
                  </div>
                  <p className="mt-2 text-lg font-semibold">{formatNumber(usage.tts.usedCharacters)} <span className="text-xs font-normal text-slate-500">/ {formatNumber(usage.tts.freeLimitCharacters)}</span></p>
                  <UsageBar percentage={usage.tts.percentage} />
                  <p className="mt-2 text-[11px] text-slate-500">Disponible: {formatNumber(usage.tts.remainingCharacters)} caracteres</p>
                  {usage.providers.tts.configured && (
                    <p className="mt-1 break-all text-[11px] text-slate-600">{usage.providers.tts.voice || 'Voz predeterminada'}</p>
                  )}
                </div>

                <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold text-white">IA</span>
                    <span className="text-[10px] text-slate-500">Estimación</span>
                  </div>
                  <p className="mt-2 text-lg font-semibold">${usage.llm.estimatedCostUsd.toFixed(4)} <span className="text-xs font-normal text-slate-500">/ ref. ${usage.llm.referenceCreditUsd.toFixed(2)}</span></p>
                  <UsageBar percentage={usage.llm.percentageOfReference} />
                  <p className="mt-2 text-[11px] text-slate-500">{formatNumber(usage.llm.inputTokens)} entrada · {formatNumber(usage.llm.outputTokens)} salida</p>
                </div>
              </div>
            )}

            {usage && (
              <p className="mt-2 text-[11px] leading-4 text-slate-600">
                Cálculo orientativo con margen de seguridad.
              </p>
            )}
          </section>

          <section>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">Comportamiento de voz</h3>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="text-xs text-slate-400">
                Entrada
                <select
                  value={voicePreferences.sttMode}
                  onChange={(event) => updatePreference('sttMode', event.target.value as VoicePreferences['sttMode'])}
                  className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="auto">Automático</option>
                  <option value="azure">Voz</option>
                  <option value="text">Solo texto</option>
                </select>
              </label>

              <label className="text-xs text-slate-400">
                Al terminar de hablar
                <select
                  value={voicePreferences.voiceSubmitMode}
                  onChange={(event) => updatePreference('voiceSubmitMode', event.target.value as VoicePreferences['voiceSubmitMode'])}
                  className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="manual">Revisar antes de enviar</option>
                  <option value="auto">Enviar automáticamente</option>
                </select>
              </label>

              <label className="text-xs text-slate-400">
                Evaluación de pronunciación
                <select
                  value={voicePreferences.pronunciationAssessmentMode}
                  onChange={(event) => updatePreference('pronunciationAssessmentMode', event.target.value as VoicePreferences['pronunciationAssessmentMode'])}
                  className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="basic">Básica (Accuracy + Fluency)</option>
                  <option value="off">Desactivada</option>
                </select>
              </label>

              <label className="text-xs text-slate-400">
                Salida
                <select
                  value={voicePreferences.ttsMode}
                  onChange={(event) => updatePreference('ttsMode', event.target.value as VoicePreferences['ttsMode'])}
                  className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="auto">Automático</option>
                  <option value="google">Audio</option>
                  <option value="text">Sin audio</option>
                </select>
              </label>

              <label className="text-xs text-slate-400">
                Respuesta
                <select
                  value={voicePreferences.responseDisplayMode}
                  onChange={(event) => updatePreference('responseDisplayMode', event.target.value as VoicePreferences['responseDisplayMode'])}
                  className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="auto">Automático</option>
                  <option value="listening">Listening</option>
                  <option value="reading">Reading</option>
                  <option value="mixed">Audio + texto</option>
                </select>
              </label>
            </div>
            <p className="mt-2 text-[11px] leading-4 text-slate-600">
              Listening prioriza el audio, Reading muestra solo texto y Mixto combina ambos.
            </p>
          </section>


          <section className="rounded-xl border border-slate-800 bg-slate-950 p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">Aplicación instalable</h3>
                <p className="mt-1 text-sm text-slate-200">Acceso rápido desde móvil o escritorio</p>
                <p className="mt-2 text-xs leading-5 text-slate-500">
                  Puedes abrir Mural como app desde tu dispositivo.
                </p>
              </div>
              {pwaIsStandalone || pwaInstalled ? (
                <span className="rounded-lg border border-emerald-900/50 bg-emerald-950/30 px-3 py-2 text-xs text-emerald-300">Instalada</span>
              ) : pwaCanInstall ? (
                <button type="button" onClick={onInstallPwa} className="rounded-xl bg-indigo-600 px-4 py-2 text-xs font-medium text-white transition hover:bg-indigo-500">
                  Instalar Mural
                </button>
              ) : pwaIsIos ? (
                <span className="max-w-xs text-xs leading-5 text-slate-400">En iPhone/iPad: Compartir → Añadir a pantalla de inicio.</span>
              ) : (
                <span className="text-xs text-slate-500">El navegador ofrecerá instalación cuando cumpla los requisitos.</span>
              )}
            </div>
          </section>


          <div className="flex justify-end">
            <button type="button" onClick={onClose} className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500">
              Cerrar
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
