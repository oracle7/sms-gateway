/**
 * app.js
 * Controls the main messaging interface (thread list, chat area, and sidebars).
 */
document.addEventListener('DOMContentLoaded', () => {
    const threadList = document.getElementById('thread-list');
    const chatArea = document.getElementById('chat-area');
    const messageForm = document.getElementById('message-form');
    const messageInput = document.getElementById('message-input');

    // Right sidebar elements
    const rightContactName = document.getElementById('right-contact-name');
    const rightContactPhone = document.getElementById('right-contact-phone');
    const contactInitial = document.getElementById('contact-initial');

    let activePhone = null;
    let contactsCache = {};

    // Alerting Variables
    let isAlerting = false;
    let originalTitle = document.title;
    let alertInterval = null;
    let activeTimer = null;

    // Normalization helper (E.164 Standard)
    function normalizePhone(phone, defaultCountryCode = '1') {
        if (!phone) return '';
        let cleaned = phone.trim().replace(/[^\d+]/g, '');
        if (cleaned.startsWith('+')) return '+' + cleaned.replace(/\D/g, '');
        if (cleaned.length === 10) return `+${defaultCountryCode}${cleaned}`;
        if (cleaned.length === 11 && cleaned.startsWith(defaultCountryCode)) return `+${cleaned}`;
        return `+${cleaned}`;
    }

    // 1. Boot up
    async function init() {
        await loadContactsMap();
        await loadThreads();
        setupEmojiPicker();

        const urlParams = new URLSearchParams(window.location.search);
        const phoneParam = urlParams.get('phone');
        if (phoneParam) {
            openThread(normalizePhone(phoneParam));
        }
    }

    // 2. Fetch contacts for name resolution
    async function loadContactsMap() {
        try {
            const res = await fetch('/api/contacts/');
            const contacts = await res.json();
            contacts.forEach(c => {
                contactsCache[normalizePhone(c.phone_number)] = c.name;
            });
        } catch (err) {
            console.error('Failed to load contacts map', err);
        }
    }

    // 3. Load and sort the left sidebar threads
    async function loadThreads() {
        try {
            const res = await fetch('/api/messages/?limit=500');
            const messages = await res.json();

            const threads = {};
            messages.forEach(msg => {
                const contactPhone = normalizePhone(msg.sender || msg.recipient);
                if (!contactPhone) return;

                if (!threads[contactPhone]) {
                    threads[contactPhone] = { latestMsg: msg };
                }
            });

            renderSidebar(threads);
        } catch (err) {
            console.error('Failed to load threads', err);
        }
    }

    function renderSidebar(threads) {
        if (!threadList) return;
        threadList.innerHTML = '';

        // Sort by most recent activity
        const sortedPhones = Object.keys(threads).sort((a, b) => {
            return new Date(threads[b].latestMsg.timestamp) - new Date(threads[a].latestMsg.timestamp);
        });

        sortedPhones.forEach(phone => {
            const data = threads[phone];
            const name = contactsCache[phone] || phone;
            const previewText = data.latestMsg.body || 'Media message';

            // Check for unread based on web_viewed boolean
            const isOutbound = data.latestMsg.sender === null;
            const isUnread = !isOutbound && (data.latestMsg.web_viewed === false || data.latestMsg.web_viewed === 0);

            let containerClasses = `p-4 border-b border-gray-100 cursor-pointer transition-colors relative `;
            if (activePhone === phone) {
                containerClasses += `bg-blue-50 `;
            } else if (isUnread) {
                containerClasses += `bg-red-50 hover:bg-red-100 `; // Red tint for unread
            } else {
                containerClasses += `bg-white hover:bg-gray-50 `;
            }

            // Pulse indicator for unread threads
            const unreadIndicator = isUnread ? `<span class="absolute top-4 right-4 w-2.5 h-2.5 bg-red-500 rounded-full animate-pulse shadow-sm shadow-red-300" title="Unread"></span>` : '';

            const el = document.createElement('div');
            el.className = containerClasses;
            el.innerHTML = `
                <div class="font-bold truncate pr-6 ${isUnread ? 'text-red-900' : 'text-gray-800'}">${name}</div>
                <div class="text-sm truncate ${isUnread ? 'text-red-700 font-medium' : 'text-gray-500'}">${previewText}</div>
                ${unreadIndicator}
            `;
            el.onclick = () => openThread(phone);
            threadList.appendChild(el);
        });
    }

    // 4. Open a specific chat
    async function openThread(phone) {
        activePhone = normalizePhone(phone);

        // Update Right Sidebar Details
        const name = contactsCache[activePhone] || activePhone;
        if (rightContactName) rightContactName.textContent = name;
        if (rightContactPhone) rightContactPhone.textContent = activePhone;
        if (contactInitial) contactInitial.textContent = name.charAt(0).toUpperCase();

        loadThreads(); // Re-render to highlight active thread

        try {
            const [inbound, outbound] = await Promise.all([
                fetch(`/api/messages/?sender=${encodeURIComponent(activePhone)}`).then(r => r.json()),
                fetch(`/api/messages/?recipient=${encodeURIComponent(activePhone)}`).then(r => r.json())
            ]);

            const allMessages = [...inbound, ...outbound].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
            renderChatArea(allMessages);

        } catch (err) {
            console.error('Failed to load chat history', err);
        }
    }

    function renderChatArea(messages) {
        if (!chatArea) return;
        chatArea.innerHTML = '';

        if (messages.length === 0) {
            chatArea.innerHTML = `<div class="flex h-full items-center justify-center text-gray-400">No messages yet.</div>`;
            return;
        }

        messages.forEach(msg => appendMessageBubble(msg));
        chatArea.scrollTop = chatArea.scrollHeight;
    }

    function appendMessageBubble(msg) {
        if (!chatArea) return;
        const isOutbound = msg.sender === null;

        const bubble = document.createElement('div');
        bubble.dataset.internalId = msg.id;
        bubble.className = `max-w-md p-3 rounded-2xl mb-2 chat-bubble-animate ${isOutbound ? 'bg-blue-500 text-white self-end ml-auto rounded-br-sm' : 'bg-white border border-gray-200 text-gray-800 self-start mr-auto rounded-bl-sm shadow-sm'}`;

        let mediaHtml = '';
        if (msg.attachments && msg.attachments.length > 0) {
            msg.attachments.forEach(att => {
                mediaHtml += `<img src="${att.filename}" class="max-w-xs rounded mt-2" />`;
            });
        }

        let statusHtml = '';
        if (isOutbound) {
            if (msg.is_failed) statusHtml = `<span class="text-red-300 text-xs ml-2" title="${msg.error_reason || 'Failed'}">❌</span>`;
            else if (msg.is_delivered) statusHtml = `<span class="text-blue-200 text-xs ml-2" title="Delivered">✓✓</span>`;
            else if (msg.is_sent) statusHtml = `<span class="text-gray-200 text-xs ml-2" title="Sent">✓</span>`;
            else statusHtml = `<span class="text-gray-300 text-xs ml-2" title="Sending">...</span>`;
        }

        bubble.innerHTML = `
            <div class="text-sm leading-relaxed">${msg.body}</div>
            ${mediaHtml}
            <div class="text-right text-[10px] mt-1 ${isOutbound ? 'text-blue-100' : 'text-gray-400'}">
                ${new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                ${statusHtml}
            </div>
        `;

        chatArea.appendChild(bubble);
        chatArea.scrollTop = chatArea.scrollHeight;
    }

    // 5. Send a new message
    if (messageForm) {
        messageForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!activePhone) return alert("Select a thread first!");

            const body = messageInput.value.trim();
            if (!body) return;

            messageInput.value = '';

            try {
                const res = await fetch('/api/messages/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ recipient: activePhone, body: body })
                });

                if (res.ok) {
                    const newMsg = await res.json();
                    appendMessageBubble(newMsg);
                    loadThreads();
                }
            } catch (err) {
                console.error('Send failed', err);
            }
        });
    }

    // 6. Emoji Picker Logic
    function setupEmojiPicker() {
        document.querySelectorAll('#emoji-picker button').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const emoji = e.target.textContent;
                if (messageInput) {
                    const start = messageInput.selectionStart;
                    const end = messageInput.selectionEnd;
                    const text = messageInput.value;
                    messageInput.value = text.slice(0, start) + emoji + text.slice(end);
                    messageInput.focus();
                    messageInput.selectionStart = messageInput.selectionEnd = start + emoji.length;
                }
            });
        });
    }

    // 7. Alerting Logic (3-second window active)
    function startAlert() {
        if (isAlerting) return;
        isAlerting = true;
        let showDot = false;
        alertInterval = setInterval(() => {
            document.title = showDot ? "🔴 New Message! - Parla!" : originalTitle;
            showDot = !showDot;
        }, 800);
    }

    function stopAlert() {
        isAlerting = false;
        clearInterval(alertInterval);
        document.title = originalTitle;
    }

    function checkWindowActive() {
        if (document.hasFocus()) {
            // Window is active. If alerting, clear it after 3 seconds of sustained focus.
            if (isAlerting && !activeTimer) {
                activeTimer = setTimeout(() => {
                    stopAlert();
                    activeTimer = null;
                }, 3000);
            }
        } else {
            // Window lost focus. Pause the clearing timer.
            if (activeTimer) {
                clearTimeout(activeTimer);
                activeTimer = null;
            }
        }
    }

    window.addEventListener('focus', checkWindowActive);
    window.addEventListener('blur', checkWindowActive);

    // 8. Listen to SSE Broadcasts
    window.addEventListener('sse:new_message', (e) => {
        const msg = e.detail;
        const involvedPhone = normalizePhone(msg.sender || msg.recipient);

        if (activePhone === involvedPhone) {
            appendMessageBubble(msg);
        }

        // Trigger alert for inbound messages
        if (msg.sender !== null) {
            startAlert();
            checkWindowActive();
        }

        loadThreads();
    });

    window.addEventListener('sse:status_update', (e) => {
        if (activePhone) {
            openThread(activePhone);
        }
    });

    init();
});