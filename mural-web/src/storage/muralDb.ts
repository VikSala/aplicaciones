import type { ConversationMessage } from '../core/types';
import type { PronunciationAssessmentSummary, PronunciationMemorySnapshot } from '../pronunciation/types';
import type { DailyProgressRecord, ProgressActivitySnapshot } from '../progress/types';
import { countWords } from '../progress/analytics';
import { emptyPronunciationMemory } from '../pronunciation/memory';
import type {
  LearningEvidenceItem,
  LearningMemorySnapshot,
  TurnLearningAnalysis,
  VocabularyMemoryItem,
} from '../learning/types';

const DB_NAME = 'mural-web';
const DB_VERSION = 3;
const ACTIVE_SESSION_ID = 'active';
const MAX_VOCABULARY_ITEMS = 80;
const MAX_EVIDENCE_ITEMS = 60;
const MAX_RECENT_EXAMPLES = 3;
const MAX_PRONUNCIATION_WEAK_WORDS = 60;
const MAX_PROGRESS_DAYS = 120;

const STORES = {
  sessions: 'sessions',
  messages: 'messages',
  settings: 'settings',
  vocabulary: 'vocabulary',
  learningEvidence: 'learningEvidence',
  pronunciation: 'pronunciation',
  progressDaily: 'progressDaily',
} as const;

export const STORAGE_SETTING_KEYS = {
  voicePreferences: 'voice-preferences',
  appearanceMode: 'appearance-mode',
} as const;

interface PersistedSession {
  id: typeof ACTIVE_SESSION_ID;
  languageId: string;
  themeId: number;
  startedAt: string;
  updatedAt: string;
}

interface PersistedMessage extends ConversationMessage {
  id?: number;
  sessionId: typeof ACTIVE_SESSION_ID;
  position: number;
  createdAt: string;
}

interface PersistedSetting<T = unknown> {
  key: string;
  value: T;
  updatedAt: string;
}

export interface ActiveConversationSnapshot {
  languageId: string;
  themeId: number;
  startedAt: string;
  updatedAt: string;
  messages: ConversationMessage[];
}

let dbPromise: Promise<IDBDatabase> | null = null;

function openDatabase(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;

  dbPromise = new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('IndexedDB no está disponible en este navegador.'));
      return;
    }

    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = () => {
      const db = request.result;

      if (!db.objectStoreNames.contains(STORES.sessions)) {
        db.createObjectStore(STORES.sessions, { keyPath: 'id' });
      }

      if (!db.objectStoreNames.contains(STORES.messages)) {
        const messages = db.createObjectStore(STORES.messages, { keyPath: 'id', autoIncrement: true });
        messages.createIndex('sessionId', 'sessionId', { unique: false });
        messages.createIndex('position', 'position', { unique: false });
      }

      if (!db.objectStoreNames.contains(STORES.settings)) {
        db.createObjectStore(STORES.settings, { keyPath: 'key' });
      }

      if (!db.objectStoreNames.contains(STORES.vocabulary)) {
        db.createObjectStore(STORES.vocabulary, { keyPath: 'id' });
      }

      if (!db.objectStoreNames.contains(STORES.learningEvidence)) {
        db.createObjectStore(STORES.learningEvidence, { keyPath: 'id' });
      }

      if (!db.objectStoreNames.contains(STORES.pronunciation)) {
        db.createObjectStore(STORES.pronunciation, { keyPath: 'languageId' });
      }

      if (!db.objectStoreNames.contains(STORES.progressDaily)) {
        db.createObjectStore(STORES.progressDaily, { keyPath: 'id' });
      }
    };

    request.onsuccess = () => {
      const db = request.result;
      db.onversionchange = () => db.close();
      resolve(db);
    };

    request.onerror = () => {
      dbPromise = null;
      reject(request.error ?? new Error('No se ha podido abrir IndexedDB.'));
    };

    request.onblocked = () => {
      dbPromise = null;
      reject(new Error('La base local de Mural está bloqueada por otra pestaña.'));
    };
  });

  return dbPromise;
}

