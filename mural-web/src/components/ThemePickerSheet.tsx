import React from 'react';
import type { ConversationTheme } from '../core/types';
import { AppIcon } from './AppIcon';

interface ThemePickerSheetProps {
  open: boolean;
  themes: ConversationTheme[];
  selectedThemeId: number;
  disabled?: boolean;
  onSelect: (themeId: number) => void;
  onClose: () => void;
}

export const ThemePickerSheet: React.FC<ThemePickerSheetProps> = ({ open, themes, selectedThemeId, disabled, onSelect, onClose }) => {
  if (!open) return null;
  return (
    <div className="sheet-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="bottom-sheet" role="dialog" aria-modal="true" aria-label="Elegir tema">
        <div className="sheet-handle" />
        <div className="sheet-header">
          <div>
            <p className="eyebrow">Themes</p>
            <h2>¿De qué quieres hablar?</h2>
            <p>Cambiar de tema reinicia la conversación actual, pero conserva tu aprendizaje.</p>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Cerrar"><AppIcon name="close" /></button>
        </div>
        <div className="theme-grid">
          {themes.map((theme) => (
            <button
              key={theme.id}
              type="button"
              disabled={disabled}
              onClick={() => { onSelect(theme.id); onClose(); }}
              className={`theme-tile ${theme.id === selectedThemeId ? 'is-active' : ''}`}
            >
              <span className="theme-tile__number">{String(theme.id).padStart(2, '0')}</span>
              <span>{theme.title}</span>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
};
