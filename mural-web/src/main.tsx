import React from 'react';
import ReactDOM from 'react-dom/client';
import { MainView } from './components/MainView';
import { registerPwaServiceWorker } from './pwa/register';
import './index.css';
import { applyAppearance, loadAppearancePreference } from './theme/appearance';

applyAppearance(loadAppearancePreference());
registerPwaServiceWorker();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MainView />
  </React.StrictMode>,
);