function requestAsPromise<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('Error de IndexedDB.'));
  });
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onabort = () => reject(transaction.error ?? new Error('La transacción local se ha cancelado.'));
    transaction.onerror = () => reject(transaction.error ?? new Error('Error guardando datos locales.'));
  });
}

function safeIdPart(value: string): string {
  return value.trim().toLocaleLowerCase().replace(/[^a-z0-9áéíóúüñ_-]+/gi, '-').replace(/^-+|-+$/g, '').slice(0, 80);
}

function clampConfidence(value: number | undefined): number {
  if (!Number.isFinite(value)) return 1;
  return Math.max(0, Math.min(1, Number(value)));
}

export async function loadActiveConversation(): Promise<ActiveConversationSnapshot | null> {
  const db = await openDatabase();
  const transaction = db.transaction([STORES.sessions, STORES.messages], 'readonly');
  const done = transactionDone(transaction);
  const sessionRequest = transaction.objectStore(STORES.sessions).get(ACTIVE_SESSION_ID);
  const messagesRequest = transaction.objectStore(STORES.messages).getAll();

  const [session, storedMessages] = await Promise.all([
    requestAsPromise(sessionRequest) as Promise<PersistedSession | undefined>,
    requestAsPromise(messagesRequest) as Promise<PersistedMessage[]>,
  ]);
  await done;

  if (!session) return null;

  const messages = storedMessages
    .filter((message) => message.sessionId === ACTIVE_SESSION_ID)
    .sort((a, b) => a.position - b.position)
    .map(({ role, text }) => ({ role, text }));

  return {
    languageId: session.languageId,
    themeId: session.themeId,
    startedAt: session.startedAt,
    updatedAt: session.updatedAt,
    messages,
  };
}

export async function saveActiveConversation(
  languageId: string,
  themeId: number,
  messages: ConversationMessage[],
  startedAt: string,
): Promise<void> {
  const db = await openDatabase();
  const transaction = db.transaction([STORES.sessions, STORES.messages], 'readwrite');
  const now = new Date().toISOString();

  transaction.objectStore(STORES.sessions).put({
    id: ACTIVE_SESSION_ID,
    languageId,
    themeId,
    startedAt,
    updatedAt: now,
  } satisfies PersistedSession);

  const messageStore = transaction.objectStore(STORES.messages);
  messageStore.clear();
  messages.forEach((message, position) => {
    messageStore.add({
      sessionId: ACTIVE_SESSION_ID,
      position,
      role: message.role,
      text: message.text,
      createdAt: now,
    } satisfies PersistedMessage);
  });

  await transactionDone(transaction);
}

export async function resetActiveConversation(languageId: string, themeId: number): Promise<string> {
  const startedAt = new Date().toISOString();
  await saveActiveConversation(languageId, themeId, [], startedAt);
  return startedAt;
}

export async function loadSetting<T>(key: string): Promise<T | null> {
  const db = await openDatabase();
  const transaction = db.transaction(STORES.settings, 'readonly');
  const done = transactionDone(transaction);
  const record = await requestAsPromise(
    transaction.objectStore(STORES.settings).get(key),
  ) as PersistedSetting<T> | undefined;
  await done;
  return record?.value ?? null;
}

export async function saveSetting<T>(key: string, value: T): Promise<void> {
  const db = await openDatabase();
  const transaction = db.transaction(STORES.settings, 'readwrite');
  transaction.objectStore(STORES.settings).put({
    key,
    value,
    updatedAt: new Date().toISOString(),
  } satisfies PersistedSetting<T>);
  await transactionDone(transaction);
}

export async function loadLearningMemory(languageId: string): Promise<LearningMemorySnapshot> {
  const db = await openDatabase();
  const transaction = db.transaction([STORES.vocabulary, STORES.learningEvidence], 'readonly');
  const done = transactionDone(transaction);

  const [allVocabulary, allEvidence] = await Promise.all([
    requestAsPromise(transaction.objectStore(STORES.vocabulary).getAll()) as Promise<VocabularyMemoryItem[]>,
    requestAsPromise(transaction.objectStore(STORES.learningEvidence).getAll()) as Promise<LearningEvidenceItem[]>,
  ]);
  await done;

  return {
    vocabulary: allVocabulary.filter((item) => item.languageId === languageId),
    evidence: allEvidence.filter((item) => item.languageId === languageId),
  };
}

