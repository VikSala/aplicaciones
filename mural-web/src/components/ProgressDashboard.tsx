import React from 'react';
import type { ProgressOverview } from '../progress/types';

interface ProgressDashboardProps {
  overview: ProgressOverview;
  status: 'loading' | 'ready' | 'error';
  error: string | null;
  onClearActivity: () => void;
  clearDisabled: boolean;
}

function categoryLabel(category: string): string {
  switch (category) {
    case 'grammar': return 'Gramática';
    case 'usage': return 'Uso';
    case 'spelling': return 'Ortografía';
    case 'vocabulary': return 'Vocabulario';
    default: return category;
  }
}

function Metric({ label, value, hint }: { label: string; value: string; hint: string }) {
  return <article className="metric-card"><span>{label}</span><strong>{value}</strong><p>{hint}</p></article>;
}

export const ProgressDashboard: React.FC<ProgressDashboardProps> = ({ overview, status, error, onClearActivity, clearDisabled }) => {
  const maxTurns = Math.max(1, ...overview.last7Days.days.map((day) => day.turns));

  if (status === 'loading') return <div className="empty-panel"><h3>Cargando progreso…</h3></div>;

  return (
    <div className="content-page progress-page">
      <div className="page-heading">
        <p className="eyebrow">Progress</p>
        <h2>Tu práctica, sin puntuaciones inventadas</h2>
        <p>Actividad real, vocabulario, puntos pedagógicos y pronunciación.</p>
      </div>

      {error && <div className="error-note">{error}</div>}

      <section className="metric-grid">
        <Metric label="Turnos · 7 días" value={String(overview.last7Days.turns)} hint={`${overview.last7Days.voiceTurns} voz · ${overview.last7Days.keyboardTurns} teclado`} />
        <Metric label="Días activos" value={`${overview.last7Days.activeDays}/7`} hint={overview.streakDays > 0 ? `Racha: ${overview.streakDays} día${overview.streakDays === 1 ? '' : 's'}` : 'Sin racha activa'} />
        <Metric label="Tus palabras" value={new Intl.NumberFormat('es-ES').format(overview.last7Days.userWords)} hint={`${new Intl.NumberFormat('es-ES').format(overview.last7Days.assistantWords)} recibidas`} />
        <Metric label="Temas" value={String(overview.last7Days.themesPracticed)} hint={`${overview.last7Days.sessionsStarted} sesiones`} />
      </section>

      <section className="surface-card activity-card">
        <div className="section-heading"><div><h3>Últimos 7 días</h3><p>{overview.retained.turns} turnos en el periodo retenido</p></div></div>
        <div className="activity-bars" aria-label="Actividad de los últimos siete días">
          {overview.last7Days.days.map((day) => {
            const height = day.turns === 0 ? 7 : Math.max(18, Math.round((day.turns / maxTurns) * 108));
            return <div key={day.date} className="activity-day"><div className="activity-track"><span style={{ height }} title={`${day.turns} turnos · ${day.words} palabras`} /></div><strong>{day.label}</strong><small>{day.turns}</small></div>;
          })}
        </div>
      </section>

      <div className="two-column-grid">
        <section className="surface-card">
          <div className="section-heading"><div><h3>Vocabulario</h3><p>{overview.vocabulary.total} palabras observadas</p></div></div>
          <div className="mini-metrics"><div><strong>{overview.vocabulary.mastered}</strong><span>Consolidado</span></div><div><strong>{overview.vocabulary.review}</strong><span>Repasar</span></div><div><strong>{overview.vocabulary.introduced}</strong><span>En proceso</span></div></div>
          <div className="compact-list">
            {overview.vocabulary.topReview.length ? overview.vocabulary.topReview.map((item) => <div key={item.id}><span>{item.term}</span><small>{item.correctUses} correctos · {item.needsWorkUses} a revisar</small></div>) : <p className="muted-copy">Sin palabras prioritarias todavía.</p>}
          </div>
        </section>

        <section className="surface-card">
          <div className="section-heading"><div><h3>Gramática y uso</h3><p>Puntos observados</p></div></div>
          <div className="skill-grid">
            {Object.entries(overview.skills.categories).map(([category, data]) => <div key={category}><span>{categoryLabel(category)}</span><small>{data.strengths} fuertes · {data.review} revisar</small></div>)}
          </div>
          <div className="compact-list">
            {overview.skills.topReview.length ? overview.skills.topReview.map((item) => <div key={item.id}><span>{item.label}</span><small>{item.correction || item.note || categoryLabel(item.category)}</small></div>) : <p className="muted-copy">Sin puntos prioritarios todavía.</p>}
          </div>
        </section>
      </div>

      <section className="surface-card">
        <div className="section-heading"><div><h3>Pronunciación</h3><p>{overview.pronunciation.assessmentCount} evaluaciones</p></div></div>
        {overview.pronunciation.assessmentCount > 0 ? <>
          <div className="mini-metrics"><div><strong>{Math.round(overview.pronunciation.averagePronunciation)}</strong><span>Global</span></div><div><strong>{Math.round(overview.pronunciation.averageAccuracy)}</strong><span>Precisión</span></div><div><strong>{Math.round(overview.pronunciation.averageFluency)}</strong><span>Fluidez</span></div></div>
          {overview.pronunciation.weakWords.length > 0 && <div className="chip-cloud">{overview.pronunciation.weakWords.map((item) => <span key={item.normalizedWord}>{item.word} · {Math.round(item.averageAccuracy)}</span>)}</div>}
        </> : <p className="muted-copy">Aún no hay evaluaciones de pronunciación.</p>}
      </section>

      <section className="surface-card destructive-row"><div><h3>Actividad local</h3><p>Borra solo agregados diarios; no afecta a la conversación, vocabulario ni pronunciación.</p></div><button type="button" onClick={onClearActivity} disabled={clearDisabled || overview.retained.turns === 0}>Borrar actividad</button></section>
    </div>
  );
};
