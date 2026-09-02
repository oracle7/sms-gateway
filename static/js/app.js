/**
 * app.js
 * Controls the main messaging interface (thread list, chat area, and sidebars).
 */
document.addEventListener('DOMContentLoaded', () => {
    const SYSTEM_PHONE = '+19296141937';

    const threadList = document.getElementById('thread-list');
    const chatArea = document.getElementById('chat-area');
    const messageForm = document.getElementById('message-form');
    const messageInput = document.getElementById('message-input');

    const rightContactName = document.getElementById('right-contact-name');
    const rightContactPhone = document.getElementById('right-contact-phone');
    const contactInitial = document.getElementById('contact-initial');

    let activePhone = null;
    let contactsCache = {};
    let unreadInActiveThread = false; 

    let isAlerting = false;
    let originalTitle = document.title;
    let alertInterval = null;

    function normalizePhone(phone, defaultCountryCode = '1') {
        if (!phone) return '';
        let cleaned = phone.trim().replace(/[^\d+]/g, '');
        if (cleaned.startsWith('+')) return '+' + cleaned.replace(/\D/g, '');
        if (cleaned.length === 10) return `+${defaultCountryCode}${cleaned}`;
        if (cleaned.length === 11 && cleaned.startsWith(defaultCountryCode)) return `+${cleaned}`;
        return `+${cleaned}`;
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
        await loadThreads();
        setupEmojiPicker();

        document.body.style.transition = 'box-shadow 0.3s ease-in-out';

        const urlParams = new URLSearchParams(window.location.search);
        const phoneParam = urlParams.get('phone');
        if (phoneParam) {
            openThread(normalizePhone(phoneParam));
        }
    }

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

    function markActiveThreadRead() {
        if (!activePhone) return;
        fetch('/api/messages/mark-read/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone: activePhone })
        }).then(() => {
            unreadInActiveThread = false;
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

    async function openThread(phone) {
        activePhone = normalizePhone(phone);
        unreadInActiveThread = false;

        if (rightContactName) rightContactName.textContent = contactsCache[activePhone] || activePhone;
        if (rightContactPhone) rightContactPhone.textContent = activePhone;
        if (contactInitial) contactInitial.textContent = (contactsCache[activePhone] || activePhone).charAt(0).toUpperCase();

        markActiveThreadRead(); 

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

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            activePhone = null;
            unreadInActiveThread = false;
            stopAlert(); 

            if (rightContactName) rightContactName.textContent = 'Select a conversation';
            if (rightContactPhone) rightContactPhone.textContent = '';
            if (contactInitial) contactInitial.textContent = '?';

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

        messages.forEach(msg => appendMessageBubble(msg));
        chatArea.scrollTop = chatArea.scrollHeight;
    }

    function appendMessageBubble(msg) {
        if (!chatArea) return;
        const msgSender = normalizePhone(msg.sender);
        const isOutbound = msgSender === SYSTEM_PHONE || !msgSender;

        const bubble = document.createElement('div');
        bubble.dataset.internalId = msg.id;
        
        // Notice the 'group relative' classes added here for the hover effect
        bubble.className = `group relative max-w-md p-3 rounded-2xl mb-2 chat-bubble-animate ${isOutbound ? 'bg-blue-500 text-white self-end ml-auto rounded-br-sm' : 'bg-white border border-gray-200 text-gray-800 self-start mr-auto rounded-bl-sm shadow-sm'}`;

        let contentHtml = '';
        const hasText = msg.body && msg.body.trim() !== '';
        const hasMedia = msg.attachments && msg.attachments.length > 0;

        if (hasText) {
            // whitespace-pre-wrap ensures [SHIFT]+[ENTER] linebreaks render correctly
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

        // Inject the Copy Button if there is text to copy
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

        chatArea.appendChild(bubble);
        chatArea.scrollTop = chatArea.scrollHeight;
    }

    if (messageForm && messageInput) {
        // Handle Auto-resizing
        messageInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
            if (this.value === '') this.style.height = '44px';
        });

        // Handle Enter (Send) vs Shift+Enter (New Line)
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
            messageInput.style.height = '44px'; // Reset height after sending

            try {
                const res = await fetch('/api/messages/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ recipient: activePhone, body: body })
                });

                if (res.ok) {
                    const newMsg = await res.json();
                    appendMessageBubble(newMsg);
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
        const toggleBtn = document.getElementById('emoji-toggle-btn'); // Your emoji trigger button

        if (!picker || !messageInput) return;

        // Toggle picker visibility on button click (if you have a toggle button)
        if (toggleBtn) {
            toggleBtn.addEventListener('click', (e) => {
                e.preventDefault();
                picker.classList.toggle('hidden');
            });
        }

        // Handle selecting an emoji from the picker
        picker.addEventListener('emoji-click', event => {
            const emoji = event.detail.unicode;
            const start = messageInput.selectionStart;
            const end = messageInput.selectionEnd;
            const text = messageInput.value;

            // Insert emoji at cursor position
            messageInput.value = text.slice(0, start) + emoji + text.slice(end);
            messageInput.focus();
            messageInput.selectionStart = messageInput.selectionEnd = start + emoji.length;

            // Trigger input event to auto-resize the compose box
            messageInput.dispatchEvent(new Event('input'));
        });

        // Close picker when clicking outside of it
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
        const normRecipient = normalizePhone(msg.recipient);

        let involvedPhone = null;
        if (normSender && normSender !== SYSTEM_PHONE) {
            involvedPhone = normSender;
        } else if (normRecipient && normRecipient !== SYSTEM_PHONE) {
            involvedPhone = normRecipient;
        }

        if (activePhone === involvedPhone && involvedPhone !== null) {
            appendMessageBubble(msg);

            if (normSender && normSender !== SYSTEM_PHONE) {
                unreadInActiveThread = true;
            }
        }

        if (normSender && normSender !== SYSTEM_PHONE) {
            startAlert();
        }

        loadThreads();
    });

    window.addEventListener('sse:status_update', (e) => {
        if (activePhone) {
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