export async function applyLearningAnalysis(
  languageId: string,
  userText: string,
  analysis: TurnLearningAnalysis,
): Promise<LearningMemorySnapshot> {
  const db = await openDatabase();
  const existing = await loadLearningMemory(languageId);
  const now = new Date().toISOString();
  const vocabulary = new Map(existing.vocabulary.map((item) => [item.id, item]));
  const evidence = new Map(existing.evidence.map((item) => [item.id, item]));

  for (const observation of analysis.vocabulary.slice(0, 6)) {
    if (clampConfidence(observation.confidence) < 0.55) continue;

    const term = observation.term.trim().slice(0, 80);
    if (!term) continue;
    const normalizedTerm = term.toLocaleLowerCase(languageId === 'en' ? 'en-US' : undefined);
    const id = `${languageId}:vocab:${safeIdPart(normalizedTerm)}`;
    if (!safeIdPart(normalizedTerm)) continue;

    const current = vocabulary.get(id) ?? {
      id,
      languageId,
      term,
      normalizedTerm,
      correctUses: 0,
      needsWorkUses: 0,
      introducedCount: 0,
      lastSeenAt: now,
    } satisfies VocabularyMemoryItem;

    current.term = term;
    current.meaningEs = observation.meaningEs?.trim().slice(0, 120) || current.meaningEs;
    current.lastSeenAt = now;
    if (observation.status === 'correct') current.correctUses += 1;
    if (observation.status === 'needs_work') current.needsWorkUses += 1;
    if (observation.status === 'introduced') current.introducedCount += 1;
    vocabulary.set(id, current);
  }

  for (const observation of analysis.skills.slice(0, 6)) {
    if (clampConfidence(observation.confidence) < 0.55) continue;

    const key = safeIdPart(observation.key || observation.label);
    if (!key) continue;
    const id = `${languageId}:${observation.category}:${key}`;
    const current = evidence.get(id) ?? {
      id,
      languageId,
      category: observation.category,
      key,
      label: observation.label.trim().slice(0, 100) || key,
      correctCount: 0,
      needsWorkCount: 0,
      recentExamples: [],
      lastSeenAt: now,
    } satisfies LearningEvidenceItem;

    current.label = observation.label.trim().slice(0, 100) || current.label;
    current.lastSeenAt = now;
    if (observation.status === 'correct') current.correctCount += 1;
    if (observation.status === 'needs_work') current.needsWorkCount += 1;
    current.correction = observation.correction?.trim().slice(0, 180) || current.correction;
    current.note = observation.note?.trim().slice(0, 180) || current.note;
    current.recentExamples = [
      ...current.recentExamples,
      { text: userText.trim().slice(0, 240), status: observation.status, at: now },
    ].slice(-MAX_RECENT_EXAMPLES);
    evidence.set(id, current);
  }

  const vocabularyList = [...vocabulary.values()]
    .sort((a, b) => new Date(b.lastSeenAt).getTime() - new Date(a.lastSeenAt).getTime())
    .slice(0, MAX_VOCABULARY_ITEMS);
  const evidenceList = [...evidence.values()]
    .sort((a, b) => new Date(b.lastSeenAt).getTime() - new Date(a.lastSeenAt).getTime())
    .slice(0, MAX_EVIDENCE_ITEMS);

  const transaction = db.transaction([STORES.vocabulary, STORES.learningEvidence], 'readwrite');
  const vocabularyStore = transaction.objectStore(STORES.vocabulary);
  const evidenceStore = transaction.objectStore(STORES.learningEvidence);

  const existingVocabularyIds = new Set(existing.vocabulary.map((item) => item.id));
  const retainedVocabularyIds = new Set(vocabularyList.map((item) => item.id));
  for (const id of existingVocabularyIds) if (!retainedVocabularyIds.has(id)) vocabularyStore.delete(id);
  for (const item of vocabularyList) vocabularyStore.put(item);

  const existingEvidenceIds = new Set(existing.evidence.map((item) => item.id));
  const retainedEvidenceIds = new Set(evidenceList.map((item) => item.id));
  for (const id of existingEvidenceIds) if (!retainedEvidenceIds.has(id)) evidenceStore.delete(id);
  for (const item of evidenceList) evidenceStore.put(item);

  await transactionDone(transaction);
  return { vocabulary: vocabularyList, evidence: evidenceList };
}

