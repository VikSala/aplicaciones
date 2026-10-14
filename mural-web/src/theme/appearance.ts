export type AppearanceMode = 'system' | 'light' | 'dark';

const APPEARANCE_CACHE_KEY = 'mural-web-appearance';

export function loadAppearancePreference(): AppearanceMode {
  if (typeof window === 'undefined') return 'system';
  const value = window.localStorage.getItem(APPEARANCE_CACHE_KEY);
  return value === 'light' || value === 'dark' || value === 'system' ? value : 'system';
}

export function cacheAppearancePreference(mode: AppearanceMode): void {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(APPEARANCE_CACHE_KEY, mode);
}

export function resolveAppearance(mode: AppearanceMode): 'light' | 'dark' {
  if (mode === 'light' || mode === 'dark') return mode;
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 'dark';
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

export function applyAppearance(mode: AppearanceMode): void {
  if (typeof document === 'undefined') return;
  const resolved = resolveAppearance(mode);
  document.documentElement.dataset.appearance = resolved;
  document.documentElement.dataset.appearanceMode = mode;
  document.documentElement.style.colorScheme = resolved;
  const themeColor = resolved === 'dark' ? '#1c1c1c' : '#f5f5f3';
  document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]').forEach((meta) => { meta.content = themeColor; });
}
