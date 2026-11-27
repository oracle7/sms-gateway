/**
 * sse.js
 * Resilient Server-Sent Events client for IPsec VPN + Firefox,
 * with Pixel 6 health badge updates and smart build_id auto-reload.
 */
document.addEventListener('DOMContentLoaded', () => {
    const SSE_URL = '/events';
    const currentBuildId = document.body.dataset.buildId || '';

    let evtSource = null;
    let hasConnectedOnce = false;
    let lastActivityTime = Date.now();
    let reconnectAttempt = 0;
    let reconnectTimer = null;
    let pendingVersionReload = false;
    let isWiped = false;

    function updateHealthUI(data) {
        if (!data) return;
        const batLevel = document.getElementById('battery-level');
        if (batLevel) {
            const level = data.battery_level !== undefined && data.battery_level !== null ? data.battery_level : '--';
            batLevel.textContent = level + '%';
        }

        const batCharging = document.getElementById('battery-charging');
        if (batCharging) {
            batCharging.classList.toggle('hidden', !data.is_charging);
        }

        const led = document.getElementById('device-health-led');
        if (led) {
            led.classList.remove('pass', 'warn', 'fail');
            if (data.status === 'pass') {
                led.classList.add('pass');
                led.title = 'Pixel 6 Healthy';
            } else if (data.status === 'warn') {
                led.classList.add('warn');
                led.title = 'Warning: Check Pixel 6';
            } else if (data.status === 'fail') {
                led.classList.add('fail');
                led.title = 'Critical Failure on Pixel 6';
            } else {
                led.title = 'Waiting for Pixel 6 ping...';
            }
        }
    }

    async function pollHealthStatus() {
        if (isWiped) return;
        try {
            const res = await window.ClinicApi.apiFetch('/health/status', {
                cache: 'no-store',
                headers: { 'X-Background-Sync': '1' },
            });
            if (res.ok) {
                const data = await res.json();
                updateHealthUI(data);
            }
        } catch (_err) {
            // Handled gracefully
        }
    }

    function isSafeToAutoReload() {
        const input = document.getElementById('message-input');
        const hasDraft = input && input.value.trim().length > 0;
        const openModals = document.querySelectorAll('.modal-backdrop:not(.hidden)');
        return !hasDraft && openModals.length === 0;
    }

    function checkAndTriggerReload() {
        if (!pendingVersionReload || isWiped) return;
        if (isSafeToAutoReload()) {
            const banner = document.getElementById('version-banner');
            const bannerText = document.getElementById('version-banner-text');
            if (banner && bannerText) {
                bannerText.textContent = 'New version detected — refreshing in 3 seconds...';
                banner.classList.remove('hidden');
            }
            setTimeout(() => {
                if (!isWiped && isSafeToAutoReload()) {
                    window.location.reload();
                }
            }, 3000);
        } else {
            const banner = document.getElementById('version-banner');
            if (banner) banner.classList.remove('hidden');
        }
    }

    function handleBuildVersion(serverBuildId) {
        if (!serverBuildId || !currentBuildId || serverBuildId === currentBuildId) return;
        pendingVersionReload = true;
        checkAndTriggerReload();
    }

    function scheduleReconnect() {
        if (isWiped || reconnectTimer) return;
        const delays = [1000, 2000, 5000, 10000, 30000];
        const baseDelay = delays[Math.min(reconnectAttempt, delays.length - 1)];
        const jitter = Math.floor(Math.random() * 500);
        reconnectAttempt += 1;
        reconnectTimer = setTimeout(() => {
            reconnectTimer = null;
            initSSE();
        }, baseDelay + jitter);
    }

    function initSSE() {
        if (isWiped) return;
        if (evtSource) {
            evtSource.close();
            evtSource = null;
        }

        lastActivityTime = Date.now();
        evtSource = new EventSource(SSE_URL);

        evtSource.onopen = () => {
            lastActivityTime = Date.now();
            reconnectAttempt = 0;
            window.dispatchEvent(new CustomEvent('sse:reconnected', {
                detail: { isReconnect: hasConnectedOnce },
            }));
            hasConnectedOnce = true;
            pollHealthStatus();
        };

        evtSource.onmessage = (event) => {
            lastActivityTime = Date.now();
            try {
                const payload = JSON.parse(event.data);
                if (payload.type === 'ping') return;

                if (payload.type === 'hello') {
                    if (payload.data && payload.data.build_id) {
                        handleBuildVersion(payload.data.build_id);
                    }
                    return;
                }
                if (payload.type === 'session_expired') {
                    window.ClinicApi.wipePhiAndRedirect('timeout');
                    return;
                }
                if (payload.type === 'health_update') {
                    updateHealthUI(payload.data);
                    return;
                }

                window.dispatchEvent(new CustomEvent('sse:' + payload.type, { detail: payload.data }));
            } catch (err) {
                console.error('[SSE] Parse error:', err);
            }
        };

        evtSource.onerror = () => {
            const led = document.getElementById('device-health-led');
            if (led) {
                led.classList.remove('pass', 'warn');
                led.classList.add('fail');
                led.title = 'Live connection interrupted — reconnecting...';
            }
            if (evtSource) {
                evtSource.close();
                evtSource = null;
            }
            scheduleReconnect();
        };
    }

    // Watchdog: server sends ping every 15s; >35s silence on VPN means half-open drop
    setInterval(() => {
        if (isWiped) return;
        if (Date.now() - lastActivityTime > 35000) {
            initSSE();
        }
    }, 5000);

    window.addEventListener('online', () => {
        reconnectAttempt = 0;
        initSSE();
    });

    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            if (!evtSource || evtSource.readyState === EventSource.CLOSED || (Date.now() - lastActivityTime > 25000)) {
                initSSE();
            }
        }
    });

    window.addEventListener('app:wipe_phi', () => {
        isWiped = true;
        if (evtSource) {
            evtSource.close();
            evtSource = null;
        }
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
    });

    // Re-check pending version reload when user clears/sends draft or clicks Reload Now
    const msgInput = document.getElementById('message-input');
    if (msgInput) {
        msgInput.addEventListener('input', () => {
            if (pendingVersionReload && isSafeToAutoReload()) {
                checkAndTriggerReload();
            }
        });
    }
    const reloadBtn = document.getElementById('version-reload-btn');
    if (reloadBtn) {
        reloadBtn.addEventListener('click', () => window.location.reload());
    }
    window.addEventListener('app:message_sent', () => {
        if (pendingVersionReload) checkAndTriggerReload();
    });

    initSSE();
    pollHealthStatus();
    setInterval(pollHealthStatus, 60000);
});
