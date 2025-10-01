document.addEventListener('DOMContentLoaded', () => {
    // --- Constants ---
    const API_BASE_URL = ''; // Assuming APIs are on the same host

    // --- Element References ---
    const loginButton = document.getElementById('login-button');
    const logoutButton = document.getElementById('logout-button');
    const userProfile = document.getElementById('user-profile');
    const userAvatar = document.getElementById('user-avatar');
    const usernameSpan = document.getElementById('username');
    const permissionsSpan = document.getElementById('permissions');
    const premiumPlanBanner = document.querySelector('.premium-plan');

    const menuItems = document.querySelectorAll('.menu-item');
    const viewbotPage = document.querySelector('.viewbot-controls');
    const viewbotStatusPage = document.querySelector('.viewbot-status');
    const settingsPage = document.getElementById('settings-page');
    const logsPage = document.getElementById('logs-page');

    const startBtn = document.getElementById('start-btn');
    const stopBotButton = document.getElementById('stop-bot-button');
    const channelInput = document.getElementById('channel-input');
    
    const viewersSlider = document.getElementById('views-input');
    const viewersValue = document.getElementById('views-value');
    const durationSlider = document.getElementById('duration-input');
    const durationValue = document.getElementById('duration-value');
    const viewerSpeedInput = document.getElementById('viewer-speed-input');
    const viewerSpeedValue = document.getElementById('viewer-speed-value');

    // Status screen elements
    const activeViewersSpan = document.getElementById('active-viewers');
    const timeRemainingSpan = document.getElementById('time-remaining');
    const statusLine = document.getElementById('status-line');
    const progressBar = document.getElementById('progress-bar');
    const progressPercent = document.getElementById('progress-percent');
    const logsContent = document.getElementById('logs-content');

    // --- State Variables ---
    let isBotRunning = false;
    let wasRunning = false;
    let timeRemaining = 0;
    let statusInterval;
    let durationInterval;

    // --- Functions ---

    function getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) return parts.pop().split(';').shift();
        return null;
    }

    function showPage(pageId) {
        const pages = [viewbotPage, viewbotStatusPage, settingsPage, logsPage];
        let pageToShow = null;

        if (pageId === 'viewbot') {
            pageToShow = isBotRunning ? viewbotStatusPage : viewbotPage;
        } else if (pageId === 'settings') {
            pageToShow = settingsPage;
        } else if (pageId === 'logs') {
            pageToShow = logsPage;
        }
        // Add other pages here if needed

        pages.forEach(p => {
            if (p && p.style.display !== 'none') {
                p.style.display = 'none';
            }
        });

        if (pageToShow) {
            pageToShow.style.display = 'block';
        }

        menuItems.forEach(item => {
            if (item.dataset.page === pageId) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
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
        await pollStatus(true);
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
            if(viewersValue) viewersValue.textContent = viewersSlider.value;
        }
    }

    async function startBot() {
        const channel = channelInput.value;
        const views = parseInt(viewersSlider.value, 10);
        const duration = parseInt(durationSlider.value, 10);
        const viewerSpeed = parseFloat(viewerSpeedInput.value);

        if (!channel) {
            alert('Please enter a channel name.');
            return;
        }

        const token = localStorage.getItem('accessToken');
        if (!token) {
            alert('You are not logged in. Please log in to start the bot.');
            return;
        }

        if(startBtn) {
            startBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Starting...';
            startBtn.disabled = true;
        }

        const payload = {
            channel: channel,
            views: views,
            duration: duration,
            viewer_speed: viewerSpeed
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

            const result = await response.json();
            if (response.ok) {
                isBotRunning = true;
                timeRemaining = duration * 60;
                updateStatusDisplay({ is_running: true, status_line: 'Initializing...', target_viewers: views });
                startDurationTimer();
                showPage('viewbot');
                pollStatus();
            } else {
                throw new Error(result.detail || 'Failed to start bot.');
            }
        } catch (error) {
            alert(`Error starting bot: ${error.message}`);
            isBotRunning = false;
            showPage('viewbot');
        } finally {
            if(startBtn) {
                startBtn.innerHTML = '<i class="fas fa-play"></i> Start Viewbot';
                startBtn.disabled = false;
            }
        }
    }

    async function stopBot() {
        if(stopBotButton) {
            stopBotButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Stopping...';
            stopBotButton.disabled = true;
        }

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
            if(stopBotButton) {
                stopBotButton.innerHTML = '<i class="fas fa-stop"></i> Stop Viewbot';
                stopBotButton.disabled = false;
            }
        }
    }

    async function pollStatus(once = false) {
        const executePoll = async () => {
            const token = localStorage.getItem('accessToken');
            if (!token) {
                if (statusInterval) clearInterval(statusInterval);
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
                } else {
                    const status = await response.json();
                    isBotRunning = status.is_running;
                    updateStatusDisplay(status);
                    
                    if (status.logs && Array.isArray(status.logs)) {
                        updateLogsDisplay(status.logs);
                    }
                }

                if (isBotRunning !== wasRunning) {
                    showPage('viewbot');
                }
                wasRunning = isBotRunning;

            } catch (error) {
                console.error('Polling error:', error.message);
                isBotRunning = false;
                if (isBotRunning !== wasRunning) showPage('viewbot');
                wasRunning = false;
            }
        };

        await executePoll();
        if (!once) {
            if (statusInterval) clearInterval(statusInterval);
            statusInterval = setInterval(executePoll, 2000);
        }
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

    function updateStatusDisplay(data) {
        const modal = document.getElementById('views-ended-modal');
        if (wasRunning && !data.is_running && modal) {
            modal.style.display = 'flex';
        }

        if (data.is_running) {
            const statusText = data.status_line || 'Running...';
            if(statusLine) statusLine.textContent = statusText;
            
            const currentViewers = data.current_viewers || 0;
            const targetViewers = data.target_viewers || 0;
            if(activeViewersSpan) activeViewersSpan.textContent = `${currentViewers} / ${targetViewers}`;

            let progress = 0;
            if (targetViewers > 0) {
                progress = (currentViewers / targetViewers) * 100;
            }
            
            if(progressBar) progressBar.style.width = `${progress}%`;
            if(progressPercent) progressPercent.textContent = `${Math.round(progress)}%`;

        } else {
            if(statusLine) statusLine.textContent = data.status_line || 'Not running.';
            if(progressBar) progressBar.style.width = '0%';
            if(progressPercent) progressPercent.textContent = '0%';
        }
    }

    function updateLogsDisplay(logs) {
        if (logsContent) {
            // Backend sends logs with newest first.
            logsContent.innerHTML = logs.join('\n');
        }
    }

    // --- Event Listeners ---
    menuItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const pageId = item.dataset.page;
            showPage(pageId);
        });
    });

    if (viewersSlider && viewersValue) {
        viewersSlider.addEventListener('input', () => {
            viewersValue.textContent = viewersSlider.value;
        });
    }

    if (durationSlider && durationValue) {
        durationSlider.addEventListener('input', () => {
            durationValue.textContent = `${durationSlider.value} min`;
        });
    }

    if (viewerSpeedInput && viewerSpeedValue) {
        viewerSpeedInput.addEventListener('input', () => {
            viewerSpeedValue.textContent = `${parseFloat(viewerSpeedInput.value).toFixed(2)}s`;
        });
    }
    
    const viewsEndedDoneBtn = document.getElementById('views-ended-done-btn');
    if (viewsEndedDoneBtn) {
        viewsEndedDoneBtn.addEventListener('click', () => {
            const modal = document.getElementById('views-ended-modal');
            if(modal) modal.style.display = 'none';
        });
    }

    if (loginButton) {
        loginButton.addEventListener('click', () => {
            window.location.href = '/login';
        });
    }

    if(logoutButton) {
        logoutButton.addEventListener('click', () => {
            localStorage.removeItem('accessToken');
            window.location.reload();
        });
    }

    if (startBtn) {
        startBtn.addEventListener('click', startBot);
    }

    if (stopBotButton) {
        stopBotButton.addEventListener('click', stopBot);
    }

    // --- Initial Load ---
    checkUserSession();
    showPage('viewbot');
});
