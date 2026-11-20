/**
 * sse.js
 * Handles the real-time connection to the FastAPI SSE endpoint.
 */
document.addEventListener('DOMContentLoaded', () => {
    const SSE_URL = '/events';
    let evtSource = null;
    let hasConnectedOnce = false;
    let lastActivityTime = Date.now();

    function updateHealthUI(data) {
        if (!data) return;

        // Update Battery Text
        const batLevel = document.getElementById('battery-level');
        if (batLevel) {
            const level = data.battery_level !== undefined && data.battery_level !== null ? data.battery_level : '--';
            batLevel.textContent = level + '%';
        }

        // Toggle Lightning Bolt Icon
        const batCharging = document.getElementById('battery-charging');
        if (batCharging) {
            if (data.is_charging) {
                batCharging.classList.remove('hidden');
            } else {
                batCharging.classList.add('hidden');
            }
        }

        // Update LED Color based on status
        const led = document.getElementById('device-health-led');
        if (led) {
            led.classList.remove('bg-slate-300', 'bg-green-500', 'bg-yellow-500', 'bg-red-500', 'animate-pulse');

            if (data.status === 'pass') {
                led.classList.add('bg-green-500');
                led.title = "System Healthy";
            } else if (data.status === 'warn') {
                led.classList.add('bg-yellow-500');
                led.title = "Warning: Check Device";
            } else if (data.status === 'fail') {
                led.classList.add('bg-red-500', 'animate-pulse');
                led.title = "Critical Failure";
            } else {
                led.classList.add('bg-slate-300');
                led.title = "Waiting for ping...";
            }
        }
    }

    async function pollHealthStatus() {
        try {
            const res = await fetch('/health/status', { cache: 'no-store' });
            if (res.ok) {
                const data = await res.json();
                updateHealthUI(data);
            }
        } catch (err) {
            console.warn('[Health] Failed to poll device status:', err);
        }
    }

    function initSSE() {
        if (evtSource) {
            evtSource.close();
            evtSource = null;
        }

        lastActivityTime = Date.now();
        console.log('[SSE] Initializing connection...');
        evtSource = new EventSource(SSE_URL);

        evtSource.onopen = () => {
            lastActivityTime = Date.now();
            console.log('[SSE] Connected to Event Stream.');
            window.dispatchEvent(new CustomEvent('sse:reconnected', {
                detail: { isReconnect: hasConnectedOnce }
            }));
            hasConnectedOnce = true;
            pollHealthStatus();
        };

        evtSource.onmessage = (event) => {
            lastActivityTime = Date.now();
            try {
                const payload = JSON.parse(event.data);
                if (payload.type === 'ping') {
                    return;
                }

                console.log(`[SSE] Event Received: ${payload.type}`, payload.data);

                if (payload.type === 'new_message') {
                    window.dispatchEvent(new CustomEvent('sse:new_message', { detail: payload.data }));
                }
                else if (payload.type === 'status_update') {
                    window.dispatchEvent(new CustomEvent('sse:status_update', { detail: payload.data }));
                }
                else if (payload.type === 'thread_read') {
                    window.dispatchEvent(new CustomEvent('sse:thread_read', { detail: payload.data }));
                }
                else if (payload.type === 'health_update') {
                    updateHealthUI(payload.data);
                }
            } catch (error) {
                console.error('[SSE] Error parsing event data:', error);
            }
        };

        evtSource.onerror = (error) => {
            console.warn('[SSE] Connection lost. Reconnecting...', error);
            const led = document.getElementById('device-health-led');
            if (led) {
                led.classList.remove('bg-green-500', 'bg-yellow-500');
                led.classList.add('bg-red-500');
                led.title = "SSE Disconnected";
            }
        };
    }

    // Watchdog: detect silent half-open TCP drops (e.g., across IPsec VPN)
    // Server sends a ping every 10s, so >25s of silence indicates a dead stream.
    setInterval(() => {
        if (Date.now() - lastActivityTime > 25000) {
            console.warn('[SSE] Heartbeat timeout detected. Reconnecting...');
            initSSE();
        }
    }, 5000);

    window.addEventListener('online', () => {
        console.log('[SSE] Network online. Reconnecting...');
        initSSE();
    });

    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            if (!evtSource || evtSource.readyState === EventSource.CLOSED || (Date.now() - lastActivityTime > 20000)) {
                console.log('[SSE] Tab became visible with stale/closed stream. Reconnecting...');
                initSSE();
            }
        }
    });

    initSSE();
    pollHealthStatus();
    setInterval(pollHealthStatus, 60000);
});