/**
 * app.js
 * Controls the main messaging interface (thread list, chat area, and sidebars).
 */
document.addEventListener('DOMContentLoaded', () => {
    // Define the system's phone number here to determine message direction
    const SYSTEM_PHONE = '+19296141937';

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
    let unreadInActiveThread = false; // Tracks if a message arrived while looking away

    // Alerting Variables
    let isAlerting = false;
    let originalTitle = document.title;
    let alertInterval = null;

    // Normalization helper (E.164 Standard)
    function normalizePhone(phone, defaultCountryCode = '1') {
        if (!phone) return '';
        let cleaned = phone.trim().replace(/[^\d+]/g, '');
        if (cleaned.startsWith('+')) return '+' + cleaned.replace(/\D/g, '');
        if (cleaned.length === 10) return `+${defaultCountryCode}${cleaned}`;
        if (cleaned.length === 11 && cleaned.startsWith(defaultCountryCode)) return `+${cleaned}`;
        return `+${cleaned}`;
    }

    // NEW: Safely parse backend timestamps as UTC so the browser converts them to local time
    function parseUTCDate(timestamp) {
        if (!timestamp) return new Date();
        let ts = timestamp;
        // If the backend returns a string without 'Z' or a timezone offset, append 'Z'
        if (typeof ts === 'string' && !ts.endsWith('Z') && !ts.match(/[\+\-]\d{2}:\d{2}$/)) {
            ts += 'Z';
        }
        return new Date(ts);
    }

    // 1. Boot up
    async function init() {
        await loadContactsMap();
        await loadThreads();
        setupEmojiPicker();

        // Smooth transition for the flashy borders
        document.body.style.transition = 'box-shadow 0.3s ease-in-out';

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
            const res = await fetch('/api/messages/?limit=500', { cache: 'no-store' });
            const messages = await res.json();

            const threads = {};
            messages.forEach(msg => {
                const normSender = normalizePhone(msg.sender);
                const normRecipient = normalizePhone(msg.recipient);

                let contactPhone = null;
                if (normSender && normSender !== SYSTEM_PHONE) {
                    contactPhone = normSender;
                } else if (normRecipient && normRecipient !== SYSTEM_PHONE) {
                    contactPhone = normRecipient;
                }

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

        const sortedPhones = Object.keys(threads).sort((a, b) => {
            return parseUTCDate(threads[b].latestMsg.timestamp) - parseUTCDate(threads[a].latestMsg.timestamp);
        });

        sortedPhones.forEach(phone => {
            const data = threads[phone];
            const name = contactsCache[phone] || phone;
            const previewText = data.latestMsg.body || 'Media message';

            const msgSender = normalizePhone(data.latestMsg.sender);
            const isOutbound = msgSender === SYSTEM_PHONE || !msgSender;
            const isUnread = !isOutbound && (data.latestMsg.web_viewed === false || data.latestMsg.web_viewed === 0);

            let containerClasses = `p-4 border-b border-gray-100 cursor-pointer transition-colors relative `;
            if (activePhone === phone) {
                containerClasses += `bg-blue-50 `;
            } else if (isUnread) {
                containerClasses += `bg-red-50 hover:bg-red-100 `;
            } else {
                containerClasses += `bg-white hover:bg-gray-50 `;
            }

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

    // Function to mark active thread as read
    function markActiveThreadRead() {
        if (!activePhone) return;
        fetch('/api/messages/mark-read/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone: activePhone })
        }).then(() => {
            unreadInActiveThread = false;
            stopAlert(); // Clear flashing immediately
            loadThreads(); // Refresh sidebar to remove red dot
        }).catch(err => console.error('Failed to mark thread as read', err));
    }

    // Hover interaction on chat area clears the unread state
    if (chatArea) {
        const handleInteraction = () => {
            if (unreadInActiveThread) {
                markActiveThreadRead();
            }
        };
        chatArea.addEventListener('mouseenter', handleInteraction);
        chatArea.addEventListener('mousemove', handleInteraction); // Failsafe if mouse is already in the area
    }

    // 4. Open a specific chat
    async function openThread(phone) {
        activePhone = normalizePhone(phone);
        unreadInActiveThread = false;

        if (rightContactName) rightContactName.textContent = contactsCache[activePhone] || activePhone;
        if (rightContactPhone) rightContactPhone.textContent = activePhone;
        if (contactInitial) contactInitial.textContent = (contactsCache[activePhone] || activePhone).charAt(0).toUpperCase();

        markActiveThreadRead(); // Immediately mark as read on click

        try {
            const [inbound, outbound] = await Promise.all([
                fetch(`/api/messages/?sender=${encodeURIComponent(activePhone)}`, { cache: 'no-store' }).then(r => r.json()),
                fetch(`/api/messages/?recipient=${encodeURIComponent(activePhone)}`, { cache: 'no-store' }).then(r => r.json())
            ]);

            const allMessages = [...inbound, ...outbound].sort((a, b) => parseUTCDate(a.timestamp) - parseUTCDate(b.timestamp));
            renderChatArea(allMessages);

        } catch (err) {
            console.error('Failed to load chat history', err);
        }
    }

    // Escape key logic to unload the thread
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            activePhone = null;
            unreadInActiveThread = false;
            stopAlert(); // Clear alerts just in case

            if (rightContactName) rightContactName.textContent = 'Select a conversation';
            if (rightContactPhone) rightContactPhone.textContent = '';
            if (contactInitial) contactInitial.textContent = '?';

            if (chatArea) {
                chatArea.innerHTML = `<div class="flex h-full items-center justify-center text-gray-400">No messages yet.</div>`;
            }

            loadThreads(); // Re-render sidebar to remove the blue selection highlight
        }
    });

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
        const msgSender = normalizePhone(msg.sender);
        const isOutbound = msgSender === SYSTEM_PHONE || !msgSender;

        const bubble = document.createElement('div');
        bubble.dataset.internalId = msg.id;
        bubble.className = `max-w-md p-3 rounded-2xl mb-2 chat-bubble-animate ${isOutbound ? 'bg-blue-500 text-white self-end ml-auto rounded-br-sm' : 'bg-white border border-gray-200 text-gray-800 self-start mr-auto rounded-bl-sm shadow-sm'}`;

        let contentHtml = '';
        const hasText = msg.body && msg.body.trim() !== '';
        const hasMedia = msg.attachments && msg.attachments.length > 0;

        if (hasText) {
            contentHtml += `<div class="text-sm leading-relaxed">${msg.body}</div>`;
        }

        if (hasMedia) {
            msg.attachments.forEach(att => {
                const contentType = att.content_type || '';
                const fileUrl = att.filename;
                const outBoundErrorColor = isOutbound ? 'text-blue-200' : 'text-gray-500';

                if (contentType.startsWith('image/')) {
                    contentHtml += `<img src="${fileUrl}" class="max-w-xs rounded mt-2" alt="Image Attachment" onerror="this.outerHTML='<div class=\\'text-sm italic mt-2 ${outBoundErrorColor}\\'>[Image link broken]</div>'" />`;
                } else if (contentType.startsWith('audio/')) {
                    contentHtml += `<audio controls src="${fileUrl}" class="mt-2 max-w-xs" onerror="this.outerHTML='<div class=\\'text-sm italic mt-2 ${outBoundErrorColor}\\'>[Audio link broken]</div>'"></audio>`;
                } else if (contentType.startsWith('video/')) {
                    contentHtml += `<video controls src="${fileUrl}" class="max-w-xs rounded mt-2" onerror="this.outerHTML='<div class=\\'text-sm italic mt-2 ${outBoundErrorColor}\\'>[Video link broken]</div>'"></video>`;
                } else {
                    const displayName = fileUrl.split('/').pop() || 'Download File';
                    const linkColor = isOutbound ? 'text-white' : 'text-blue-600';
                    contentHtml += `<a href="${fileUrl}" target="_blank" rel="noopener noreferrer" class="block mt-2 underline truncate max-w-xs ${linkColor}" title="Download ${displayName}">📎 ${displayName}</a>`;
                }
            });
        }

        if (!hasText && !hasMedia) {
            contentHtml = `<div class="text-sm italic ${isOutbound ? 'text-blue-200' : 'text-gray-500'}">[MMS absent]</div>`;
        }

        let statusHtml = '';
        if (isOutbound) {
            if (msg.is_failed) statusHtml = `<span class="text-red-300 text-xs ml-2" title="${msg.error_reason || 'Failed'}">❌</span>`;
            else if (msg.is_delivered) statusHtml = `<span class="text-blue-200 text-xs ml-2" title="Delivered">✓✓</span>`;
            else if (msg.is_sent) statusHtml = `<span class="text-gray-200 text-xs ml-2" title="Sent">✓</span>`;
            else statusHtml = `<span class="text-gray-300 text-xs ml-2" title="Sending">...</span>`;
        }

        const formattedDate = parseUTCDate(msg.timestamp).toLocaleString([], {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });

        bubble.innerHTML = `
            ${contentHtml}
            <div class="text-right text-[10px] mt-1 ${isOutbound ? 'text-blue-100' : 'text-gray-400'}">
                ${formattedDate}
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
                    stopAlert(); // Stop flashing if they are actively typing/sending
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

    // 7. Alerting Logic with Flashy Borders (No auto-timeout, requires interaction)
    function startAlert() {
        if (isAlerting) return;
        isAlerting = true;
        let showDot = false;

        alertInterval = setInterval(() => {
            document.title = showDot ? "🔴 New Message! - Messaging Center!" : originalTitle;
            // Toggles a heavy red inset shadow across the entire page body
            document.body.style.boxShadow = showDot ? 'inset 0 0 50px 20px rgba(255, 0, 0, 0.7)' : 'none';
            showDot = !showDot;
        }, 800);
    }

    function stopAlert() {
        isAlerting = false;
        clearInterval(alertInterval);
        document.title = originalTitle;
        document.body.style.boxShadow = 'none'; // Clear the red border
    }

    // 8. Listen to SSE Broadcasts
    window.addEventListener('sse:new_message', (e) => {
        const msg = e.detail;

        const normSender = normalizePhone(msg.sender);
        const normRecipient = normalizePhone(msg.recipient);

        let involvedPhone = null;
        if (normSender && normSender !== SYSTEM_PHONE) {
            involvedPhone = normSender;
        } else if (normRecipient && normRecipient !== SYSTEM_PHONE) {
            involvedPhone = normRecipient;
        }

        if (activePhone === involvedPhone && involvedPhone !== null) {
            appendMessageBubble(msg);

            // Mark the active thread as having unread items so hover can trigger the read state
            if (normSender && normSender !== SYSTEM_PHONE) {
                unreadInActiveThread = true;
            }
        }

        // Trigger flashy alerts for all inbound messages, regardless of active thread
        if (normSender && normSender !== SYSTEM_PHONE) {
            startAlert();
        }

        loadThreads();
    });

    window.addEventListener('sse:status_update', (e) => {
        if (activePhone) {
            // Check if thread is open, but do not clear unread state
            fetch(`/api/messages/?sender=${encodeURIComponent(activePhone)}`, { cache: 'no-store' }).then(r => r.json()).then(inbound => {
                fetch(`/api/messages/?recipient=${encodeURIComponent(activePhone)}`, { cache: 'no-store' }).then(r => r.json()).then(outbound => {
                    const allMessages = [...inbound, ...outbound].sort((a, b) => parseUTCDate(a.timestamp) - parseUTCDate(b.timestamp));
                    renderChatArea(allMessages);
                });
            });
        }
    });

    init();
});