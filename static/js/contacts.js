/**
 * contacts.js
 * Address book CRUD + soft-delete & restore with safe DOM rendering.
 */
document.addEventListener('DOMContentLoaded', () => {
    const { apiFetch } = window.ClinicApi;

    const tableBody = document.getElementById('contacts-table-body');
    const searchInput = document.getElementById('contacts-search');
    const showDeletedToggle = document.getElementById('contacts-show-deleted');
    const addBtn = document.getElementById('add-contact-btn');

    const modal = document.getElementById('contact-modal');
    const modalTitle = document.getElementById('contact-modal-title');
    const form = document.getElementById('contact-form');
    const formErr = document.getElementById('contact-form-error');
    const phoneInput = document.getElementById('contact-phone');
    const nameInput = document.getElementById('contact-name');
    const notesInput = document.getElementById('contact-notes');

    let isEditMode = false;
    let editContactId = null;

    function showErr(msg) {
        if (!formErr) return;
        if (!msg) {
            formErr.classList.add('hidden');
            formErr.textContent = '';
            return;
        }
        formErr.textContent = msg;
        formErr.classList.remove('hidden');
    }

    async function fetchContacts() {
        const params = new URLSearchParams();
        if (searchInput && searchInput.value.trim()) params.set('search', searchInput.value.trim());
        if (showDeletedToggle && showDeletedToggle.checked) params.set('include_deleted', 'true');

        const res = await apiFetch('/api/contacts/?' + params.toString(), { cache: 'no-store' });
        if (!res.ok) return;
        const contacts = await res.json();
        renderTable(contacts);
    }

    function renderTable(contacts) {
        if (!tableBody) return;
        tableBody.textContent = '';

        if (!contacts || contacts.length === 0) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 4;
            td.style.textAlign = 'center';
            td.style.padding = '28px';
            td.textContent = 'No contacts found.';
            tr.appendChild(td);
            tableBody.appendChild(tr);
            return;
        }

        contacts.forEach((c) => {
            const tr = document.createElement('tr');

            const nameTd = document.createElement('td');
            nameTd.style.fontWeight = '700';
            nameTd.textContent = c.name + (c.deleted_at ? ' (Removed)' : '');

            const phoneTd = document.createElement('td');
            phoneTd.textContent = c.display_phone || c.phone_number;

            const notesTd = document.createElement('td');
            notesTd.style.color = 'var(--text-secondary)';
            notesTd.textContent = c.notes || '';

            const actionsTd = document.createElement('td');
            const actionsWrap = document.createElement('div');
            actionsWrap.className = 'table-actions';

            if (!c.deleted_at) {
                const chatLink = document.createElement('a');
                chatLink.href = '/?phone=' + encodeURIComponent(c.phone_number);
                chatLink.className = 'btn btn-primary btn-sm';
                chatLink.textContent = 'Chat';
                actionsWrap.appendChild(chatLink);

                const editBtn = document.createElement('button');
                editBtn.type = 'button';
                editBtn.className = 'btn btn-secondary btn-sm';
                editBtn.textContent = 'Edit';
                editBtn.addEventListener('click', () => {
                    isEditMode = true;
                    editContactId = c.id;
                    modalTitle.textContent = 'Edit Contact';
                    showErr('');
                    phoneInput.value = c.phone_number;
                    phoneInput.disabled = true;
                    nameInput.value = c.name;
                    notesInput.value = c.notes || '';
                    modal.classList.remove('hidden');
                    nameInput.focus();
                });
                actionsWrap.appendChild(editBtn);

                const delBtn = document.createElement('button');
                delBtn.type = 'button';
                delBtn.className = 'btn btn-danger btn-sm';
                delBtn.textContent = 'Remove';
                delBtn.addEventListener('click', async () => {
                    if (!confirm(`Remove contact "${c.name}" from the address book? Message history stays preserved.`)) return;
                    const res = await apiFetch(`/api/contacts/${encodeURIComponent(String(c.id))}`, { method: 'DELETE' });
                    if (res.ok) fetchContacts();
                });
                actionsWrap.appendChild(delBtn);
            } else {
                const restoreBtn = document.createElement('button');
                restoreBtn.type = 'button';
                restoreBtn.className = 'btn btn-secondary btn-sm';
                restoreBtn.textContent = 'Restore';
                restoreBtn.addEventListener('click', async () => {
                    const res = await apiFetch(`/api/contacts/${encodeURIComponent(String(c.id))}/restore`, { method: 'POST' });
                    if (res.ok) fetchContacts();
                });
                actionsWrap.appendChild(restoreBtn);
            }

            actionsTd.appendChild(actionsWrap);
            tr.appendChild(nameTd);
            tr.appendChild(phoneTd);
            tr.appendChild(notesTd);
            tr.appendChild(actionsTd);
            tableBody.appendChild(tr);
        });
    }

    if (addBtn) {
        addBtn.addEventListener('click', () => {
            isEditMode = false;
            editContactId = null;
            modalTitle.textContent = 'Add Contact';
            showErr('');
            form.reset();
            phoneInput.disabled = false;
            modal.classList.remove('hidden');
            phoneInput.focus();
        });
    }

    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            showErr('');
            const payload = {
                name: nameInput.value.trim(),
                notes: notesInput.value.trim() || null,
            };

            let res;
            if (isEditMode) {
                res = await apiFetch(`/api/contacts/${encodeURIComponent(String(editContactId))}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
            } else {
                payload.phone_number = phoneInput.value.trim();
                res = await apiFetch('/api/contacts/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
            }

            if (res.ok) {
                modal.classList.add('hidden');
                fetchContacts();
            } else {
                const errData = await res.json().catch(() => ({}));
                showErr(errData.detail || 'Could not save contact.');
            }
        });
    }

    if (searchInput) {
        let timer = null;
        searchInput.addEventListener('input', () => {
            clearTimeout(timer);
            timer = setTimeout(fetchContacts, 250);
        });
    }
    if (showDeletedToggle) {
        showDeletedToggle.addEventListener('change', fetchContacts);
    }

    fetchContacts();
});
