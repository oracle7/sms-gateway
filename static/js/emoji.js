/**
 * emoji.js
 * Lightweight 100% local emoji picker (zero external CDN requests).
 */
(function () {
    const CATEGORIES = [
        {
            id: 'smileys',
            label: '😊',
            title: 'Smileys',
            items: [
                ['😊', 'smile happy'], ['😀', 'grin happy'], ['😄', 'laugh'], ['😁', 'beam'],
                ['🙂', 'slight smile'], ['😉', 'wink'], ['😌', 'relieved'], ['🥰', 'love'],
                ['🙏', 'thanks please pray'], ['👍', 'thumbs up ok yes'], ['👏', 'clap'],
                ['👋', 'wave hello bye'], ['🤝', 'handshake'], ['👌', 'ok'],
            ],
        },
        {
            id: 'clinic',
            label: '🩺',
            title: 'Clinic & Care',
            items: [
                ['🩺', 'doctor stethoscope'], ['🦶', 'foot podiatry'], ['🩹', 'bandage'],
                ['💊', 'pill medicine'], ['🏥', 'hospital clinic'], ['📋', 'clipboard form'],
                ['📅', 'calendar appointment'], ['⏰', 'clock time reminder'], ['📞', 'phone call'],
                ['✅', 'check confirm done'], ['❗', 'important alert'], ['❓', 'question'],
                ['🚶', 'walk'], ['👟', 'shoe'],
            ],
        },
        {
            id: 'hearts',
            label: '❤️',
            title: 'Hearts & Symbols',
            items: [
                ['❤️', 'heart love'], ['💙', 'blue heart'], ['💚', 'green heart'],
                ['🌟', 'star'], ['✨', 'sparkles'], ['🎉', 'celebrate'],
                ['☀️', 'sun morning'], ['🌤️', 'day'], ['☔', 'rain'], ['❄️', 'snow'],
                ['📍', 'location address'], ['🚗', 'car parking'], ['🏠', 'home'], ['💼', 'office'],
            ],
        },
    ];

    function initLocalEmojiPicker() {
        const panel = document.getElementById('emoji-picker-panel');
        const toggleBtn = document.getElementById('emoji-toggle-btn');
        const messageInput = document.getElementById('message-input');
        if (!panel || !toggleBtn || !messageInput) return;

        let activeCat = CATEGORIES[0].id;
        let searchQuery = '';

        const searchInput = document.createElement('input');
        searchInput.type = 'search';
        searchInput.className = 'emoji-search';
        searchInput.placeholder = 'Search emoji...';

        const catsRow = document.createElement('div');
        catsRow.className = 'emoji-cats';

        const grid = document.createElement('div');
        grid.className = 'emoji-grid';

        panel.appendChild(searchInput);
        panel.appendChild(catsRow);
        panel.appendChild(grid);

        function renderCategories() {
            catsRow.textContent = '';
            CATEGORIES.forEach((cat) => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'emoji-cat-btn' + (cat.id === activeCat ? ' active' : '');
                btn.textContent = cat.label;
                btn.title = cat.title;
                btn.addEventListener('click', () => {
                    activeCat = cat.id;
                    searchQuery = '';
                    searchInput.value = '';
                    renderCategories();
                    renderGrid();
                });
                catsRow.appendChild(btn);
            });
        }

        function renderGrid() {
            grid.textContent = '';
            let pool = [];
            if (searchQuery) {
                const q = searchQuery.toLowerCase();
                CATEGORIES.forEach((c) => {
                    c.items.forEach((entry) => {
                        if (entry[1].includes(q) || entry[0].includes(q)) pool.push(entry);
                    });
                });
            } else {
                const found = CATEGORIES.find((c) => c.id === activeCat) || CATEGORIES[0];
                pool = found.items;
            }

            pool.forEach(([char, desc]) => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'emoji-btn';
                btn.textContent = char;
                btn.title = desc;
                btn.addEventListener('click', () => {
                    const start = messageInput.selectionStart || 0;
                    const end = messageInput.selectionEnd || 0;
                    const val = messageInput.value;
                    messageInput.value = val.slice(0, start) + char + val.slice(end);
                    messageInput.focus();
                    messageInput.selectionStart = messageInput.selectionEnd = start + char.length;
                    messageInput.dispatchEvent(new Event('input'));
                });
                grid.appendChild(btn);
            });
        }

        searchInput.addEventListener('input', () => {
            searchQuery = searchInput.value.trim();
            renderGrid();
        });

        toggleBtn.addEventListener('click', (e) => {
            e.preventDefault();
            panel.classList.toggle('hidden');
            if (!panel.classList.contains('hidden')) {
                searchInput.focus();
            }
        });

        document.addEventListener('click', (e) => {
            if (!panel.contains(e.target) && !toggleBtn.contains(e.target)) {
                panel.classList.add('hidden');
            }
        });

        renderCategories();
        renderGrid();
    }

    document.addEventListener('DOMContentLoaded', initLocalEmojiPicker);
})();
