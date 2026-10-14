import React from 'react';

type IconName = 'settings' | 'talk' | 'themes' | 'words' | 'progress' | 'send' | 'keyboard' | 'newConversation' | 'close' | 'play' | 'sun' | 'moon' | 'auto' | 'chevronDown';

interface AppIconProps {
  name: IconName;
  size?: number;
  strokeWidth?: number;
}

export const AppIcon: React.FC<AppIconProps> = ({ name, size = 20, strokeWidth = 1.4 }) => {
  const common = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  };

  switch (name) {
    case 'settings':
      return <svg {...common}><path stroke="none" d="M0 0h24v24H0z" fill="none" /><path d="M12 6a2 2 0 1 0 4 0a2 2 0 1 0 -4 0" /><path d="M4 6l8 0" /><path d="M16 6l4 0" /><path d="M6 12a2 2 0 1 0 4 0a2 2 0 1 0 -4 0" /><path d="M4 12l2 0" /><path d="M10 12l10 0" /><path d="M15 18a2 2 0 1 0 4 0a2 2 0 1 0 -4 0" /><path d="M4 18l11 0" /><path d="M19 18l1 0" /></svg>;
    case 'talk':
      return <svg {...common}><path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z" /><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0" /><path d="M12 18v3" /><path d="M9 21h6" /></svg>;
    case 'themes':
      return <svg {...common}><rect x="4" y="4" width="6" height="6" rx="1.5" /><rect x="14" y="4" width="6" height="6" rx="1.5" /><rect x="4" y="14" width="6" height="6" rx="1.5" /><rect x="14" y="14" width="6" height="6" rx="1.5" /></svg>;
    case 'words':
      return <svg {...common}><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H11v16H6.5A2.5 2.5 0 0 0 4 21.5Z" /><path d="M20 5.5A2.5 2.5 0 0 0 17.5 3H13v16h4.5A2.5 2.5 0 0 1 20 21.5Z" /></svg>;
    case 'progress':
      return <svg {...common}><path d="M4 19V9" /><path d="M10 19V5" /><path d="M16 19v-7" /><path d="M22 19H2" /></svg>;
    case 'send':
      return <svg {...common}><path d="m4 4 16 8-16 8 3-8Z" /><path d="M7 12h13" /></svg>;
    case 'keyboard':
      return <svg {...common}><path stroke="none" d="M0 0h24v24H0z" fill="none" /><path d="M2 8a2 2 0 0 1 2 -2h16a2 2 0 0 1 2 2v8a2 2 0 0 1 -2 2h-16a2 2 0 0 1 -2 -2l0 -8" /><path d="M6 10l0 .01" /><path d="M10 10l0 .01" /><path d="M14 10l0 .01" /><path d="M18 10l0 .01" /><path d="M6 14l0 .01" /><path d="M18 14l0 .01" /><path d="M10 14l4 .01" /></svg>;
    case 'newConversation':
      return <svg {...common}><path stroke="none" d="M0 0h24v24H0z" fill="none" /><path d="M7 7h-1a2 2 0 0 0 -2 2v9a2 2 0 0 0 2 2h9a2 2 0 0 0 2 -2v-1" /><path d="M20.385 6.585a2.1 2.1 0 0 0 -2.97 -2.97l-8.415 8.385v3h3l8.385 -8.415" /><path d="M16 5l3 3" /></svg>;
    case 'close':
      return <svg {...common}><path d="m6 6 12 12M18 6 6 18" /></svg>;
    case 'play':
      return <svg {...common} fill="currentColor" stroke="none"><path d="m8 5 11 7-11 7Z" /></svg>;
    case 'sun':
      return <svg {...common}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.65 17.65l1.42 1.42M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.65 6.35l1.42-1.42" /></svg>;
    case 'moon':
      return <svg {...common}><path d="M20.5 15.2A8.5 8.5 0 0 1 8.8 3.5 8.5 8.5 0 1 0 20.5 15.2Z" /></svg>;
    case 'auto':
      return <svg {...common}><path d="M12 3v3M12 18v3M3 12h3M18 12h3" /><circle cx="12" cy="12" r="4" /></svg>;
    case 'chevronDown':
      return <svg {...common}><path stroke="none" d="M0 0h24v24H0z" fill="none" /><path d="M6 9l6 6l6 -6" /></svg>;
    default:
      return null;
  }
};
