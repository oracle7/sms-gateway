/**
 * app.js
 * Controls the main messaging interface (thread list and chat area).
 */
document.addEventListener('DOMContentLoaded', () => {
    function normalizePhone(phone, defaultCountryCode = '1') {
        if (!phone) return '';
        let cleaned = String(phone).trim().replace(/[^\d+]/g, '');
        const digits = cleaned.replace(/\D/g, '');
        if (!digits) return '';
        if (cleaned.startsWith('+')) return '+' + digits;
        if (digits.length === 10) return `+${defaultCountryCode}${digits}`;
        if (digits.length === 11 && digits.startsWith(defaultCountryCode)) return `+${digits}`;
        return `+${digits}`;
    }

    const SYSTEM_PHONE = normalizePhone(window.SYSTEM_PHONE || '+19296141937');

    function getInvolvedPhone(msg) {
        const normSender = normalizePhone(msg.sender);
        const normRecipient = normalizePhone(msg.recipient);
        if (normSender && normSender !== SYSTEM_PHONE) {
            return normSender;
        }
        if (normRecipient && normRecipient !== SYSTEM_PHONE) {
            return normRecipient;
        }
        return null;
    }

    const threadList = document.getElementById('thread-list');
    const chatArea = document.getElementById('chat-area');
    const messageForm = document.getElementById('message-form');
    const messageInput = document.getElementById('message-input');

    let activePhone = null;
    let userClosedThread = false;
    let contactsCache = {};
    let recentMessagesCache = [];
    let lastThreadsCache = {};
    let unreadInActiveThread = false;

    let isAlerting = false;
    let originalTitle = document.title;
    let alertInterval = null;
    let scrollTimers = [];

    function performScroll() {
        if (!chatArea) return;
        chatArea.scrollTop = chatArea.scrollHeight;
        const lastBubble = chatArea.lastElementChild;
        if (lastBubble && typeof lastBubble.scrollIntoView === 'function') {
            lastBubble.scrollIntoView({ block: 'end' });
        }
        chatArea.scrollTop = chatArea.scrollHeight;
    }

    function scrollToBottom() {
        if (!chatArea) return;
        scrollTimers.forEach(id => clearTimeout(id));
        scrollTimers = [];

        performScroll();
        requestAnimationFrame(() => {
            performScroll();
            requestAnimationFrame(performScroll);
        });
        scrollTimers.push(setTimeout(performScroll, 40));
        scrollTimers.push(setTimeout(performScroll, 120));
        scrollTimers.push(setTimeout(performScroll, 250));
    }

    function parseUTCDate(timestamp) {
        if (!timestamp) return new Date();
        let ts = timestamp;
        if (typeof ts === 'string' && !ts.endsWith('Z') && !ts.match(/[\+\-]\d{2}:\d{2}$/)) {
            ts += 'Z';
        }
        return new Date(ts);
    }

    async function init() {
        await loadContactsMap();
        const sortedPhones = await loadThreads();
        setupEmojiPicker();

        document.body.style.transition = 'box-shadow 0.3s ease-in-out';

        const urlParams = new URLSearchParams(window.location.search);
        const phoneParam = urlParams.get('phone');
        if (phoneParam) {
            await openThread(normalizePhone(phoneParam));
        } else if (!activePhone && !userClosedThread && sortedPhones && sortedPhones.length > 0) {
            await openThread(sortedPhones[0]);
        }
    }

    async function loadContactsMap() {
        try {
            const res = await fetch('/api/contacts/', { cache: 'no-store' });
            const contacts = await res.json();
            contacts.forEach(c => {
                contactsCache[normalizePhone(c.phone_number)] = c.name;
            });
        } catch (err) {
            console.error('Failed to load contacts map', err);
        }
    }

    async function loadThreads() {
        try {
            const res = await fetch('/api/messages/?limit=500', { cache: 'no-store' });
            const messages = await res.json();
            recentMessagesCache = messages;

            const threads = {};
            messages.forEach(msg => {
                const contactPhone = getInvolvedPhone(msg);
                if (!contactPhone) return;

                if (!threads[contactPhone]) {
                    threads[contactPhone] = { latestMsg: msg };
                }
            });

            lastThreadsCache = threads;
            const sortedPhones = renderSidebar(threads);

            // Reconcile active thread directly from recentMessagesCache so any message
            // visible in the sidebar is guaranteed to appear in the chat area too.
            if (activePhone && chatArea) {
                const activeCachedMsgs = messages
                    .filter(m => getInvolvedPhone(m) === activePhone)
                    .sort((a, b) => parseUTCDate(a.timestamp) - parseUTCDate(b.timestamp));

                let reconciled = false;
                activeCachedMsgs.forEach(msg => {
                    const existingBubble = chatArea.querySelector(`[data-internal-id="${msg.id}"]`);
                    const expectedBodyHash = `${msg.body || ''}::${(msg.attachments || []).length}`;
                    if (!existingBubble || existingBubble.dataset.bodyHash !== expectedBodyHash) {
                        if (!chatArea.querySelector('[data-internal-id]') && chatArea.children.length > 0) {
                            chatArea.innerHTML = '';
                        }
                        appendMessageBubble(msg, { animate: !existingBubble, autoScroll: false });
                        reconciled = true;
                    }
                });

                if (reconciled) {
                    scrollToBottom();
                }
            }

            const hasUnread = sortedPhones.some(phone => {
                const msg = threads[phone].latestMsg;
                const msgSender = normalizePhone(msg.sender);
                const isOutbound = msgSender === SYSTEM_PHONE || !msgSender;
                const suppressActiveUnread = activePhone === phone && !unreadInActiveThread;
                return !isOutbound && !suppressActiveUnread && (msg.web_viewed === false || msg.web_viewed === 0);
            });
            if (!hasUnread) {
                stopAlert();
            }

            return sortedPhones;
        } catch (err) {
            console.error('Failed to load threads', err);
            return [];
        }
    }

    function renderSidebar(threads) {
        const sortedPhones = Object.keys(threads).sort((a, b) => {
            return parseUTCDate(threads[b].latestMsg.timestamp) - parseUTCDate(threads[a].latestMsg.timestamp);
        });

        if (!threadList) return sortedPhones;
        threadList.innerHTML = '';

        sortedPhones.forEach(phone => {
            const data = threads[phone];
            const name = contactsCache[phone] || phone;
            const previewText = data.latestMsg.body || 'Media message';

            const msgSender = normalizePhone(data.latestMsg.sender);
            const isOutbound = msgSender === SYSTEM_PHONE || !msgSender;
            const suppressActiveUnread = activePhone === phone && !unreadInActiveThread;
            const isUnread = !isOutbound && !suppressActiveUnread && (data.latestMsg.web_viewed === false || data.latestMsg.web_viewed === 0);

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

        return sortedPhones;
    }

    function markActiveThreadRead() {
        if (!activePhone) return;
        unreadInActiveThread = false;
        fetch('/api/messages/mark-read/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone: activePhone })
        }).then(() => {
            stopAlert();
            loadThreads();
        }).catch(err => console.error('Failed to mark thread as read', err));
    }

    if (chatArea) {
        const handleInteraction = () => {
            if (unreadInActiveThread) {
                markActiveThreadRead();
            }
        };
        chatArea.addEventListener('mouseenter', handleInteraction);
        chatArea.addEventListener('mousemove', handleInteraction);
    }

    function getStatusHtml(msg, isOutbound) {
        if (!isOutbound) return '';
        if (msg.is_failed) return `<span class="text-red-300 text-xs ml-2" title="${msg.error_reason || 'Failed'}">❌</span>`;
        if (msg.is_delivered) return `<span class="text-blue-200 text-xs ml-2" title="Delivered">✓✓</span>`;
        if (msg.is_sent) return `<span class="text-gray-200 text-xs ml-2" title="Sent">✓</span>`;
        return `<span class="text-gray-300 text-xs ml-2" title="Sending">...</span>`;
    }

    async function syncActiveThread(options = { forceScroll: false, forceRender: false }) {
        const targetPhone = activePhone;
        if (!targetPhone) return;

        try {
            const [inbound, outbound] = await Promise.all([
                fetch(`/api/messages/?sender=${encodeURIComponent(targetPhone)}`, { cache: 'no-store' }).then(r => r.json()),
                fetch(`/api/messages/?recipient=${encodeURIComponent(targetPhone)}`, { cache: 'no-store' }).then(r => r.json())
            ]);

            if (activePhone !== targetPhone) return;

            const cachedForTarget = recentMessagesCache.filter(m => getInvolvedPhone(m) === targetPhone);
            const msgMap = new Map();
            cachedForTarget.forEach(m => msgMap.set(m.id, m));
            [...inbound, ...outbound].forEach(m => msgMap.set(m.id, m));
            const allMessages = Array.from(msgMap.values()).sort((a, b) => parseUTCDate(a.timestamp) - parseUTCDate(b.timestamp));

            if (!chatArea) return;

            if (options.forceRender || !chatArea.querySelector('[data-internal-id]')) {
                renderChatArea(allMessages);
                return;
            }

            let addedOrUpdated = false;
            allMessages.forEach(msg => {
                const existingBubble = chatArea.querySelector(`[data-internal-id="${msg.id}"]`);
                const expectedBodyHash = `${msg.body || ''}::${(msg.attachments || []).length}`;
                if (!existingBubble || existingBubble.dataset.bodyHash !== expectedBodyHash) {
                    appendMessageBubble(msg, { animate: !existingBubble, autoScroll: false });
                    addedOrUpdated = true;
                } else {
                    const statusEl = existingBubble.querySelector('.msg-status-indicator');
                    if (statusEl) {
                        const msgSender = normalizePhone(msg.sender);
                        const isOutbound = msgSender === SYSTEM_PHONE || !msgSender;
                        const nextStatusHtml = getStatusHtml(msg, isOutbound);
                        if (statusEl.innerHTML !== nextStatusHtml) {
                            statusEl.innerHTML = nextStatusHtml;
                            addedOrUpdated = true;
                        }
                    }
                }
            });

            if (addedOrUpdated || options.forceScroll) {
                scrollToBottom();
            }
        } catch (err) {
            console.error('Failed to load chat history', err);
        }
    }

    async function openThread(phone) {
        const normalized = normalizePhone(phone);
        userClosedThread = false;
        if (chatArea) {
            chatArea.innerHTML = '';
        }
        activePhone = normalized;
        unreadInActiveThread = false;

        renderSidebar(lastThreadsCache);
        markActiveThreadRead();
        await syncActiveThread({ forceScroll: true, forceRender: true });
    }

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            userClosedThread = true;
            activePhone = null;
            unreadInActiveThread = false;
            stopAlert();

            // Also hide picker if escape is pressed
            const picker = document.querySelector('emoji-picker');
            if (picker) picker.classList.add('hidden');

            if (chatArea) {
                chatArea.innerHTML = `<div class="flex h-full items-center justify-center text-gray-400">No messages yet.</div>`;
            }

            loadThreads();
        }
    });

    function renderChatArea(messages) {
        if (!chatArea) return;
        chatArea.innerHTML = '';

        if (messages.length === 0) {
            chatArea.innerHTML = `<div class="flex h-full items-center justify-center text-gray-400">No messages yet.</div>`;
            return;
        }

        messages.forEach(msg => appendMessageBubble(msg, { animate: false, autoScroll: false }));
        scrollToBottom();
    }

    function appendMessageBubble(msg, options = { animate: true, autoScroll: true }) {
        if (!chatArea) return;
        const animate = options.animate !== false;
        const autoScroll = options.autoScroll !== false;
        const msgSender = normalizePhone(msg.sender);
        const isOutbound = msgSender === SYSTEM_PHONE || !msgSender;

        const bubble = document.createElement('div');
        bubble.dataset.internalId = msg.id;
        bubble.dataset.bodyHash = `${msg.body || ''}::${(msg.attachments || []).length}`;

        bubble.className = `group relative shrink-0 max-w-md p-3 rounded-2xl mb-2 ${animate ? 'chat-bubble-animate ' : ''}${isOutbound ? 'bg-blue-500 text-white self-end ml-auto rounded-br-sm' : 'bg-white border border-gray-200 text-gray-800 self-start mr-auto rounded-bl-sm shadow-sm'}`;

        let contentHtml = '';
        const hasText = msg.body && msg.body.trim() !== '';
        const hasMedia = msg.attachments && msg.attachments.length > 0;

        if (hasText) {
            contentHtml += `<div class="text-sm leading-relaxed pr-6 whitespace-pre-wrap">${msg.body}</div>`;
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

        const statusHtml = `<span class="msg-status-indicator">${getStatusHtml(msg, isOutbound)}</span>`;

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

        bubble.querySelectorAll('img, video').forEach(mediaEl => {
            mediaEl.addEventListener('load', scrollToBottom);
            mediaEl.addEventListener('loadedmetadata', scrollToBottom);
        });

        if (hasText) {
            const copyBtn = document.createElement('button');
            copyBtn.className = `opacity-0 group-hover:opacity-100 transition-opacity absolute top-2 right-2 p-1.5 rounded-md shadow-sm z-10 flex items-center justify-center ${isOutbound ? 'bg-blue-600 text-blue-100 hover:bg-blue-700 hover:text-white' : 'bg-gray-100 text-gray-500 hover:bg-gray-200 hover:text-gray-700'}`;
            copyBtn.title = "Copy text";
            copyBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>`;
            copyBtn.onclick = () => {
                navigator.clipboard.writeText(msg.body).then(() => {
                    const origHtml = copyBtn.innerHTML;
                    copyBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>`;
                    setTimeout(() => copyBtn.innerHTML = origHtml, 2000);
                }).catch(err => console.error('Failed to copy text', err));
            };
            bubble.appendChild(copyBtn);
        }

        const existingBubble = chatArea.querySelector(`[data-internal-id="${msg.id}"]`);
        if (existingBubble) {
            if (typeof existingBubble.replaceWith === 'function') {
                existingBubble.replaceWith(bubble);
            } else {
                chatArea.replaceChild(bubble, existingBubble);
            }
        } else {
            chatArea.appendChild(bubble);
        }
        if (autoScroll) {
            scrollToBottom();
        }
    }

    if (messageForm && messageInput) {
        messageInput.addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
            if (this.value === '') this.style.height = '44px';
        });

        messageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                if (messageInput.value.trim() !== '') {
                    messageForm.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
                }
            }
        });

        messageForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!activePhone) return alert("Select a thread first!");

            const body = messageInput.value.trim();
            if (!body) return;

            messageInput.value = '';
            messageInput.style.height = '44px';

            try {
                const res = await fetch('/api/messages/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ recipient: activePhone, body: body })
                });

                if (res.ok) {
                    const newMsg = await res.json();
                    if (!chatArea.querySelector('[data-internal-id]') && chatArea.children.length > 0) {
                        chatArea.innerHTML = '';
                    }
                    if (!chatArea.querySelector(`[data-internal-id="${newMsg.id}"]`)) {
                        appendMessageBubble(newMsg);
                    }
                    scrollToBottom();
                    stopAlert();
                    loadThreads();
                }
            } catch (err) {
                console.error('Send failed', err);
            }
        });
    }

    function setupEmojiPicker() {
        const picker = document.querySelector('emoji-picker');
        const toggleBtn = document.getElementById('emoji-toggle-btn');
        if (!picker || !messageInput) return;

        // Toggle the picker when clicking the smiley button
        if (toggleBtn) {
            toggleBtn.addEventListener('click', (e) => {
                e.preventDefault();
                picker.classList.toggle('hidden');
            });
        }

        // Insert emoji and auto-resize
        picker.addEventListener('emoji-click', event => {
            const emoji = event.detail.unicode;
            const start = messageInput.selectionStart;
            const end = messageInput.selectionEnd;
            const text = messageInput.value;

            messageInput.value = text.slice(0, start) + emoji + text.slice(end);
            messageInput.focus();
            messageInput.selectionStart = messageInput.selectionEnd = start + emoji.length;

            messageInput.dispatchEvent(new Event('input'));
        });

        // Hide the picker when clicking outside of it
        document.addEventListener('click', (e) => {
            if (toggleBtn && !picker.contains(e.target) && !toggleBtn.contains(e.target)) {
                picker.classList.add('hidden');
            }
        });
    }

    function startAlert() {
        if (isAlerting) return;
        isAlerting = true;
        let showDot = false;

        alertInterval = setInterval(() => {
            document.title = showDot ? "🔴 New Message! - Messaging Center!" : originalTitle;
            document.body.style.boxShadow = showDot ? 'inset 0 0 50px 20px rgba(255, 0, 0, 0.7)' : 'none';
            showDot = !showDot;
        }, 800);
    }

    function stopAlert() {
        isAlerting = false;
        clearInterval(alertInterval);
        document.title = originalTitle;
        document.body.style.boxShadow = 'none';
    }

    window.addEventListener('sse:new_message', (e) => {
        const msg = e.detail;

        const normSender = normalizePhone(msg.sender);
        const involvedPhone = getInvolvedPhone(msg);
        const isInbound = Boolean(normSender && normSender !== SYSTEM_PHONE);

        if (activePhone === involvedPhone && involvedPhone !== null) {
            if (chatArea && !chatArea.querySelector('[data-internal-id]') && chatArea.children.length > 0) {
                chatArea.innerHTML = '';
            }
            appendMessageBubble(msg, { animate: true, autoScroll: true });
            scrollToBottom();

            if (isInbound) {
                if (document.visibilityState === 'visible') {
                    markActiveThreadRead();
                } else {
                    unreadInActiveThread = true;
                    startAlert();
                }
            }
        } else if (!activePhone && !userClosedThread && involvedPhone !== null) {
            openThread(involvedPhone);
        } else if (isInbound) {
            startAlert();
        }

        loadThreads();
    });

    window.addEventListener('sse:status_update', () => {
        if (activePhone) {
            syncActiveThread({ forceScroll: true });
        }
    });

    window.addEventListener('sse:thread_read', (e) => {
        if (e.detail && normalizePhone(e.detail.phone) === activePhone) {
            unreadInActiveThread = false;
        }
        loadThreads();
    });

    window.addEventListener('sse:reconnected', () => {
        loadThreads();
        if (activePhone) {
            syncActiveThread({ forceScroll: false });
        }
    });

    function handleReturnToApp() {
        if (unreadInActiveThread) {
            markActiveThreadRead();
        }
        loadThreads();
        if (activePhone) {
            syncActiveThread({ forceScroll: false });
        }
    }

    window.addEventListener('focus', handleReturnToApp);
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            handleReturnToApp();
        }
    });

    setInterval(() => {
        loadThreads();
        if (activePhone) {
            syncActiveThread({ forceScroll: false });
        }
    }, 30000);

    init();
});