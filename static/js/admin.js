/**
 * admin.js
 * User administration, active session control, and HIPAA immutable audit log viewer/exporter.
 */
document.addEventListener('DOMContentLoaded', () => {
    const { apiFetch } = window.ClinicApi;

    const tabUsersBtn = document.getElementById('admin-tab-users');
    const tabSessionsBtn = document.getElementById('admin-tab-sessions');
    const tabAuditBtn = document.getElementById('admin-tab-audit');
    const usersSection = document.getElementById('admin-users-section');
    const sessionsSection = document.getElementById('admin-sessions-section');
    const auditSection = document.getElementById('admin-audit-section');

    const usersBody = document.getElementById('users-table-body');
    const addUserBtn = document.getElementById('add-user-btn');
    const addUserModal = document.getElementById('add-user-modal');
    const addUserForm = document.getElementById('add-user-form');
    const addUserErr = document.getElementById('add-user-error');

    const editUserModal = document.getElementById('edit-user-modal');
    const editUserForm = document.getElementById('edit-user-form');
    const editUserErr = document.getElementById('edit-user-error');
    const editUserLabel = document.getElementById('edit-user-username-label');
    const editDisplayInput = document.getElementById('eu-display');
    const editRoleSelect = document.getElementById('eu-role');
    let editTargetUserId = null;

    const resetPwModal = document.getElementById('reset-pw-modal');
    const resetPwForm = document.getElementById('reset-pw-form');
    const resetPwErr = document.getElementById('reset-pw-error');
    const resetPwLabel = document.getElementById('reset-pw-target-label');
    let resetTargetUserId = null;

    const sessionsBody = document.getElementById('sessions-table-body');
    const sessionsRefreshBtn = document.getElementById('sessions-refresh-btn');

    const auditBody = document.getElementById('audit-table-body');
    const auditFilterUser = document.getElementById('audit-filter-user');
    const auditFilterAction = document.getElementById('audit-filter-action');
    const auditFilterOutcome = document.getElementById('audit-filter-outcome');
    const auditApplyBtn = document.getElementById('audit-apply-btn');
    const auditVerifyBtn = document.getElementById('audit-verify-btn');
    const auditVerifyBanner = document.getElementById('audit-verify-banner');
    const auditPrevBtn = document.getElementById('audit-prev-btn');
    const auditNextBtn = document.getElementById('audit-next-btn');
    const auditPageInfo = document.getElementById('audit-page-info');
    let auditOffset = 0;
    const auditLimit = 50;

    function switchTab(tab) {
        const isUsers = tab === 'users';
        const isSessions = tab === 'sessions';
        const isAudit = tab === 'audit';

        usersSection.classList.toggle('hidden', !isUsers);
        sessionsSection.classList.toggle('hidden', !isSessions);
        auditSection.classList.toggle('hidden', !isAudit);

        tabUsersBtn.className = isUsers ? 'btn btn-primary' : 'btn btn-secondary';
        tabSessionsBtn.className = isSessions ? 'btn btn-primary' : 'btn btn-secondary';
        tabAuditBtn.className = isAudit ? 'btn btn-primary' : 'btn btn-secondary';

        if (isUsers) loadUsers();
        else if (isSessions) loadSessions();
        else loadAuditLogs();
    }

    tabUsersBtn.addEventListener('click', () => switchTab('users'));
    tabSessionsBtn.addEventListener('click', () => switchTab('sessions'));
    tabAuditBtn.addEventListener('click', () => switchTab('audit'));

    async function loadUsers() {
        const res = await apiFetch('/api/admin/users', { cache: 'no-store' });
        if (!res.ok) return;
        const users = await res.json();
        usersBody.textContent = '';

        users.forEach((u) => {
            const tr = document.createElement('tr');

            const uTd = document.createElement('td');
            uTd.style.fontWeight = '700';
            uTd.textContent = u.username;

            const dTd = document.createElement('td');
            dTd.textContent = u.display_name;

            const rTd = document.createElement('td');
            rTd.textContent = u.role === 'admin' ? 'Admin (Doctor)' : 'Staff';

            const sTd = document.createElement('td');
            const badge = document.createElement('span');
            if (!u.is_active) {
                badge.className = 'badge badge-neutral';
                badge.textContent = 'Disabled';
            } else if (u.locked_until && Date.parse(u.locked_until) > Date.now()) {
                badge.className = 'badge badge-danger';
                badge.textContent = 'Locked';
            } else {
                badge.className = 'badge badge-ok';
                badge.textContent = 'Active';
            }
            sTd.appendChild(badge);

            const lTd = document.createElement('td');
            lTd.textContent = u.last_login_at ? new Date(u.last_login_at).toLocaleString() : 'Never';

            const aTd = document.createElement('td');
            const wrap = document.createElement('div');
            wrap.className = 'table-actions';

            const editBtn = document.createElement('button');
            editBtn.type = 'button';
            editBtn.className = 'btn btn-secondary btn-sm';
            editBtn.textContent = 'Edit';
            editBtn.addEventListener('click', () => {
                editTargetUserId = u.id;
                editUserLabel.textContent = `Username: ${u.username}`;
                editDisplayInput.value = u.display_name;
                editRoleSelect.value = u.role;
                editUserErr.classList.add('hidden');
                editUserModal.classList.remove('hidden');
                editDisplayInput.focus();
            });
            wrap.appendChild(editBtn);

            const resetBtn = document.createElement('button');
            resetBtn.type = 'button';
            resetBtn.className = 'btn btn-secondary btn-sm';
            resetBtn.textContent = 'Reset Password';
            resetBtn.addEventListener('click', () => {
                resetTargetUserId = u.id;
                resetPwLabel.textContent = `User: ${u.display_name} (${u.username})`;
                resetPwErr.classList.add('hidden');
                resetPwForm.reset();
                resetPwModal.classList.remove('hidden');
            });
            wrap.appendChild(resetBtn);

            const signOutBtn = document.createElement('button');
            signOutBtn.type = 'button';
            signOutBtn.className = 'btn btn-secondary btn-sm';
            signOutBtn.textContent = 'Sign Out';
            signOutBtn.addEventListener('click', async () => {
                if (!confirm(`Sign out all active browser sessions for "${u.display_name}"?`)) return;
                const r = await apiFetch(`/api/admin/users/${u.id}/sign-out`, { method: 'POST' });
                if (r.ok) {
                    const data = await r.json();
                    alert(`Signed out ${data.revoked_sessions} active session(s) for ${u.display_name}.`);
                }
            });
            wrap.appendChild(signOutBtn);

            if (u.locked_until && Date.parse(u.locked_until) > Date.now()) {
                const unlockBtn = document.createElement('button');
                unlockBtn.type = 'button';
                unlockBtn.className = 'btn btn-secondary btn-sm';
                unlockBtn.textContent = 'Unlock';
                unlockBtn.addEventListener('click', async () => {
                    const r = await apiFetch(`/api/admin/users/${u.id}/unlock`, { method: 'POST' });
                    if (r.ok) loadUsers();
                });
                wrap.appendChild(unlockBtn);
            }

            const toggleBtn = document.createElement('button');
            toggleBtn.type = 'button';
            toggleBtn.className = u.is_active ? 'btn btn-danger btn-sm' : 'btn btn-primary btn-sm';
            toggleBtn.textContent = u.is_active ? 'Disable' : 'Enable';
            toggleBtn.addEventListener('click', async () => {
                const r = await apiFetch(`/api/admin/users/${u.id}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ is_active: !u.is_active }),
                });
                if (r.ok) {
                    loadUsers();
                } else {
                    const err = await r.json().catch(() => ({}));
                    alert(err.detail || 'Could not update user.');
                }
            });
            wrap.appendChild(toggleBtn);

            aTd.appendChild(wrap);
            tr.appendChild(uTd);
            tr.appendChild(dTd);
            tr.appendChild(rTd);
            tr.appendChild(sTd);
            tr.appendChild(lTd);
            tr.appendChild(aTd);
            usersBody.appendChild(tr);
        });
    }

    async function loadSessions() {
        const res = await apiFetch('/api/admin/sessions', { cache: 'no-store' });
        if (!res.ok) return;
        const sessions = await res.json();
        sessionsBody.textContent = '';

        if (!sessions || sessions.length === 0) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 6;
            td.style.textAlign = 'center';
            td.style.padding = '24px';
            td.textContent = 'No active sessions.';
            tr.appendChild(td);
            sessionsBody.appendChild(tr);
            return;
        }

        sessions.forEach((s) => {
            const tr = document.createElement('tr');

            const userTd = document.createElement('td');
            userTd.style.fontWeight = '700';
            userTd.textContent = `${s.display_name} (${s.username})`;
            if (s.is_current) {
                const curBadge = document.createElement('span');
                curBadge.className = 'badge badge-ok';
                curBadge.style.marginLeft = '8px';
                curBadge.textContent = 'This browser';
                userTd.appendChild(curBadge);
            }

            const roleTd = document.createElement('td');
            roleTd.textContent = s.role === 'admin' ? 'Admin' : 'Staff';

            const ipTd = document.createElement('td');
            ipTd.className = 'mono';
            ipTd.textContent = s.ip_address || '-';

            const inTd = document.createElement('td');
            inTd.textContent = new Date(s.created_at).toLocaleString();

            const expTd = document.createElement('td');
            expTd.textContent = new Date(s.expires_at).toLocaleString();

            const actTd = document.createElement('td');
            const wrap = document.createElement('div');
            wrap.className = 'table-actions';

            const revokeBtn = document.createElement('button');
            revokeBtn.type = 'button';
            revokeBtn.className = 'btn btn-danger btn-sm';
            revokeBtn.textContent = 'Sign Out';
            revokeBtn.addEventListener('click', async () => {
                if (!confirm(`Sign out session for "${s.display_name}" (${s.ip_address || 'unknown IP'})?`)) return;
                const r = await apiFetch(`/api/admin/sessions/${encodeURIComponent(s.id)}/revoke`, { method: 'POST' });
                if (r.ok) loadSessions();
            });
            wrap.appendChild(revokeBtn);
            actTd.appendChild(wrap);

            tr.appendChild(userTd);
            tr.appendChild(roleTd);
            tr.appendChild(ipTd);
            tr.appendChild(inTd);
            tr.appendChild(expTd);
            tr.appendChild(actTd);
            sessionsBody.appendChild(tr);
        });
    }

    if (sessionsRefreshBtn) {
        sessionsRefreshBtn.addEventListener('click', loadSessions);
    }

    addUserBtn.addEventListener('click', () => {
        addUserErr.classList.add('hidden');
        addUserForm.reset();
        addUserModal.classList.remove('hidden');
    });

    addUserForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        addUserErr.classList.add('hidden');
        const res = await apiFetch('/api/admin/users', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username: document.getElementById('au-username').value.trim(),
                display_name: document.getElementById('au-display').value.trim(),
                role: document.getElementById('au-role').value,
                password: document.getElementById('au-password').value,
            }),
        });
        if (res.ok) {
            addUserModal.classList.add('hidden');
            loadUsers();
        } else {
            const err = await res.json().catch(() => ({}));
            addUserErr.textContent = err.detail || 'Could not create user.';
            addUserErr.classList.remove('hidden');
        }
    });

    editUserForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        editUserErr.classList.add('hidden');
        const res = await apiFetch(`/api/admin/users/${editTargetUserId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                display_name: editDisplayInput.value.trim(),
                role: editRoleSelect.value,
            }),
        });
        if (res.ok) {
            editUserModal.classList.add('hidden');
            loadUsers();
        } else {
            const err = await res.json().catch(() => ({}));
            editUserErr.textContent = err.detail || 'Could not update user.';
            editUserErr.classList.remove('hidden');
        }
    });

    resetPwForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        resetPwErr.classList.add('hidden');
        const res = await apiFetch(`/api/admin/users/${resetTargetUserId}/reset-password`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                new_password: document.getElementById('rp-password').value,
                must_change_password: false,
            }),
        });
        if (res.ok) {
            resetPwModal.classList.add('hidden');
            loadUsers();
        } else {
            const err = await res.json().catch(() => ({}));
            resetPwErr.textContent = err.detail || 'Could not reset password.';
            resetPwErr.classList.remove('hidden');
        }
    });

    async function loadAuditLogs() {
        const params = new URLSearchParams({
            limit: String(auditLimit),
            offset: String(auditOffset),
        });
        if (auditFilterUser.value.trim()) params.set('actor_username', auditFilterUser.value.trim());
        if (auditFilterAction.value.trim()) params.set('action', auditFilterAction.value.trim());
        if (auditFilterOutcome.value) params.set('outcome', auditFilterOutcome.value);

        const res = await apiFetch('/api/admin/audit-logs?' + params.toString(), { cache: 'no-store' });
        if (!res.ok) return;
        const data = await res.json();
        auditBody.textContent = '';

        (data.items || []).forEach((r) => {
            const tr = document.createElement('tr');

            const idTd = document.createElement('td');
            idTd.className = 'mono';
            idTd.textContent = String(r.id);

            const tsTd = document.createElement('td');
            tsTd.className = 'mono';
            tsTd.textContent = r.created_at;

            const userTd = document.createElement('td');
            userTd.textContent = r.actor_username || '-';

            const actTd = document.createElement('td');
            actTd.className = 'mono';
            actTd.textContent = r.action;

            const targetTd = document.createElement('td');
            targetTd.className = 'mono';
            targetTd.textContent = r.resource_type + (r.resource_id ? ':' + r.resource_id : '');

            const outTd = document.createElement('td');
            const badge = document.createElement('span');
            badge.className = r.outcome === 'success' ? 'badge badge-ok' : 'badge badge-danger';
            badge.textContent = r.outcome;
            outTd.appendChild(badge);

            const ipTd = document.createElement('td');
            ipTd.className = 'mono';
            ipTd.textContent = r.ip_address || '-';

            tr.appendChild(idTd);
            tr.appendChild(tsTd);
            tr.appendChild(userTd);
            tr.appendChild(actTd);
            tr.appendChild(targetTd);
            tr.appendChild(outTd);
            tr.appendChild(ipTd);
            auditBody.appendChild(tr);
        });

        const total = data.total || 0;
        const start = total === 0 ? 0 : auditOffset + 1;
        const end = Math.min(auditOffset + auditLimit, total);
        auditPageInfo.textContent = `Showing ${start}–${end} of ${total} audit records`;
        auditPrevBtn.disabled = auditOffset <= 0;
        auditNextBtn.disabled = auditOffset + auditLimit >= total;
    }

    auditApplyBtn.addEventListener('click', () => {
        auditOffset = 0;
        loadAuditLogs();
    });
    auditPrevBtn.addEventListener('click', () => {
        auditOffset = Math.max(0, auditOffset - auditLimit);
        loadAuditLogs();
    });
    auditNextBtn.addEventListener('click', () => {
        auditOffset += auditLimit;
        loadAuditLogs();
    });

    auditVerifyBtn.addEventListener('click', async () => {
        const res = await apiFetch('/api/admin/audit-logs/verify-chain');
        if (!res.ok) return;
        const data = await res.json();
        auditVerifyBanner.classList.remove('hidden');
        if (data.valid) {
            auditVerifyBanner.textContent = `Integrity Verified: all ${data.total_rows} audit log records are intact and untampered.`;
        } else {
            auditVerifyBanner.textContent = `Integrity Alert: ${data.error} (row ${data.first_broken_id}).`;
        }
    });

    loadUsers();
});
