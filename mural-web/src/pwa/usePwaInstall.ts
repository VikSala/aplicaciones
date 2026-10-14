import { useEffect, useMemo, useState } from 'react';

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
}

export interface PwaInstallState {
  canInstall: boolean;
  installed: boolean;
  isIos: boolean;
  isStandalone: boolean;
  install: () => Promise<'accepted' | 'dismissed' | 'unavailable'>;
}

function detectStandalone(): boolean {
  const standaloneMedia = window.matchMedia?.('(display-mode: standalone)').matches ?? false;
  const navigatorStandalone = Boolean((window.navigator as Navigator & { standalone?: boolean }).standalone);
  return standaloneMedia || navigatorStandalone;
}

export function usePwaInstall(): PwaInstallState {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(false);
  const [isStandalone, setIsStandalone] = useState(() => (typeof window === 'undefined' ? false : detectStandalone()));
  const isIos = useMemo(() => {
    if (typeof navigator === 'undefined') return false;
    return /iphone|ipad|ipod/i.test(navigator.userAgent);
  }, []);

  useEffect(() => {
    const onBeforeInstall = (event: Event) => {
      event.preventDefault();
      setDeferredPrompt(event as BeforeInstallPromptEvent);
    };
    const onInstalled = () => {
      setInstalled(true);
      setDeferredPrompt(null);
      setIsStandalone(true);
    };
    const media = window.matchMedia?.('(display-mode: standalone)');
    const onDisplayMode = () => setIsStandalone(detectStandalone());

    window.addEventListener('beforeinstallprompt', onBeforeInstall);
    window.addEventListener('appinstalled', onInstalled);
    media?.addEventListener?.('change', onDisplayMode);

    return () => {
      window.removeEventListener('beforeinstallprompt', onBeforeInstall);
      window.removeEventListener('appinstalled', onInstalled);
      media?.removeEventListener?.('change', onDisplayMode);
    };
  }, []);

  return {
    canInstall: Boolean(deferredPrompt) && !isStandalone,
    installed,
    isIos,
    isStandalone,
    install: async () => {
      if (!deferredPrompt) return 'unavailable';
      await deferredPrompt.prompt();
      const choice = await deferredPrompt.userChoice;
      if (choice.outcome === 'accepted') setDeferredPrompt(null);
      return choice.outcome;
    },
  };
}