export async function clearLearningMemory(languageId: string): Promise<void> {
  const db = await openDatabase();
  const current = await loadLearningMemory(languageId);
  const transaction = db.transaction([STORES.vocabulary, STORES.learningEvidence], 'readwrite');
  const vocabularyStore = transaction.objectStore(STORES.vocabulary);
  const evidenceStore = transaction.objectStore(STORES.learningEvidence);

  current.vocabulary.forEach((item) => vocabularyStore.delete(item.id));
  current.evidence.forEach((item) => evidenceStore.delete(item.id));
  await transactionDone(transaction);
}

export async function loadPronunciationMemory(languageId: string): Promise<PronunciationMemorySnapshot> {
  const db = await openDatabase();
  const transaction = db.transaction(STORES.pronunciation, 'readonly');
  const done = transactionDone(transaction);
  const stored = await requestAsPromise(
    transaction.objectStore(STORES.pronunciation).get(languageId),
  ) as PronunciationMemorySnapshot | undefined;
  await done;
  return stored ?? emptyPronunciationMemory(languageId);
}

export async function applyPronunciationAssessment(
  languageId: string,
  assessment: PronunciationAssessmentSummary,
): Promise<PronunciationMemorySnapshot> {
  const db = await openDatabase();
  const current = await loadPronunciationMemory(languageId);
  const nextCount = current.assessmentCount + 1;
  const weighted = (previous: number, next: number) =>
    ((previous * current.assessmentCount) + next) / nextCount;

  const weakWords = new Map(current.weakWords.map((item) => [item.normalizedWord, { ...item }]));
  for (const word of assessment.weakWords) {
    const normalizedWord = word.word.trim().toLocaleLowerCase('en-US');
    if (!normalizedWord) continue;
    const previous = weakWords.get(normalizedWord);
    const attempts = (previous?.attempts ?? 0) + 1;
    const averageAccuracy = previous
      ? ((previous.averageAccuracy * previous.attempts) + word.accuracyScore) / attempts
      : word.accuracyScore;

    weakWords.set(normalizedWord, {
      word: word.word,
      normalizedWord,
      attempts,
      weakAttempts: (previous?.weakAttempts ?? 0) + 1,
      averageAccuracy,
      lastAccuracy: word.accuracyScore,
      weakestPhonemes: [...word.phonemes]
        .sort((a, b) => a.accuracyScore - b.accuracyScore)
        .slice(0, 3),
      lastSeenAt: assessment.assessedAt,
    });
  }

  const snapshot: PronunciationMemorySnapshot = {
    languageId,
    assessmentCount: nextCount,
    averageAccuracy: weighted(current.averageAccuracy, assessment.accuracyScore),
    averageFluency: weighted(current.averageFluency, assessment.fluencyScore),
    averagePronunciation: weighted(current.averagePronunciation, assessment.pronunciationScore),
    weakWords: [...weakWords.values()]
      .sort((a, b) => {
        const priorityA = a.weakAttempts * 10 - a.averageAccuracy + new Date(a.lastSeenAt).getTime() / 1e13;
        const priorityB = b.weakAttempts * 10 - b.averageAccuracy + new Date(b.lastSeenAt).getTime() / 1e13;
        return priorityB - priorityA;
      })
      .slice(0, MAX_PRONUNCIATION_WEAK_WORDS),
    latestAssessment: assessment,
    updatedAt: assessment.assessedAt,
  };

  const transaction = db.transaction(STORES.pronunciation, 'readwrite');
  transaction.objectStore(STORES.pronunciation).put(snapshot);
  await transactionDone(transaction);
  return snapshot;
}

