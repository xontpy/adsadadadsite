document.addEventListener('DOMContentLoaded', () => {
    // --- Element References ---
    const loginButton = document.getElementById('login-button');
    const logoutButton = document.getElementById('logout-button');
    const userProfile = document.getElementById('user-profile');
    const userAvatar = document.getElementById('user-avatar');
    const usernameSpan = document.getElementById('username');
    const permissionsSpan = document.getElementById('permissions');
    const premiumPlanBanner = document.querySelector('.premium-plan');

    const mainContent = document.querySelector('.main-content');
    const viewbotPage = document.querySelector('.viewbot-controls');
    const viewbotStatusPage = document.querySelector('.viewbot-status');
    const settingsPage = document.getElementById('settings-page');
    
    const startBotButton = document.getElementById('start-bot-button');
    const stopBotButton = document.getElementById('stop-bot-button');
    const channelInput = document.getElementById('channel-input');
    const viewersSlider = document.getElementById('viewers-slider');
    const viewersCount = document.getElementById('viewers-count');
    const durationSlider = document.getElementById('duration-slider');
    const durationCount = document.getElementById('duration-count');
    const rampUpTimeInput = document.getElementById('ramp-up-time');

    // Status screen elements
    const activeViewersSpan = document.getElementById('active-viewers');
    const timeRemainingSpan = document.getElementById('time-remaining');
    const progressBar = document.getElementById('progress-bar');
    const progressPercentSpan = document.getElementById('progress-percent');

    // Settings elements
    const themeSelect = document.getElementById('theme-select');
    const notificationsToggle = document.getElementById('notifications-toggle');
    
    // Menu items
    const menuItems = document.querySelectorAll('.menu-item');

    // --- Configuration ---
    const API_BASE_URL = 'https://kickaviewss.onrender.com'; // Replace with your actual API endpoint

    // --- State ---
    let isBotRunning = false;
    let statusInterval;
    let durationInterval;
    let timeRemaining = 0;

    // --- Event Listeners ---
    if (viewersSlider && viewersCount) {
        viewersSlider.addEventListener('input', () => {
            viewersCount.textContent = viewersSlider.value;
        });
    }

    if (durationSlider && durationCount) {
        durationSlider.addEventListener('input', () => {
            durationCount.textContent = durationSlider.value;
        });
    }

    if (loginButton) {
        loginButton.addEventListener('click', () => {
            window.location.href = `${API_BASE_URL}/login`;
        });
    }

    if (logoutButton) {
        logoutButton.addEventListener('click', () => {
            localStorage.removeItem('accessToken');
            showLoginState();
        });
    }

    if (startBotButton) {
        startBotButton.addEventListener('click', startBot);
    }
    
    if (stopBotButton) {
        stopBotButton.addEventListener('click', stopBot);
    }

    menuItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const page = item.getAttribute('data-page');
            showPage(page);
        });
    });

    if (themeSelect) {
        themeSelect.addEventListener('change', (e) => {
            document.body.className = `${e.target.value}-theme`;
        });
    }

    // --- Functions ---
    function showPage(page) {
        const pages = [viewbotPage, viewbotStatusPage, settingsPage];
        let pageToShow = null;

        if (page === 'viewbot') {
            pageToShow = isBotRunning ? viewbotStatusPage : viewbotPage;
        } else if (page === 'settings') {
            pageToShow = settingsPage;
        }
        // Add other pages here (e.g., support)

        pages.forEach(p => {
            if (p !== pageToShow) {
                p.style.display = 'none';
                p.classList.remove('page');
            }
        });

        if (pageToShow) {
            pageToShow.style.display = 'block';
            pageToShow.classList.add('page');
        }

        // Update active menu item
        menuItems.forEach(item => {
            item.classList.toggle('active', item.getAttribute('data-page') === page);
        });
    }


    async function checkUserSession() {
        const hash = window.location.hash;
        if (hash.startsWith('#token=')) {
            const token = hash.substring('#token='.length);
            localStorage.setItem('accessToken', token);
            window.history.replaceState(null, '', window.location.pathname + window.location.search);
            await fetchUserData(token);
        } else {
            const storedToken = localStorage.getItem('accessToken');
            if (storedToken) {
                await fetchUserData(storedToken);
            } else {
                showLoginState();
            }
        }
        pollStatus();
    }

    async function fetchUserData(token) {
        try {
            const response = await fetch(`${API_BASE_URL}/api/me`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (response.ok) {
                const user = await response.json();
                showLoggedInState(user);
            } else {
                localStorage.removeItem('accessToken');
                showLoginState();
            }
        } catch (error) {
            console.error('Error fetching user data:', error);
            showLoginState();
        }
    }

    function showLoginState() {
        if (loginButton) loginButton.style.display = 'block';
        if (userProfile) userProfile.style.display = 'none';
        if (premiumPlanBanner) premiumPlanBanner.style.display = 'none';
    }

    function showLoggedInState(user) {
        if (loginButton) loginButton.style.display = 'none';
        if (userProfile) userProfile.style.display = 'flex';
        
        if (usernameSpan) usernameSpan.textContent = user.username;
        if (permissionsSpan) {
            permissionsSpan.textContent = user.is_premium ? 'Pro' : 'Standard';
        }
        if (user.is_premium && premiumPlanBanner) {
            premiumPlanBanner.style.display = 'flex';
        }
        if (userAvatar) userAvatar.src = `https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png`;

        if (viewersSlider) {
            viewersSlider.max = user.max_views || 500;
            if (parseInt(viewersSlider.value) > viewersSlider.max) {
                viewersSlider.value = viewersSlider.max;
            }
            if(viewersCount) viewersCount.textContent = viewersSlider.value;
        }
    }

    async function startBot() {
        const channel = channelInput.value;
        const viewers = viewersSlider.value;
        const duration = durationSlider.value;
        const rampUpTime = rampUpTimeInput.value;

        if (!channel) {
            alert('Please enter a Kick channel name.');
            return;
        }

        const token = localStorage.getItem('accessToken');
        if (!token) {
            alert('You are not logged in. Please log in to start the bot.');
            return;
        }

        startBotButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Starting...';
        startBotButton.disabled = true;

        const payload = {
            channel: channel,
            views: parseInt(viewers),
            duration: parseInt(duration),
            ramp_up_minutes: rampUpTime ? parseInt(rampUpTime) : 0
        };

        try {
            const response = await fetch(`${API_BASE_URL}/api/start`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify(payload),
            });

            const data = await response.json();

            if (response.ok) {
                isBotRunning = true;
                timeRemaining = parseInt(duration) * 60;
                updateStatusDisplay({ target_viewers: viewers });
                startDurationTimer();
                showPage('viewbot');
                pollStatus();
            } else {
                throw new Error(data.detail || 'Failed to start bot.');
            }
        } catch (error) {
            alert(`Error starting bot: ${error.message}`);
            isBotRunning = false;
            showPage('viewbot');
        } finally {
            startBotButton.innerHTML = '<i class="fas fa-play"></i> Start Viewbot';
            startBotButton.disabled = false;
        }
    }

    async function stopBot() {
        stopBotButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Stopping...';
        stopBotButton.disabled = true;

        const token = localStorage.getItem('accessToken');
        try {
            const response = await fetch(`${API_BASE_URL}/api/stop`, {
                method: 'POST',
                 headers: { 'Authorization': `Bearer ${token}` }
            });
            const data = await response.json();
            if (response.ok) {
                isBotRunning = false;
                stopDurationTimer();
                showPage('viewbot');
                if (statusInterval) clearInterval(statusInterval);
            } else {
                throw new Error(data.detail || 'Failed to stop bot.');
            }
        } catch (error) {
            alert(`Error stopping bot: ${error.message}`);
        } finally {
            stopBotButton.innerHTML = '<i class="fas fa-stop"></i> Stop Viewbot';
            stopBotButton.disabled = false;
        }
    }

    function pollStatus() {
        if (statusInterval) clearInterval(statusInterval);
        
        statusInterval = setInterval(async () => {
            if (!isBotRunning) {
                clearInterval(statusInterval);
                return;
            }

            const token = localStorage.getItem('accessToken');
            if (!token) {
                clearInterval(statusInterval);
                return;
            }
            try {
                const response = await fetch(`${API_BASE_URL}/api/status`, {
                     headers: { 'Authorization': `Bearer ${token}` }
                });
                if (!response.ok) {
                    if (response.status === 401) {
                        localStorage.removeItem('accessToken');
                        showLoginState();
                    }
                    isBotRunning = false;
                    stopDurationTimer();
                    showPage('viewbot');
                    clearInterval(statusInterval);
                    return;
                }
                
                const status = await response.json();
                isBotRunning = status.is_running;

                if (isBotRunning) {
                    updateStatusDisplay(status);
                } else {
                    stopDurationTimer();
                    showPage('viewbot');
                    clearInterval(statusInterval);
                }

            } catch (error) {
                console.error('Polling error:', error.message);
                isBotRunning = false;
                stopDurationTimer();
                showPage('viewbot');
                clearInterval(statusInterval);
            }
        }, 2000); // Poll every 2 seconds
    }

    function startDurationTimer() {
        if (durationInterval) clearInterval(durationInterval);
        durationInterval = setInterval(() => {
            timeRemaining--;
            if (timeRemaining < 0) {
                timeRemaining = 0;
                clearInterval(durationInterval);
            }
            updateTimerDisplay();
        }, 1000);
    }

    function stopDurationTimer() {
        if (durationInterval) clearInterval(durationInterval);
    }

    function updateTimerDisplay() {
        const minutes = Math.floor(timeRemaining / 60);
        const seconds = timeRemaining % 60;
        if (timeRemainingSpan) {
            timeRemainingSpan.textContent = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
        }
    }

    function updateStatusDisplay(status) {
        const targetViewers = status.target_viewers || viewersSlider.value;
        const currentViewers = status.current_viewers || 0;
        const progress = status.progress_percent || 0;

        if (activeViewersSpan) activeViewersSpan.textContent = `${currentViewers} / ${targetViewers}`;
        if (progressBar) progressBar.style.width = `${progress}%`;
        if (progressPercentSpan) progressPercentSpan.textContent = `${Math.round(progress)}%`;
    }

    // --- Initial Load ---
    checkUserSession();
    showPage('viewbot'); // Show viewbot page by default
});
