import React from 'react';
import type { LearningMemorySnapshot } from '../learning/types';

interface WordsViewProps { memory: LearningMemorySnapshot; }

export const WordsView: React.FC<WordsViewProps> = ({ memory }) => {
  const words = [...memory.vocabulary].sort((a, b) => {
    const ar = a.needsWorkUses - a.correctUses;
    const br = b.needsWorkUses - b.correctUses;
    return br - ar || new Date(b.lastSeenAt).getTime() - new Date(a.lastSeenAt).getTime();
  });

  return (
    <div className="content-page words-page">
      <div className="page-heading">
        <p className="eyebrow">Words</p>
        <h2>Tu vocabulario</h2>
        <p>Una memoria compacta de palabras que han aparecido en tu aprendizaje. No es un historial de conversaciones.</p>
      </div>
      {words.length === 0 ? (
        <div className="empty-panel"><span className="empty-panel__mark">Aa</span><h3>Todavía no hay palabras guardadas</h3><p>Habla con Mural y el vocabulario útil irá apareciendo aquí.</p></div>
      ) : (
        <div className="word-list">
          {words.map((item) => {
            const review = item.needsWorkUses > item.correctUses;
            return (
              <article key={item.id} className="word-row">
                <div><h3>{item.term}</h3><p>{item.meaningEs || 'Vocabulario observado durante la conversación'}</p></div>
                <div className="word-row__meta"><span className={review ? 'status-dot status-dot--review' : 'status-dot'} />{review ? 'Repasar' : 'En progreso'}</div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
};
