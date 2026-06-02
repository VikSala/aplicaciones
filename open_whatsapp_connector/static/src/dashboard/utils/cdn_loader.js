/** @odoo-module **/

// Singleton-promise lazy loader for Chart.js. Same pattern used by
// mss_oto_data_reader; trimmed to just Chart.js (no Leaflet — the WhatsApp
// dashboard has no maps).

let _chartPromise = null;
export function loadChartJS() {
    if (_chartPromise) return _chartPromise;
    _chartPromise = new Promise((resolve, reject) => {
        if (window.Chart) { resolve(window.Chart); return; }
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js';
        script.onload = () => resolve(window.Chart);
        script.onerror = () => reject(new Error('Failed to load Chart.js'));
        document.head.appendChild(script);
    });
    return _chartPromise;
}
