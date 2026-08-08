/**
 * app.js
 * Controls the main messaging interface (thread list and chat area).
 */
document.addEventListener('DOMContentLoaded', () => {
    const threadList = document.getElementById('thread-list');
    const chatArea = document.getElementById('chat-area');
    const messageForm = document.getElementById('message-form');
    const messageInput = document.getElementById('message-input');
    const currentContactName = document.getElementById('current-contact-name');

    let activePhone = null;
    let contactsCache = {};

    // 1. Boot up
    async function init() {
        await loadContactsMap();
        await loadThreads();

        // Check if we came from the Contacts page via a "Start Chat" link
        const urlParams = new URLSearchParams(window.location.search);
        const phoneParam = urlParams.get('phone');
        if (phoneParam) {
            openThread(phoneParam);
        }
    }

    // 2. Fetch contacts for name resolution
    async function loadContactsMap() {
        try {
            const res = await fetch('/api/contacts/');
            const contacts = await res.json();
            contacts.forEach(c => {
                contactsCache[c.phone_number] = c.name;
            });
        } catch (err) {
            console.error('Failed to load contacts map', err);
        }
    }

    // 3. Load the left sidebar threads
    async function loadThreads() {
        try {
            const res = await fetch('/api/messages/?limit=500');
            const messages = await res.json();

            // Group by contact
            const threads = {};
            messages.forEach(msg => {
                const contactPhone = msg.sender || msg.recipient;
                if (!contactPhone) return;

                if (!threads[contactPhone]) {
                    threads[contactPhone] = {
                        latestMsg: msg,
                        unread: 0 // Placeholder for future unread logic
                    };
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

        Object.keys(threads).forEach(phone => {
            const data = threads[phone];
            const name = contactsCache[phone] || phone;
            const previewText = data.latestMsg.body || 'Media message';

            const el = document.createElement('div');
            el.className = `p-4 border-b cursor-pointer hover:bg-gray-100 ${activePhone === phone ? 'bg-gray-200' : ''}`;
            el.innerHTML = `
                <div class="font-bold truncate">${name}</div>
                <div class="text-sm text-gray-600 truncate">${previewText}</div>
            `;
            el.onclick = () => openThread(phone);
            threadList.appendChild(el);
        });
    }

    // 4. Open a specific chat
    async function openThread(phone) {
        activePhone = phone;
        if (currentContactName) {
            currentContactName.textContent = contactsCache[phone] || phone;
        }

        // Highlight active thread in sidebar
        loadThreads();

        try {
            const [inbound, outbound] = await Promise.all([
                fetch(`/api/messages/?sender=${encodeURIComponent(phone)}`).then(r => r.json()),
                fetch(`/api/messages/?recipient=${encodeURIComponent(phone)}`).then(r => r.json())
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

        messages.forEach(msg => appendMessageBubble(msg));
        chatArea.scrollTop = chatArea.scrollHeight;
    }

    function appendMessageBubble(msg) {
        if (!chatArea) return;
        const isOutbound = msg.sender === null;

        const bubble = document.createElement('div');
        bubble.dataset.internalId = msg.id;
        bubble.className = `max-w-md p-3 rounded-lg mb-2 ${isOutbound ? 'bg-blue-500 text-white self-end ml-auto' : 'bg-gray-200 text-black self-start mr-auto'}`;

        let mediaHtml = '';
        if (msg.attachments && msg.attachments.length > 0) {
            msg.attachments.forEach(att => {
                mediaHtml += `<img src="${att.filename}" class="max-w-xs rounded mt-2" />`;
            });
        }

        // Checkmarks for outbound
        let statusHtml = '';
        if (isOutbound) {
            if (msg.is_failed) statusHtml = `<span class="text-red-300 text-xs ml-2" title="${msg.error_reason || 'Failed'}">❌</span>`;
            else if (msg.is_delivered) statusHtml = `<span class="text-blue-200 text-xs ml-2" title="Delivered">✓✓</span>`;
            else if (msg.is_sent) statusHtml = `<span class="text-gray-300 text-xs ml-2" title="Sent">✓</span>`;
            else statusHtml = `<span class="text-gray-300 text-xs ml-2" title="Sending">...</span>`;
        }

        bubble.innerHTML = `
            <div>${msg.body}</div>
            ${mediaHtml}
            <div class="text-right text-xs mt-1 opacity-75">
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
                    loadThreads(); // Refresh sidebar preview
                }
            } catch (err) {
                console.error('Send failed', err);
            }
        });
    }

    // 6. Listen to SSE Broadcasts
    window.addEventListener('sse:new_message', (e) => {
        const msg = e.detail;
        const involvedPhone = msg.sender || msg.recipient;

        if (activePhone === involvedPhone) {
            appendMessageBubble(msg);
        }
        loadThreads();
    });

    window.addEventListener('sse:status_update', (e) => {
        const data = e.detail;
        // Since we don't reload the whole UI, we just find the bubble and update it.
        // For a simpler approach, re-fetching the active thread also works perfectly.
        if (activePhone) {
            openThread(activePhone);
        }
    });

    init();
});