export async function clearPronunciationMemory(languageId: string): Promise<void> {
  const db = await openDatabase();
  const transaction = db.transaction(STORES.pronunciation, 'readwrite');
  transaction.objectStore(STORES.pronunciation).delete(languageId);
  await transactionDone(transaction);
}



function localProgressDateKey(date = new Date()): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function emptyDailyProgress(languageId: string, date: string): DailyProgressRecord {
  return {
    id: `${languageId}:${date}`,
    languageId,
    date,
    turns: 0,
    voiceTurns: 0,
    keyboardTurns: 0,
    userWords: 0,
    assistantWords: 0,
    sessionsStarted: 0,
    themeTurns: {},
    updatedAt: new Date().toISOString(),
  };
}

export async function loadProgressActivity(languageId: string): Promise<ProgressActivitySnapshot> {
  const db = await openDatabase();
  const transaction = db.transaction(STORES.progressDaily, 'readonly');
  const done = transactionDone(transaction);
  const records = await requestAsPromise(
    transaction.objectStore(STORES.progressDaily).getAll(),
  ) as DailyProgressRecord[];
  await done;

  return {
    daily: records
      .filter((item) => item.languageId === languageId)
      .sort((a, b) => a.date.localeCompare(b.date))
      .slice(-MAX_PROGRESS_DAYS),
  };
}

async function saveProgressRecord(languageId: string, next: DailyProgressRecord): Promise<ProgressActivitySnapshot> {
  const db = await openDatabase();
  const current = await loadProgressActivity(languageId);
  const byId = new Map(current.daily.map((item) => [item.id, item]));
  byId.set(next.id, next);

  const retained = [...byId.values()]
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(-MAX_PROGRESS_DAYS);
  const retainedIds = new Set(retained.map((item) => item.id));

  const transaction = db.transaction(STORES.progressDaily, 'readwrite');
  const store = transaction.objectStore(STORES.progressDaily);
  current.daily.forEach((item) => {
    if (!retainedIds.has(item.id)) store.delete(item.id);
  });
  retained.forEach((item) => store.put(item));
  await transactionDone(transaction);

  return { daily: retained };
}

export async function recordProgressTurn(
  languageId: string,
  themeId: number,
  source: 'keyboard' | 'voice',
  userText: string,
  assistantText: string,
): Promise<ProgressActivitySnapshot> {
  const date = localProgressDateKey();
  const current = await loadProgressActivity(languageId);
  const existing = current.daily.find((item) => item.date === date) ?? emptyDailyProgress(languageId, date);
  const next: DailyProgressRecord = {
    ...existing,
    turns: existing.turns + 1,
    voiceTurns: existing.voiceTurns + (source === 'voice' ? 1 : 0),
    keyboardTurns: existing.keyboardTurns + (source === 'keyboard' ? 1 : 0),
    userWords: existing.userWords + countWords(userText),
    assistantWords: existing.assistantWords + countWords(assistantText),
    themeTurns: {
      ...existing.themeTurns,
      [String(themeId)]: (existing.themeTurns[String(themeId)] ?? 0) + 1,
    },
    updatedAt: new Date().toISOString(),
  };
  return saveProgressRecord(languageId, next);
}

export async function recordProgressSessionStart(
  languageId: string,
  themeId: number,
): Promise<ProgressActivitySnapshot> {
  const date = localProgressDateKey();
  const current = await loadProgressActivity(languageId);
  const existing = current.daily.find((item) => item.date === date) ?? emptyDailyProgress(languageId, date);
  const next: DailyProgressRecord = {
    ...existing,
    sessionsStarted: existing.sessionsStarted + 1,
    themeTurns: { ...existing.themeTurns, [String(themeId)]: existing.themeTurns[String(themeId)] ?? 0 },
    updatedAt: new Date().toISOString(),
  };
  return saveProgressRecord(languageId, next);
}

export async function clearProgressActivity(languageId: string): Promise<void> {
  const db = await openDatabase();
  const current = await loadProgressActivity(languageId);
  const transaction = db.transaction(STORES.progressDaily, 'readwrite');
  const store = transaction.objectStore(STORES.progressDaily);
  current.daily.forEach((item) => store.delete(item.id));
  await transactionDone(transaction);
}
