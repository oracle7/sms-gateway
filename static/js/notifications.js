/**
 * notifications.js
 * Visual tab title alerts, optional airport_ding.mp3 chime, and strictly PHI-free
 * Firefox desktop notifications.
 */
(function () {
    const SOUND_KEY = 'clinic_sound_enabled';
    const NOTIFY_KEY = 'clinic_desktop_notify_enabled';
    const BASE_TITLE = 'Messaging Center';

    let soundEnabled = localStorage.getItem(SOUND_KEY) !== 'false';
    let notifyEnabled = localStorage.getItem(NOTIFY_KEY) === 'true';
    let flashInterval = null;
    let currentUnreadCount = 0;

    const chimeAudio = new Audio('/static/airport_ding.mp3');
    chimeAudio.preload = 'auto';

    function updateToggleButtons() {
        const soundBtn = document.getElementById('sound-toggle-btn');
        if (soundBtn) {
            soundBtn.textContent = soundEnabled ? 'Sound: On' : 'Sound: Off';
            soundBtn.classList.toggle('active', soundEnabled);
        }
        const notifyBtn = document.getElementById('notify-toggle-btn');
        if (notifyBtn) {
            const granted = typeof Notification !== 'undefined' && Notification.permission === 'granted';
            const active = notifyEnabled && granted;
            notifyBtn.textContent = active ? 'Alerts: On' : 'Alerts: Off';
            notifyBtn.classList.toggle('active', active);
        }
    }

    function setUnreadCount(count) {
        currentUnreadCount = Math.max(0, Number(count) || 0);
        if (currentUnreadCount === 0) {
            stopVisualAlert();
        } else {
            startVisualAlert();
        }
    }

    function startVisualAlert() {
        if (flashInterval) return;
        let showDot = true;
        const updateTitle = () => {
            if (currentUnreadCount > 0) {
                document.title = showDot
                    ? `🔴 (${currentUnreadCount}) New Message - ${BASE_TITLE}`
                    : `(${currentUnreadCount}) ${BASE_TITLE}`;
            } else {
                document.title = BASE_TITLE;
            }
            document.body.classList.toggle('alert-flash', showDot && currentUnreadCount > 0);
            showDot = !showDot;
        };
        updateTitle();
        flashInterval = setInterval(updateTitle, 900);
    }

    function stopVisualAlert() {
        if (flashInterval) {
            clearInterval(flashInterval);
            flashInterval = null;
        }
        document.title = BASE_TITLE;
        document.body.classList.remove('alert-flash');
    }

    function notifyNewInboundMessage() {
        if (soundEnabled) {
            chimeAudio.currentTime = 0;
            chimeAudio.play().catch(() => {
                // Browser autoplay policy until first click
            });
        }
        if (
            notifyEnabled &&
            typeof Notification !== 'undefined' &&
            Notification.permission === 'granted' &&
            document.visibilityState !== 'visible'
        ) {
            // Strictly PHI-free notification text
            new Notification('Messaging Center', {
                body: 'New message received',
                tag: 'clinic-new-message',
            });
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        updateToggleButtons();

        const soundBtn = document.getElementById('sound-toggle-btn');
        if (soundBtn) {
            soundBtn.addEventListener('click', () => {
                soundEnabled = !soundEnabled;
                localStorage.setItem(SOUND_KEY, String(soundEnabled));
                updateToggleButtons();
            });
        }

        const notifyBtn = document.getElementById('notify-toggle-btn');
        if (notifyBtn) {
            notifyBtn.addEventListener('click', async () => {
                if (typeof Notification === 'undefined') return;
                if (!notifyEnabled) {
                    if (Notification.permission === 'default') {
                        await Notification.requestPermission();
                    }
                    notifyEnabled = Notification.permission === 'granted';
                } else {
                    notifyEnabled = false;
                }
                localStorage.setItem(NOTIFY_KEY, String(notifyEnabled));
                updateToggleButtons();
            });
        }
    });

    window.ClinicNotify = {
        setUnreadCount,
        notifyNewInboundMessage,
        stopVisualAlert,
    };
})();
