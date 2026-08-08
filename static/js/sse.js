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
            console.log('[SSE] Connected to Event Stream.');
        };

        evtSource.onmessage = (event) => {
            try {
                const payload = JSON.parse(event.data);
                console.log(`[SSE] Event Received: ${payload.type}`, payload.data);

                if (payload.type === 'new_message') {
                    window.dispatchEvent(new CustomEvent('sse:new_message', { detail: payload.data }));
                }
                else if (payload.type === 'status_update') {
                    window.dispatchEvent(new CustomEvent('sse:status_update', { detail: payload.data }));
                }
                // --- NEW HEALTH UPDATE HANDLER ---
                else if (payload.type === 'health_update') {
                    const data = payload.data;

                    // Update Battery Text
                    const batLevel = document.getElementById('battery-level');
                    if (batLevel) batLevel.textContent = data.battery_level + '%';

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
                        // Clear existing colors
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
                        }
                    }
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

    initSSE();
});