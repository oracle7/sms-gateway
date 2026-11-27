/**
 * app.js
 * Controls the messaging workspace (paginated threads, chat history, soft-delete,
 * reliable SMS sending, and real-time SSE reconciliation).
 */
document.addEventListener('DOMContentLoaded', () => {
    const { apiFetch } = window.ClinicApi;
    const isAdmin = (document.body.dataset.userRole || '') === 'admin';

    function normalizePhone(phone, defaultCountryCode = '1') {
        if (!phone) return '';
        const text = String(phone).trim();
        if (!text || text.toLowerCase() === 'unknown') return 'unknown';
        const digits = text.replace(/\D/g, '');
        if (!digits) return text;
        if (digits.length >= 3 && digits.length <= 6) return digits;
        if (digits.length === 10) return `+${defaultCountryCode}${digits}`;
        if (digits.length === 11 && digits.startsWith(defaultCountryCode)) return `+${digits}`;
        return `+${digits}`;
    }

    function formatPhoneDisplay(phone) {
        if (!phone || phone === 'unknown') return 'Unknown Sender';
        if (phone.length === 12 && phone.startsWith('+1') && /^\d+$/.test(phone.slice(2))) {
            return `(${phone.slice(2, 5)}) ${phone.slice(5, 8)}-${phone.slice(8, 12)}`;
        }
        return phone;
    }

    function parseUTCDate(timestamp) {
        if (!timestamp) return new Date();
        let ts = timestamp;
        if (typeof ts === 'string' && !ts.endsWith('Z') && !/[\+\-]\d{2}:\d{2}$/.test(ts)) {
            ts += 'Z';
        }
        return new Date(ts);
    }

    function formatShortTime(ts) {
        if (!ts) return '';
        const d = parseUTCDate(ts);
        return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    }

    const threadListEl = document.getElementById('thread-list');
    const threadSearchEl = document.getElementById('thread-search');
    const tabInboxBtn = document.getElementById('tab-inbox');
    const tabArchivedBtn = document.getElementById('tab-archived');
    const threadsLoadMoreWrap = document.getElementById('threads-load-more-wrap');
    const threadsLoadMoreBtn = document.getElementById('threads-load-more-btn');

    const chatHeaderEl = document.getElementById('chat-header');
    const chatContactNameEl = document.getElementById('chat-contact-name');
    const chatContactPhoneEl = document.getElementById('chat-contact-phone');
    const archiveThreadBtn = document.getElementById('archive-thread-btn');
    const showHiddenToggle = document.getElementById('show-hidden-toggle');
    const chatAreaEl = document.getElementById('chat-area');

    const messageForm = document.getElementById('message-form');
    const messageInput = document.getElementById('message-input');
    const sendBtn = document.getElementById('send-btn');
    const composerErrorEl = document.getElementById('composer-error');

    const newChatBtn = document.getElementById('new-chat-btn');
    const newChatModal = document.getElementById('new-chat-modal');
    const newChatForm = document.getElementById('new-chat-form');
    const newChatSelect = document.getElementById('new-chat-contact-select');
    const newChatPhoneInput = document.getElementById('new-chat-phone');

    let activePhone = null;
    let activeThreadArchived = false;
    let userClosedThread = false;
    let unreadInActiveThread = false;
    let threadStatusTab = 'active';
    let threadSearchQuery = '';
    let threadsLimit = 50;
    let threadsCache = [];
    let hasMoreMessages = false;
    let oldestBeforeTs = null;
    let oldestBeforeId = null;
    let shouldStickToBottom = true;
    let stickTimer = null;

    function showComposerError(msg) {
        if (!composerErrorEl) return;
        if (!msg) {
            composerErrorEl.classList.add('hidden');
            composerErrorEl.textContent = '';
            return;
        }
        composerErrorEl.textContent = msg;
        composerErrorEl.classList.remove('hidden');
    }

    function performScroll() {
        if (!chatAreaEl) return;
        chatAreaEl.scrollTop = chatAreaEl.scrollHeight + 10000;
        const lastBubble = chatAreaEl.lastElementChild;
        if (lastBubble && typeof lastBubble.scrollIntoView === 'function') {
            lastBubble.scrollIntoView({ block: 'end' });
        }
        chatAreaEl.scrollTop = chatAreaEl.scrollHeight + 10000;
    }

    function scrollToBottom() {
        if (!chatAreaEl) return;
        shouldStickToBottom = true;
        if (stickTimer) clearTimeout(stickTimer);
        stickTimer = setTimeout(() => { shouldStickToBottom = false; }, 500);

        performScroll();
        requestAnimationFrame(() => {
            performScroll();
            requestAnimationFrame(performScroll);
        });
        setTimeout(performScroll, 60);
        setTimeout(performScroll, 180);
    }

    if (chatAreaEl && typeof ResizeObserver !== 'undefined') {
        const obs = new ResizeObserver(() => {
            if (shouldStickToBottom) performScroll();
        });
        obs.observe(chatAreaEl);
    }

    async function loadThreads(options = { background: false }) {
        try {
            const params = new URLSearchParams({
                status: threadStatusTab,
                limit: String(threadsLimit),
                offset: '0',
            });
            if (threadSearchQuery) params.set('q', threadSearchQuery);

            const headers = options.background ? { 'X-Background-Sync': '1' } : {};
            const res = await apiFetch('/api/threads?' + params.toString(), { cache: 'no-store', headers });
            if (!res.ok) return [];
            const data = await res.json();
            threadsCache = data.items || [];

            if (window.ClinicNotify) {
                window.ClinicNotify.setUnreadCount(data.total_unread_active || 0);
            }
            if (threadsLoadMoreWrap) {
                threadsLoadMoreWrap.classList.toggle('hidden', !data.has_more);
            }
            renderSidebar(threadsCache);
            return threadsCache;
        } catch (err) {
            console.error('Failed to load threads', err);
            return [];
        }
    }

    function renderSidebar(items) {
        if (!threadListEl) return;
        threadListEl.textContent = '';

        if (!items || items.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'chat-empty-state';
            empty.style.padding = '28px 16px';
            empty.textContent = threadStatusTab === 'archived'
                ? 'No archived conversations.'
                : 'No conversations found.';
            threadListEl.appendChild(empty);
            return;
        }

        items.forEach((t) => {
            const isActive = activePhone === t.contact_phone;
            const isUnread = (t.unread_count || 0) > 0 && !(isActive && !unreadInActiveThread);

            const item = document.createElement('div');
            item.className = 'thread-item';
            if (isActive) item.classList.add('active');
            else if (isUnread) item.classList.add('unread');

            const topRow = document.createElement('div');
            topRow.className = 'thread-row-top';

            const nameEl = document.createElement('div');
            nameEl.className = 'thread-name';
            nameEl.textContent = t.contact_name || formatPhoneDisplay(t.contact_phone);

            const timeEl = document.createElement('div');
            timeEl.className = 'thread-time';
            timeEl.textContent = formatShortTime(t.last_message_at);

            topRow.appendChild(nameEl);
            topRow.appendChild(timeEl);

            const bottomRow = document.createElement('div');
            bottomRow.className = 'thread-row-bottom';

            const previewEl = document.createElement('div');
            previewEl.className = 'thread-preview';
            previewEl.textContent = t.last_message_preview || 'No messages yet';

            bottomRow.appendChild(previewEl);

            if (isUnread) {
                const badge = document.createElement('span');
                badge.className = 'unread-badge';
                badge.textContent = String(t.unread_count);
                bottomRow.appendChild(badge);
            }

            item.appendChild(topRow);
            item.appendChild(bottomRow);
            item.addEventListener('click', () => openThread(t.contact_phone));
            threadListEl.appendChild(item);
        });
    }

    function createStatusSpan(msg) {
        const span = document.createElement('span');
        span.className = 'msg-status-indicator';
        if (msg.direction !== 'outbound') return span;

        if (msg.is_failed) {
            span.className += ' msg-status-failed';
            span.textContent = '❌ Failed';
            span.title = msg.error_reason || 'Failed to send';
        } else if (msg.is_cancelled) {
            span.textContent = 'Cancelled';
        } else if (msg.is_delivered) {
            span.textContent = '✓✓';
            span.title = 'Delivered';
        } else if (msg.is_sent) {
            span.textContent = '✓';
            span.title = 'Sent';
        } else {
            span.textContent = '...';
            span.title = 'Sending';
        }
        return span;
    }

    function buildBubbleNode(msg, animate = false) {
        const isOutbound = msg.direction === 'outbound';
        const bubble = document.createElement('div');
        bubble.className = `msg-bubble ${isOutbound ? 'outbound' : 'inbound'}`;
        if (animate) bubble.classList.add('animate');
        if (msg.deleted_at) bubble.classList.add('hidden-msg');

        bubble.dataset.internalId = msg.id;
        bubble.dataset.statusKey = `${msg.status}|${msg.is_sent}|${msg.is_delivered}|${msg.is_failed}|${Boolean(msg.deleted_at)}`;

        const hasText = Boolean(msg.body && msg.body.trim() !== '');
        const hasMedia = Boolean(msg.attachments && msg.attachments.length > 0);

        if (hasText) {
            const textEl = document.createElement('div');
            textEl.className = 'msg-text';
            textEl.textContent = msg.body;
            bubble.appendChild(textEl);
        }

        if (hasMedia) {
            const mediaWrap = document.createElement('div');
            mediaWrap.className = 'msg-attachments';

            msg.attachments.forEach((att) => {
                const ct = (att.content_type || '').toLowerCase();
                if (ct.startsWith('image/')) {
                    const link = document.createElement('a');
                    link.href = att.url;
                    link.target = '_blank';
                    link.rel = 'noopener noreferrer';
                    const img = document.createElement('img');
                    img.src = att.url;
                    img.alt = att.filename || 'Image attachment';
                    img.className = 'msg-media-img';
                    img.addEventListener('load', () => {
                        if (shouldStickToBottom) scrollToBottom();
                    });
                    link.appendChild(img);
                    mediaWrap.appendChild(link);
                } else if (ct.startsWith('audio/')) {
                    const audio = document.createElement('audio');
                    audio.controls = true;
                    audio.src = att.url;
                    audio.className = 'msg-media-audio';
                    mediaWrap.appendChild(audio);
                } else if (ct.startsWith('video/')) {
                    const video = document.createElement('video');
                    video.controls = true;
                    video.src = att.url;
                    video.className = 'msg-media-video';
                    video.addEventListener('loadedmetadata', () => {
                        if (shouldStickToBottom) scrollToBottom();
                    });
                    mediaWrap.appendChild(video);
                } else {
                    const link = document.createElement('a');
                    link.href = att.url;
                    link.target = '_blank';
                    link.rel = 'noopener noreferrer';
                    link.className = 'msg-media-link';
                    link.textContent = '📎 ' + (att.filename || 'Download attachment');
                    mediaWrap.appendChild(link);
                }
            });
            bubble.appendChild(mediaWrap);
        }

        if (!hasText && !hasMedia) {
            const emptyEl = document.createElement('div');
            emptyEl.className = 'msg-absent';
            emptyEl.textContent = '[MMS attachment absent]';
            bubble.appendChild(emptyEl);
        }

        // Metadata footer (Sender display name for v3 outbound, timestamp, status)
        const meta = document.createElement('div');
        meta.className = 'msg-meta';
        const parts = [];
        if (isOutbound && msg.sent_by_display_name) {
            parts.push(msg.sent_by_display_name);
        }
        parts.push(formatShortTime(msg.timestamp));
        if (msg.deleted_at) {
            parts.push('[Hidden]');
        }
        const metaText = document.createElement('span');
        metaText.textContent = parts.join(' · ');
        meta.appendChild(metaText);
        meta.appendChild(createStatusSpan(msg));
        bubble.appendChild(meta);

        // Hover actions (Copy + Hide / Restore)
        const actions = document.createElement('div');
        actions.className = 'msg-actions';

        if (hasText && navigator.clipboard) {
            const copyBtn = document.createElement('button');
            copyBtn.type = 'button';
            copyBtn.className = 'msg-action-btn';
            copyBtn.textContent = 'Copy';
            copyBtn.addEventListener('click', () => {
                navigator.clipboard.writeText(msg.body).then(() => {
                    copyBtn.textContent = 'Copied!';
                    setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1800);
                }).catch(() => {});
            });
            actions.appendChild(copyBtn);
        }

        if (!msg.deleted_at) {
            const hideBtn = document.createElement('button');
            hideBtn.type = 'button';
            hideBtn.className = 'msg-action-btn';
            hideBtn.textContent = 'Hide';
            hideBtn.addEventListener('click', async () => {
                if (!confirm('Hide this message from the conversation view? It remains preserved in the database.')) return;
                const res = await apiFetch(`/api/messages/${encodeURIComponent(msg.id)}/hide`, { method: 'POST' });
                if (res.ok) {
                    bubble.remove();
                    loadThreads({ background: true });
                }
            });
            actions.appendChild(hideBtn);
        } else if (isAdmin) {
            const restoreBtn = document.createElement('button');
            restoreBtn.type = 'button';
            restoreBtn.className = 'msg-action-btn';
            restoreBtn.textContent = 'Restore';
            restoreBtn.addEventListener('click', async () => {
                const res = await apiFetch(`/api/messages/${encodeURIComponent(msg.id)}/restore`, { method: 'POST' });
                if (res.ok) {
                    syncActiveThread({ forceRender: true, forceScroll: false, background: false });
                    loadThreads({ background: true });
                }
            });
            actions.appendChild(restoreBtn);
        }

        bubble.appendChild(actions);
        return bubble;
    }

    function updateChatHeader(threadMeta) {
        if (!chatHeaderEl || !threadMeta) return;
        chatHeaderEl.classList.remove('hidden');
        chatContactNameEl.textContent = threadMeta.contact_name || threadMeta.display_phone || threadMeta.contact_phone;
        chatContactPhoneEl.textContent = threadMeta.contact_name ? (threadMeta.display_phone || threadMeta.contact_phone) : '';
        activeThreadArchived = Boolean(threadMeta.archived_at);
        if (archiveThreadBtn) {
            archiveThreadBtn.textContent = activeThreadArchived ? 'Unarchive' : 'Archive';
        }
    }

    function renderChatArea(messages) {
        if (!chatAreaEl) return;
        chatAreaEl.textContent = '';

        if (hasMoreMessages) {
            const wrap = document.createElement('div');
            wrap.className = 'load-older-wrap';
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-secondary btn-sm';
            btn.textContent = 'Load older messages';
            btn.addEventListener('click', loadOlderMessages);
            wrap.appendChild(btn);
            chatAreaEl.appendChild(wrap);
        }

        if (!messages || messages.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'chat-empty-state';
            empty.textContent = 'No messages in this conversation yet.';
            chatAreaEl.appendChild(empty);
            return;
        }

        messages.forEach((msg) => chatAreaEl.appendChild(buildBubbleNode(msg, false)));
        scrollToBottom();
    }

    async function loadOlderMessages() {
        if (!activePhone || !oldestBeforeTs) return;
        const prevHeight = chatAreaEl.scrollHeight;
        const prevTop = chatAreaEl.scrollTop;

        const params = new URLSearchParams({
            limit: '50',
            before_ts: oldestBeforeTs,
            include_hidden: showHiddenToggle && showHiddenToggle.checked ? 'true' : 'false',
        });
        if (oldestBeforeId) params.set('before_id', oldestBeforeId);

        const res = await apiFetch(`/api/threads/${encodeURIComponent(activePhone)}/messages?` + params.toString());
        if (!res.ok) return;
        const data = await res.json();

        hasMoreMessages = Boolean(data.has_more);
        oldestBeforeTs = data.next_before_ts || null;
        oldestBeforeId = data.next_before_id || null;

        const existingWrap = chatAreaEl.querySelector('.load-older-wrap');
        if (existingWrap) existingWrap.remove();

        const frag = document.createDocumentFragment();
        if (hasMoreMessages) {
            const wrap = document.createElement('div');
            wrap.className = 'load-older-wrap';
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-secondary btn-sm';
            btn.textContent = 'Load older messages';
            btn.addEventListener('click', loadOlderMessages);
            wrap.appendChild(btn);
            frag.appendChild(wrap);
        }
        (data.items || []).forEach((msg) => {
            if (!chatAreaEl.querySelector(`[data-internal-id="${msg.id}"]`)) {
                frag.appendChild(buildBubbleNode(msg, false));
            }
        });
        chatAreaEl.insertBefore(frag, chatAreaEl.firstChild);

        const newHeight = chatAreaEl.scrollHeight;
        chatAreaEl.scrollTop = prevTop + (newHeight - prevHeight);
    }

    async function syncActiveThread(options = { forceRender: false, forceScroll: false, background: false }) {
        const target = activePhone;
        if (!target) return;

        const params = new URLSearchParams({
            limit: '50',
            include_hidden: showHiddenToggle && showHiddenToggle.checked ? 'true' : 'false',
        });
        const headers = options.background ? { 'X-Background-Sync': '1' } : {};
        const res = await apiFetch(`/api/threads/${encodeURIComponent(target)}/messages?` + params.toString(), {
            cache: 'no-store',
            headers,
        });
        if (!res.ok || activePhone !== target) return;
        const data = await res.json();

        updateChatHeader(data.thread);

        if (options.forceRender || !chatAreaEl.querySelector('[data-internal-id]')) {
            hasMoreMessages = Boolean(data.has_more);
            oldestBeforeTs = data.next_before_ts || null;
            oldestBeforeId = data.next_before_id || null;
            renderChatArea(data.items || []);
            return;
        }

        let changed = false;
        (data.items || []).forEach((msg) => {
            const existing = chatAreaEl.querySelector(`[data-internal-id="${msg.id}"]`);
            const nextKey = `${msg.status}|${msg.is_sent}|${msg.is_delivered}|${msg.is_failed}|${Boolean(msg.deleted_at)}`;
            if (!existing) {
                const emptyState = chatAreaEl.querySelector('.chat-empty-state');
                if (emptyState) emptyState.remove();
                chatAreaEl.appendChild(buildBubbleNode(msg, true));
                changed = true;
            } else if (existing.dataset.statusKey !== nextKey) {
                existing.replaceWith(buildBubbleNode(msg, false));
                changed = true;
            }
        });

        if (changed || options.forceScroll) {
            scrollToBottom();
        }
    }

    async function markActiveThreadRead() {
        if (!activePhone) return;
        unreadInActiveThread = false;
        try {
            await apiFetch(`/api/threads/${encodeURIComponent(activePhone)}/mark-read`, { method: 'POST' });
            await loadThreads({ background: true });
        } catch (_err) {
            // Handled
        }
    }

    async function openThread(phone) {
        const canonical = normalizePhone(phone);
        if (!canonical) return;
        userClosedThread = false;
        activePhone = canonical;
        unreadInActiveThread = false;
        showComposerError('');
        renderSidebar(threadsCache);
        await syncActiveThread({ forceRender: true, forceScroll: true, background: false });
        await markActiveThreadRead();
    }

    if (chatAreaEl) {
        const onInteract = () => {
            if (unreadInActiveThread) markActiveThreadRead();
        };
        chatAreaEl.addEventListener('mouseenter', onInteract);
        chatAreaEl.addEventListener('mousemove', onInteract);
    }

    if (archiveThreadBtn) {
        archiveThreadBtn.addEventListener('click', async () => {
            if (!activePhone) return;
            const action = activeThreadArchived ? 'unarchive' : 'archive';
            const res = await apiFetch(`/api/threads/${encodeURIComponent(activePhone)}/${action}`, { method: 'POST' });
            if (res.ok) {
                activeThreadArchived = !activeThreadArchived;
                archiveThreadBtn.textContent = activeThreadArchived ? 'Unarchive' : 'Archive';
                await loadThreads();
            }
        });
    }

    if (showHiddenToggle) {
        showHiddenToggle.addEventListener('change', () => {
            if (activePhone) syncActiveThread({ forceRender: true, forceScroll: false, background: false });
        });
    }

    if (tabInboxBtn && tabArchivedBtn) {
        tabInboxBtn.addEventListener('click', () => {
            threadStatusTab = 'active';
            threadsLimit = 50;
            tabInboxBtn.classList.add('active');
            tabArchivedBtn.classList.remove('active');
            loadThreads();
        });
        tabArchivedBtn.addEventListener('click', () => {
            threadStatusTab = 'archived';
            threadsLimit = 50;
            tabArchivedBtn.classList.add('active');
            tabInboxBtn.classList.remove('active');
            loadThreads();
        });
    }

    if (threadSearchEl) {
        let searchTimer = null;
        threadSearchEl.addEventListener('input', () => {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(() => {
                threadSearchQuery = threadSearchEl.value.trim();
                threadsLimit = 50;
                loadThreads();
            }, 300);
        });
    }

    if (threadsLoadMoreBtn) {
        threadsLoadMoreBtn.addEventListener('click', () => {
            threadsLimit += 50;
            loadThreads();
        });
    }

    // Composer: Enter sends, Shift+Enter newline; NEVER clear draft if send fails!
    if (messageForm && messageInput) {
        messageInput.addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 150) + 'px';
            if (this.value === '') this.style.height = '46px';
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
            showComposerError('');
            if (!activePhone) {
                showComposerError('Please select a conversation first, or click "+ New".');
                return;
            }
            const body = messageInput.value.trim();
            if (!body) return;

            sendBtn.disabled = true;
            sendBtn.textContent = 'Sending...';
            try {
                const res = await apiFetch('/api/messages/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ recipient: activePhone, body }),
                });
                if (res.ok) {
                    const newMsg = await res.json();
                    messageInput.value = '';
                    messageInput.style.height = '46px';
                    const emptyState = chatAreaEl.querySelector('.chat-empty-state');
                    if (emptyState) emptyState.remove();
                    if (!chatAreaEl.querySelector(`[data-internal-id="${newMsg.id}"]`)) {
                        chatAreaEl.appendChild(buildBubbleNode(newMsg, true));
                    }
                    scrollToBottom();
                    window.dispatchEvent(new CustomEvent('app:message_sent'));
                    await loadThreads({ background: true });
                } else {
                    const errData = await res.json().catch(() => ({}));
                    showComposerError(errData.detail || 'Message could not be sent. Your text was kept.');
                }
            } catch (_err) {
                showComposerError('Network error sending message. Your text was kept.');
            } finally {
                sendBtn.disabled = false;
                sendBtn.textContent = 'Send';
            }
        });
    }

    // + New Chat Modal
    if (newChatBtn && newChatModal) {
        newChatBtn.addEventListener('click', async () => {
            newChatModal.classList.remove('hidden');
            newChatPhoneInput.value = '';
            try {
                const res = await apiFetch('/api/contacts/');
                if (res.ok) {
                    const contacts = await res.json();
                    newChatSelect.textContent = '';
                    const defOpt = document.createElement('option');
                    defOpt.value = '';
                    defOpt.textContent = '-- Select a saved contact --';
                    newChatSelect.appendChild(defOpt);
                    contacts.forEach((c) => {
                        const opt = document.createElement('option');
                        opt.value = c.phone_number;
                        opt.textContent = `${c.name} (${c.display_phone || c.phone_number})`;
                        newChatSelect.appendChild(opt);
                    });
                }
            } catch (_e) {}
            newChatPhoneInput.focus();
        });

        newChatSelect.addEventListener('change', () => {
            if (newChatSelect.value) {
                newChatPhoneInput.value = newChatSelect.value;
            }
        });

        newChatForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const phone = normalizePhone(newChatPhoneInput.value);
            if (!phone || phone === 'unknown') return;
            newChatModal.classList.add('hidden');
            await openThread(phone);
            messageInput.focus();
        });
    }

    // Escape closes active thread & emoji picker (preserving v2 shortcut)
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const picker = document.getElementById('emoji-picker-panel');
            if (picker && !picker.classList.contains('hidden')) {
                picker.classList.add('hidden');
                return;
            }
            const openModal = document.querySelector('.modal-backdrop:not(.hidden)');
            if (openModal && openModal.id !== 'timeout-modal') {
                openModal.classList.add('hidden');
                return;
            }
            userClosedThread = true;
            activePhone = null;
            unreadInActiveThread = false;
            if (chatHeaderEl) chatHeaderEl.classList.add('hidden');
            if (chatAreaEl) {
                chatAreaEl.textContent = '';
                const empty = document.createElement('div');
                empty.className = 'chat-empty-state';
                empty.textContent = 'Select a conversation on the left, or click + New to start one.';
                chatAreaEl.appendChild(empty);
            }
            renderSidebar(threadsCache);
        }
    });

    // Real-time SSE handlers
    window.addEventListener('sse:message_created', (e) => {
        const data = e.detail || {};
        const msg = data.message;
        if (!msg) return;

        const isInbound = msg.direction === 'inbound';
        if (activePhone === msg.contact_phone) {
            const emptyState = chatAreaEl.querySelector('.chat-empty-state');
            if (emptyState) emptyState.remove();
            if (!chatAreaEl.querySelector(`[data-internal-id="${msg.id}"]`)) {
                chatAreaEl.appendChild(buildBubbleNode(msg, true));
                scrollToBottom();
            }
            if (isInbound) {
                if (document.visibilityState === 'visible') {
                    markActiveThreadRead();
                } else {
                    unreadInActiveThread = true;
                    if (window.ClinicNotify) window.ClinicNotify.notifyNewInboundMessage();
                }
            }
        } else {
            if (!activePhone && !userClosedThread && msg.contact_phone) {
                openThread(msg.contact_phone);
            }
            if (isInbound && window.ClinicNotify) {
                window.ClinicNotify.notifyNewInboundMessage();
            }
        }
        loadThreads({ background: true });
    });

    window.addEventListener('sse:message_status_updated', (e) => {
        const data = e.detail || {};
        if (activePhone && data.contact_phone === activePhone) {
            syncActiveThread({ forceRender: false, forceScroll: false, background: true });
        }
    });

    window.addEventListener('sse:message_hidden', (e) => {
        const data = e.detail || {};
        if (activePhone && data.contact_phone === activePhone) {
            syncActiveThread({ forceRender: true, forceScroll: false, background: true });
        }
        loadThreads({ background: true });
    });

    window.addEventListener('sse:message_restored', (e) => {
        const data = e.detail || {};
        if (activePhone && data.message && data.message.contact_phone === activePhone) {
            syncActiveThread({ forceRender: true, forceScroll: false, background: true });
        }
        loadThreads({ background: true });
    });

    window.addEventListener('sse:thread_read', (e) => {
        const data = e.detail || {};
        if (data.contact_phone === activePhone) {
            unreadInActiveThread = false;
        }
        loadThreads({ background: true });
    });

    window.addEventListener('sse:thread_updated', () => {
        loadThreads({ background: true });
        if (activePhone) syncActiveThread({ forceRender: false, forceScroll: false, background: true });
    });

    window.addEventListener('sse:contact_updated', () => {
        loadThreads({ background: true });
        if (activePhone) syncActiveThread({ forceRender: false, forceScroll: false, background: true });
    });

    window.addEventListener('sse:reconnected', () => {
        loadThreads({ background: true });
        if (activePhone) syncActiveThread({ forceRender: false, forceScroll: false, background: true });
    });

    function handleReturnToApp() {
        if (unreadInActiveThread) markActiveThreadRead();
        loadThreads({ background: true });
        if (activePhone) syncActiveThread({ forceRender: false, forceScroll: false, background: true });
    }

    window.addEventListener('focus', handleReturnToApp);
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') handleReturnToApp();
    });

    // Gentle 30s background reconciliation (X-Background-Sync: 1 so it NEVER resets idle timer)
    setInterval(() => {
        loadThreads({ background: true });
        if (activePhone) syncActiveThread({ forceRender: false, forceScroll: false, background: true });
    }, 30000);

    async function init() {
        const items = await loadThreads({ background: false });
        const urlParams = new URLSearchParams(window.location.search);
        const phoneParam = urlParams.get('phone');
        if (phoneParam) {
            await openThread(normalizePhone(phoneParam));
        } else if (!activePhone && !userClosedThread && items && items.length > 0) {
            await openThread(items[0].contact_phone);
        }
    }

    init();
});
