/**
 * api.js
 * Shared authenticated fetch wrapper, CSRF injection, real-activity heartbeat,
 * 2-minute idle timeout warning modal, and HIPAA PHI wipe on logout/timeout.
 */
(function () {
    const body = document.body;
    const csrfToken = body.dataset.csrfToken || '';
    const idleTimeoutSec = parseInt(body.dataset.idleTimeoutSec || '1800', 10);
    let idleExpiresAtMs = Date.now() + idleTimeoutSec * 1000;
    let lastHeartbeatSentMs = Date.now();
    let hasPendingInteraction = false;
    let isRedirecting = false;

    function wipePhiAndRedirect(reason) {
        if (isRedirecting) return;
        isRedirecting = true;

        window.dispatchEvent(new CustomEvent('app:wipe_phi'));

        ['thread-list', 'chat-area', 'contacts-table-body', 'users-table-body', 'audit-table-body'].forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.textContent = '';
        });

        const msgInput = document.getElementById('message-input');
        if (msgInput) msgInput.value = '';

        window.location.replace('/login?reason=' + encodeURIComponent(reason || 'timeout'));
    }

    async function apiFetch(url, options = {}) {
        const opts = Object.assign({}, options);
        const headers = new Headers(opts.headers || {});
        const method = (opts.method || 'GET').toUpperCase();

        if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && csrfToken) {
            headers.set('X-CSRF-Token', csrfToken);
        }
        opts.headers = headers;

        const res = await fetch(url, opts);
        if (res.status === 401) {
            wipePhiAndRedirect('timeout');
            throw new Error('Session expired');
        }
        if (!opts.headers.get('X-Background-Sync')) {
            idleExpiresAtMs = Date.now() + idleTimeoutSec * 1000;
        }
        return res;
    }

    async function sendHeartbeat() {
        if (isRedirecting) return;
        try {
            const res = await apiFetch('/api/auth/heartbeat', { method: 'POST' });
            if (res.ok) {
                const data = await res.json();
                if (data.idle_expires_at) {
                    idleExpiresAtMs = Date.parse(data.idle_expires_at);
                } else {
                    idleExpiresAtMs = Date.now() + idleTimeoutSec * 1000;
                }
                lastHeartbeatSentMs = Date.now();
                hasPendingInteraction = false;
            }
        } catch (_err) {
            // Handled by 401 or next tick
        }
    }

    function markUserInteraction() {
        if (document.visibilityState !== 'visible') return;
        hasPendingInteraction = true;
        if (Date.now() - lastHeartbeatSentMs >= 60000) {
            sendHeartbeat();
        }
    }

    ['pointerdown', 'keydown', 'click', 'wheel', 'input'].forEach((evt) => {
        window.addEventListener(evt, markUserInteraction, { passive: true });
    });

    document.addEventListener('DOMContentLoaded', () => {
        const timeoutModal = document.getElementById('timeout-modal');
        const timeoutCountdown = document.getElementById('timeout-countdown');
        const stayBtn = document.getElementById('timeout-stay-btn');
        const timeoutLogoutBtn = document.getElementById('timeout-logout-btn');
        const logoutBtn = document.getElementById('logout-btn');

        async function doLogout(reason) {
            try {
                await fetch('/api/auth/logout', {
                    method: 'POST',
                    headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {},
                });
            } catch (_e) {
                // Ignore network errors on logout
            }
            wipePhiAndRedirect(reason || 'logout');
        }

        if (logoutBtn) {
            logoutBtn.addEventListener('click', () => doLogout('logout'));
        }
        if (timeoutLogoutBtn) {
            timeoutLogoutBtn.addEventListener('click', () => doLogout('logout'));
        }
        if (stayBtn) {
            stayBtn.addEventListener('click', async () => {
                await sendHeartbeat();
                if (timeoutModal) timeoutModal.classList.add('hidden');
            });
        }

        // Modal close buttons
        document.querySelectorAll('[data-close-modal]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const targetId = btn.getAttribute('data-close-modal');
                const modal = document.getElementById(targetId);
                if (modal) modal.classList.add('hidden');
            });
        });

        // Change Own Password Modal
        const cpOpenBtn = document.getElementById('change-password-open-btn');
        const cpModal = document.getElementById('password-modal');
        const cpForm = document.getElementById('change-password-form');
        const cpErr = document.getElementById('change-password-error');

        if (cpOpenBtn && cpModal) {
            cpOpenBtn.addEventListener('click', () => {
                if (cpErr) cpErr.classList.add('hidden');
                if (cpForm) cpForm.reset();
                cpModal.classList.remove('hidden');
            });
        }

        if (cpForm) {
            cpForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                cpErr.classList.add('hidden');
                const curPw = document.getElementById('cp-current').value;
                const newPw = document.getElementById('cp-new').value;
                const confPw = document.getElementById('cp-confirm').value;

                if (newPw !== confPw) {
                    cpErr.textContent = 'New passwords do not match.';
                    cpErr.classList.remove('hidden');
                    return;
                }

                try {
                    const res = await apiFetch('/api/auth/change-password', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            current_password: curPw,
                            new_password: newPw,
                            revoke_other_sessions: true,
                        }),
                    });
                    if (res.ok) {
                        cpModal.classList.add('hidden');
                        cpForm.reset();
                    } else {
                        const errData = await res.json().catch(() => ({}));
                        cpErr.textContent = errData.detail || 'Could not update password.';
                        cpErr.classList.remove('hidden');
                    }
                } catch (_err) {
                    cpErr.textContent = 'Network error updating password.';
                    cpErr.classList.remove('hidden');
                }
            });
        }

        // 1-second idle timer check
        setInterval(() => {
            if (isRedirecting) return;
            if (hasPendingInteraction && Date.now() - lastHeartbeatSentMs >= 60000) {
                sendHeartbeat();
            }
            const remainingSec = Math.ceil((idleExpiresAtMs - Date.now()) / 1000);
            if (remainingSec <= 0) {
                wipePhiAndRedirect('timeout');
                return;
            }
            if (remainingSec <= 120 && timeoutModal && timeoutCountdown) {
                timeoutCountdown.textContent = String(remainingSec);
                timeoutModal.classList.remove('hidden');
            } else if (remainingSec > 120 && timeoutModal && !timeoutModal.classList.contains('hidden')) {
                timeoutModal.classList.add('hidden');
            }
        }, 1000);
    });

    window.ClinicApi = {
        apiFetch,
        wipePhiAndRedirect,
        sendHeartbeat,
    };
})();
