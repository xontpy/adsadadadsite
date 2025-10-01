document.addEventListener('DOMContentLoaded', () => {
    // --- Constants ---
    const API_BASE_URL = ''; // Correct for single-server setup

    // --- Element References ---
    const loginButton = document.getElementById('login-button');
    const logoutButton = document.getElementById('logout-button');
    const userProfile = document.getElementById('user-profile');
    const userAvatar = document.getElementById('user-avatar');
    const usernameSpan = document.getElementById('username');
    const permissionsSpan = document.getElementById('permissions');
    const premiumPlanBanner = document.querySelector('.premium-plan');

    const menuItems = document.querySelectorAll('.menu-item');
    const viewbotControlsScreen = document.querySelector('.viewbot-controls');
    const viewbotStatusScreen = document.querySelector('.viewbot-status');
    const viewsEndedScreen = document.querySelector('.views-ended-status');
    const settingsPage = document.getElementById('settings-page');
    const logsPage = document.getElementById('logs-page');

    const startBtn = document.getElementById('start-btn');
    const stopBotButton = document.getElementById('stop-bot-button');
    const viewsEndedDoneBtn = document.getElementById('views-ended-done-btn');

    const channelInput = document.getElementById('channel-input');
    const viewersSlider = document.getElementById('views-input');
    const viewersValue = document.getElementById('views-value');
    const durationSlider = document.getElementById('duration-input');
    const durationValue = document.getElementById('duration-value');

    // Status screen elements
    const activeViewersSpan = document.getElementById('active-viewers');
    const targetViewersSpan = document.getElementById('target-viewers');
    const timeRemainingSpan = document.getElementById('time-remaining');
    const progressBar = document.getElementById('progress-bar');
    const progressPercent = document.getElementById('progress-percent');
    const logContainer = document.getElementById('logs-content');
    const finalViewersSpan = document.getElementById('final-viewers-count');

    // --- State Variables ---
    let statusPollInterval;
    let botState = 'idle'; // State machine: idle, starting, running, stopping, ended
    let activePage = 'viewbot';

    // --- Functions ---

    function showCorrectScreen() {
        // Hide all pages first
        viewbotControlsScreen.style.display = 'none';
        viewbotStatusScreen.style.display = 'none';
        viewsEndedScreen.style.display = 'none';
        settingsPage.style.display = 'none';
        logsPage.style.display = 'none';

        // Show the correct page based on the active menu item and bot state
        if (activePage === 'viewbot') {
            if (botState === 'running' || botState === 'starting' || botState === 'stopping') {
                viewbotStatusScreen.style.display = 'block';
            } else if (botState === 'ended') {
                viewsEndedScreen.style.display = 'block';
            } else { // idle
                viewbotControlsScreen.style.display = 'block';
            }
        } else if (activePage === 'settings') {
            settingsPage.style.display = 'block';
        } else if (activePage === 'logs') {
            logsPage.style.display = 'block';
        }
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
        // Sync with server state on load
        await pollStatus();
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
            viewersSlider.max = user.max_views || 100;
            if (parseInt(viewersSlider.value) > viewersSlider.max) {
                viewersSlider.value = viewersSlider.max;
            }
            if(viewersValue) viewersValue.textContent = viewersSlider.value;
        }
    }

    function updateStatusUI(status) {
        if (!status) return;

        activeViewersSpan.textContent = status.current_viewers || 0;
        targetViewersSpan.textContent = status.target_viewers || 0;
        timeRemainingSpan.textContent = status.time_elapsed_str || '00:00';

        const progress = status.progress_percent || 0;
        if(progressBar) progressBar.style.width = `${progress}%`;
        if(progressPercent) progressPercent.textContent = `${Math.round(progress)}%`;

        if (status.logs && logContainer) {
            logContainer.innerHTML = status.logs.join('\n');
            logContainer.scrollTop = logContainer.scrollHeight;
        }
    }

    async function pollStatus() {
        const token = localStorage.getItem('accessToken');
        if (!token) {
            stopPolling();
            return;
        }

        try {
            const response = await fetch(`${API_BASE_URL}/api/status`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            const status = await response.json();

            if (response.ok) {
                updateStatusUI(status);

                if (status.is_running) {
                    if (botState === 'idle' || botState === 'ended') {
                        botState = 'running';
                        startPolling(); // Start continuous polling if bot is running
                    }
                } else { // Bot is not running
                    if (botState === 'running' || botState === 'stopping') {
                        botState = 'ended';
                        finalViewersSpan.textContent = activeViewersSpan.textContent || 0;
                    }
                    stopPolling(); // Stop polling if bot is not running
                }
            } else {
                 // Handle cases where status returns an error (e.g. 401)
                if (botState === 'running') {
                    botState = 'ended';
                    finalViewersSpan.textContent = activeViewersSpan.textContent;
                }
                stopPolling();
            }
        } catch (error) {
            console.error('Polling error:', error);
            if (botState !== 'idle') botState = 'ended';
            stopPolling();
        } finally {
            showCorrectScreen();
        }
    }

    function startPolling() {
        if (statusPollInterval) return; // Already polling
        statusPollInterval = setInterval(pollStatus, 2000);
    }

    function stopPolling() {
        clearInterval(statusPollInterval);
        statusPollInterval = null;
    }

    async function startBot() {
        const token = localStorage.getItem('accessToken');
        if (!token) {
            alert('Please log in first.');
            return;
        }

        botState = 'starting';
        startBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Starting...';
        startBtn.disabled = true;
        showCorrectScreen();

        const payload = {
            channel: channelInput.value,
            views: parseInt(viewersSlider.value, 10),
            duration: parseInt(durationSlider.value, 10)
        };

        try {
            const response = await fetch(`${API_BASE_URL}/api/start`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify(payload)
            });

            if (response.ok) {
                botState = 'running';
                startPolling();
            } else {
                const errorData = await response.json();
                alert(`Error starting bot: ${errorData.detail}`);
                botState = 'idle';
            }
        } catch (error) {
            alert(`Failed to connect to the server: ${error}`);
            botState = 'idle';
        } finally {
            startBtn.innerHTML = 'Start Viewbot';
            startBtn.disabled = false;
            showCorrectScreen();
        }
    }

    async function stopBot() {
        const token = localStorage.getItem('accessToken');
        if (!token) return;

        botState = 'stopping';
        stopBotButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Stopping...';
        stopBotButton.disabled = true;
        showCorrectScreen();

        try {
            await fetch(`${API_BASE_URL}/api/stop`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            // The poller will detect the stop and transition the state
        } catch (error) {
            alert(`Error stopping bot: ${error}`);
        } finally {
            stopBotButton.innerHTML = '<i class="fas fa-stop"></i> Stop Viewbot';
            stopBotButton.disabled = false;
            await pollStatus(); // One last poll to get final state
        }
    }

    // --- Event Listeners ---
    menuItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            activePage = item.dataset.page;
            menuItems.forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            showCorrectScreen();
        });
    });

    if (viewersSlider) {
        viewersSlider.addEventListener('input', () => {
            viewersValue.textContent = viewersSlider.value;
        });
    }

    if (durationSlider) {
        durationSlider.addEventListener('input', () => {
            durationValue.textContent = `${durationSlider.value} min`;
        });
    }

    if (loginButton) {
        loginButton.addEventListener('click', () => {
            window.location.href = '/login';
        });
    }

    if (logoutButton) {
        logoutButton.addEventListener('click', () => {
            localStorage.removeItem('accessToken');
            botState = 'idle';
            window.location.reload();
        });
    }

    if (startBtn) {
        startBtn.addEventListener('click', startBot);
    }

    if (stopBotButton) {
        stopBotButton.addEventListener('click', stopBot);
    }

    if (viewsEndedDoneBtn) {
        viewsEndedDoneBtn.addEventListener('click', () => {
            botState = 'idle';
            showCorrectScreen();
        });
    }

    // --- Initial Load ---
    checkUserSession();
});
