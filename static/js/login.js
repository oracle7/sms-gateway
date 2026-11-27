document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('login-form');
    const errBox = document.getElementById('login-error');
    const submitBtn = document.getElementById('login-submit');
    const userInput = document.getElementById('login-username');
    const passInput = document.getElementById('login-password');

    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        errBox.classList.add('hidden');
        errBox.textContent = '';
        submitBtn.disabled = true;
        submitBtn.textContent = 'Signing in...';

        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username: userInput.value.trim(),
                    password: passInput.value,
                }),
            });
            if (res.ok) {
                window.location.replace('/');
                return;
            }
            const data = await res.json().catch(() => ({}));
            errBox.textContent = data.detail || 'Sign in failed. Please check your username and password.';
            errBox.classList.remove('hidden');
            passInput.value = '';
            passInput.focus();
        } catch (_err) {
            errBox.textContent = 'Network error. Please check your connection and try again.';
            errBox.classList.remove('hidden');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Sign In';
        }
    });
});
