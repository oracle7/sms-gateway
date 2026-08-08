/**
 * contacts.js
 * Manages the address book: reading, adding, editing, and deleting contacts.
 */
document.addEventListener('DOMContentLoaded', () => {
    const contactsTable = document.getElementById('contacts-table-body');
    const contactModal = document.getElementById('contact-modal');
    const contactForm = document.getElementById('contact-form');

    // Form Inputs
    const phoneInput = document.getElementById('contact-phone');
    const nameInput = document.getElementById('contact-name');
    const notesInput = document.getElementById('contact-notes');
    const modalTitle = document.getElementById('modal-title');

    let isEditMode = false;

    // 1. Fetch and render contacts
    async function fetchContacts() {
        try {
            const res = await fetch('/api/contacts/');
            const contacts = await res.json();
            renderTable(contacts);
        } catch (err) {
            console.error('Failed to fetch contacts', err);
        }
    }

    function renderTable(contacts) {
        if (!contactsTable) return;
        contactsTable.innerHTML = '';

        contacts.forEach(c => {
            const tr = document.createElement('tr');
            tr.className = "border-b hover:bg-gray-50";
            tr.innerHTML = `
                <td class="p-3 font-medium">${c.name}</td>
                <td class="p-3">${c.phone_number}</td>
                <td class="p-3 text-gray-500">${c.notes || ''}</td>
                <td class="p-3">
                    <a href="/?phone=${encodeURIComponent(c.phone_number)}" class="text-blue-500 hover:underline mr-3">Chat</a>
                    <button class="text-yellow-500 hover:underline mr-3" onclick="openEditModal('${c.phone_number}', '${c.name}', '${c.notes || ''}')">Edit</button>
                    <button class="text-red-500 hover:underline" onclick="deleteContact('${c.phone_number}')">Delete</button>
                </td>
            `;
            contactsTable.appendChild(tr);
        });
    }

    // 2. Modal interactions
    window.openAddModal = () => {
        isEditMode = false;
        modalTitle.textContent = "Add Contact";
        contactForm.reset();
        phoneInput.disabled = false; // Allow editing phone number on creation
        contactModal.classList.remove('hidden');
    };

    window.openEditModal = (phone, name, notes) => {
        isEditMode = true;
        modalTitle.textContent = "Edit Contact";
        phoneInput.value = phone;
        phoneInput.disabled = true; // Primary key, cannot change
        nameInput.value = name;
        notesInput.value = notes;
        contactModal.classList.remove('hidden');
    };

    window.closeModal = () => {
        contactModal.classList.add('hidden');
    };

    // 3. Form Submission (Create or Update)
    if (contactForm) {
        contactForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const payload = {
                name: nameInput.value,
                notes: notesInput.value
            };

            try {
                let res;
                if (isEditMode) {
                    res = await fetch(`/api/contacts/${encodeURIComponent(phoneInput.value)}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                } else {
                    payload.phone_number = phoneInput.value;
                    res = await fetch('/api/contacts/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                }

                if (res.ok) {
                    closeModal();
                    fetchContacts();
                } else {
                    const errData = await res.json();
                    alert(`Error: ${errData.detail || 'Could not save contact.'}`);
                }
            } catch (err) {
                console.error('Failed to save contact', err);
            }
        });
    }

    // 4. Delete Contact
    window.deleteContact = async (phone) => {
        if (!confirm(`Are you sure you want to delete the contact ${phone}? Your message history will remain intact.`)) {
            return;
        }

        try {
            const res = await fetch(`/api/contacts/${encodeURIComponent(phone)}`, {
                method: 'DELETE'
            });

            if (res.ok) {
                fetchContacts();
            } else {
                alert("Failed to delete contact.");
            }
        } catch (err) {
            console.error('Failed to delete contact', err);
        }
    };

    // Initialize
    fetchContacts();
});