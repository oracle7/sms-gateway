/**
 * sse.js
 * Handles the real-time connection to the FastAPI SSE endpoint.
 */
document.addEventListener('DOMContentLoaded', () => {
    const SSE_URL = '/events';
    let evtSource = null;

    function initSSE() {
        console.log('[SSE] Initializing connection...');
        evtSource = new EventSource(SSE_URL);

        evtSource.onopen = () => {
            console.log('[SSE] Connected.');
            // Optional: Update a connection indicator in the header if it exists
            const indicator = document.getElementById('connection-indicator');
            if (indicator) {
                indicator.classList.remove('bg-red-500', 'bg-yellow-500');
                indicator.classList.add('bg-green-500');
                indicator.title = "Connected to phone";
            }
        };

        evtSource.onmessage = (event) => {
            try {
                const payload = JSON.parse(event.data);
                console.log(`[SSE] Event Received: ${payload.type}`, payload.data);

                // Dispatch global events so other scripts (like app.js) can react
                if (payload.type === 'new_message') {
                    window.dispatchEvent(new CustomEvent('sse:new_message', { detail: payload.data }));
                } else if (payload.type === 'status_update') {
                    window.dispatchEvent(new CustomEvent('sse:status_update', { detail: payload.data }));
                }
            } catch (error) {
                console.error('[SSE] Error parsing event data:', error);
            }
        };

        evtSource.onerror = (error) => {
            console.warn('[SSE] Connection lost. Reconnecting...', error);
            const indicator = document.getElementById('connection-indicator');
            if (indicator) {
                indicator.classList.remove('bg-green-500');
                indicator.classList.add('bg-red-500');
                indicator.title = "Disconnected";
            }
        };
    }

    initSSE();
});