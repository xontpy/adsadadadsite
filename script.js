// Immediately check for an authentication token in the URL hash.
// If found, store it in localStorage and reload the page with a clean URL.
// This mimics the behavior of the old auth.html page and ensures the app
// always initializes from a clean state.
(function() {
    const hash = window.location.hash;
    if (hash.startsWith('#token=')) {
        const token = hash.substring('#token='.length);
        if (token) {
            localStorage.setItem('accessToken', token);
        }
        // Redirect to the root URL to clear the hash.
        // The rest of the script will execute on the reloaded page.
        window.location.href = '/';
    }
})();

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
    const kickViewbotPage = document.getElementById('kick-viewbot-page');
    const viewbotStatusScreen = document.querySelector('.viewbot-status');
    const viewsEndedModal = document.getElementById('views-ended-modal');
    const settingsPage = document.getElementById('settings-page');
    const logsPage = document.getElementById('logs-page');
    const supportPage = document.getElementById('support-page');

    const startBtn = document.getElementById('start-btn');
    const stopBotButton = document.getElementById('stop-bot-button');
    const viewsEndedDoneBtn = document.getElementById('views-ended-done-btn');

    const channelInput = document.getElementById('channel-input');
    const viewersSlider = document.getElementById('views-input');
    const viewersValue = document.getElementById('views-value');
    const durationSlider = document.getElementById('duration-input');
    const durationValue = document.getElementById('duration-value');
    const rapidToggle = document.getElementById('rapid-toggle');

    // Settings elements
    const themeSelect = document.getElementById('theme-select');
    const notificationsToggle = document.getElementById('notifications-toggle');

    // Status screen elements
    const activeViewersSpan = document.getElementById('active-viewers');
    const targetViewersSpan = document.getElementById('target-viewers');
    const totalDurationSpan = document.getElementById('total-duration');
    const timeRemainingSpan = document.getElementById('time-remaining');
    const progressBar = document.getElementById('progress-bar');
    const progressPercent = document.getElementById('progress-percent');
    const logContainer = document.getElementById('logs-content');

    // --- State Variables ---
    let statusPollInterval;
    let botState = 'idle'; // State machine: idle, starting, running, stopping, ended
    let activePage = 'viewbot';
    let notificationsEnabled = true;
    let statusFalseCount = 0;

    // --- Functions ---

    function playSuccessSound() {
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = audioContext.createOscillator();
        const gainNode = audioContext.createGain();
        oscillator.connect(gainNode);
        gainNode.connect(audioContext.destination);
        oscillator.frequency.setValueAtTime(800, audioContext.currentTime);
        oscillator.frequency.setValueAtTime(1000, audioContext.currentTime + 0.1);
        gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.5);
        oscillator.start(audioContext.currentTime);
        oscillator.stop(audioContext.currentTime + 0.5);
    }

    function applyTheme(theme) {
        document.body.className = theme;
        localStorage.setItem('theme', theme);
    }

    function requestNotificationPermission() {
        if ('Notification' in window && Notification.permission === 'default') {
            Notification.requestPermission();
        }
    }

    function showNotification(title, body) {
        if (notificationsEnabled && 'Notification' in window && Notification.permission === 'granted') {
            new Notification(title, { body: body, icon: '/assets/logo.png' });
        }
    }

    function loadSettings() {
        const savedTheme = localStorage.getItem('theme') || 'dark';
        if (themeSelect) themeSelect.value = savedTheme;
        applyTheme(savedTheme);

        const savedNotifications = localStorage.getItem('notifications');
        notificationsEnabled = savedNotifications !== null ? savedNotifications === 'true' : true;
        if (notificationsToggle) notificationsToggle.checked = notificationsEnabled;

        if (notificationsEnabled) {
            requestNotificationPermission();
        }
    }

    function showCorrectScreen() {
        // Hide all pages first
        if (kickViewbotPage) kickViewbotPage.style.display = 'none';
        if (viewbotStatusScreen) viewbotStatusScreen.style.display = 'none';
        if (settingsPage) settingsPage.style.display = 'none';
        if (logsPage) logsPage.style.display = 'none';
        if (supportPage) supportPage.style.display = 'none';

        const isBotActive = ['running', 'starting', 'stopping'].includes(botState);
        const header = document.querySelector('.main-header h1');

        // If a bot is running and the user is on a bot page, show the status screen.
        if (isBotActive && activePage === 'viewbot') {
            if (viewbotStatusScreen) viewbotStatusScreen.style.display = 'block';
            if (header) header.textContent = 'Viewbot Running';
        } else {
            // Otherwise, show the normally selected page and restore its title.
            const activeMenuItem = document.querySelector(`.menu-item.active`);
            if (header && activeMenuItem) {
                if (activePage === 'viewbot') {
                    header.textContent = 'Kick Viewbot';
                } else {
                    header.textContent = activeMenuItem.textContent.trim();
                }
            }

            switch (activePage) {
                case 'viewbot':
                    if (kickViewbotPage) kickViewbotPage.style.display = 'block';
                    break;
                case 'settings':
                    if (settingsPage) settingsPage.style.display = 'block';
                    break;
                case 'logs':
                    if (logsPage) logsPage.style.display = 'block';
                    break;
                case 'support':
                    if (supportPage) supportPage.style.display = 'block';
                    break;
                default: // Default to kick viewbot page on initial load
                    if (kickViewbotPage) kickViewbotPage.style.display = 'block';
                    if (header) header.textContent = 'Kick Viewbot';
                    break;
            }
        }
    }

    async function checkUserSession() {
        // The logic for handling the URL hash has been moved to the top of the script.
        // This function now only needs to check for a token in localStorage.
        const storedToken = localStorage.getItem('accessToken');
        if (storedToken) {
            await fetchUserData(storedToken);
        } else {
            showLoginState();
        }
    }

    async function fetchUserData(token) {
        try {
            const response = await fetch(`${API_BASE_URL}/api/me`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (response.ok) {
                const user = await response.json();
                showLoggedInState(user);
                // If user is logged in, do an initial status check
                // This will restore the status screen if a bot is already running
                pollStatus();
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
        showCorrectScreen();
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
        } else if (premiumPlanBanner) {
            premiumPlanBanner.style.display = 'none';
        }
        if (userAvatar) userAvatar.src = `https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png`;

        if (viewersSlider && viewersValue) {
            viewersSlider.max = user.max_views || 100;
            if (parseInt(viewersSlider.value) > viewersSlider.max) {
                viewersSlider.value = viewersSlider.max;
            }
            viewersValue.textContent = viewersSlider.value;
        }
        showCorrectScreen();
    }

    function updateStatusUI(status) {
        if (!status) return;

        if(activeViewersSpan) activeViewersSpan.textContent = `${status.current_viewers || 0} / ${status.target_viewers || 0}`;
        if(totalDurationSpan) totalDurationSpan.textContent = status.total_duration_str || 'Unlimited';
        if(timeRemainingSpan) timeRemainingSpan.textContent = status.time_remaining_str || '00:00';

        const progress = status.progress_percent || 0;
        if(progressBar) progressBar.style.width = `${progress}%`;
        if(progressPercent) progressPercent.textContent = `${Math.round(progress)}%`;

        if (status.logs) {
            const logText = status.logs.join('\n');
            if (logContainer) { // Part of the status screen
                logContainer.innerHTML = logText;
                logContainer.scrollTop = logContainer.scrollHeight;
            }
            if (logsPage) { // The dedicated Logs page
                // Create a preformatted element to preserve line breaks
                logsPage.innerHTML = `<pre class="logs-full-content">${logText}</pre>`;
                const logContent = logsPage.querySelector('.logs-full-content');
                if (logContent) {
                    logContent.scrollTop = logContent.scrollHeight;
                }
            }
        }

        // Hide stop button if bot not running or not in running state
        if (stopBotButton) {
            stopBotButton.style.display = (botState === 'running' || status.is_running) ? 'flex' : 'none';
        }

        // Ensure menu items are always enabled
        const menuItems = document.querySelectorAll('.menu-item');
        menuItems.forEach(item => {
            item.style.pointerEvents = 'auto';
            item.style.opacity = '1';
        });
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
                    statusFalseCount = 0;
                    if (botState === 'idle' || botState === 'ended') {
                        botState = 'running';
                        startPolling();
                    }
                } else { // Bot is not running
                    if (botState === 'stopping') {
                        botState = 'ended';
                        stopPolling();
                    } else if (botState === 'running') {
                        statusFalseCount++;
                        // Disabled automatic reset to prevent UI from resetting
                        // if (statusFalseCount > 50) {
                        //     botState = 'ended';
                        //     stopPolling();
                        //     showNotification('Bot Stopped', 'Bot was inactive for too long and has been stopped.');
                        // } else {
                            showNotification('Bot Status Warning', 'Bot status became inactive. Check logs for details.');
                        // }
                        // Keep polling and state until count exceeds
                    } else {
                        botState = 'ended';
                        stopPolling();
                    }
                }
            } else {
                // Don't change state or stop polling on server errors to prevent resetting running bots
                console.error('Server responded with error:', response.status);
            }
        } catch (error) {
            console.error('Polling error:', error);
            // Don't change state or stop polling on poll errors, to prevent resetting running bots
        } finally {
            showCorrectScreen();
        }
    }

    function startPolling() {
        if (statusPollInterval) return;
        statusPollInterval = setInterval(pollStatus, 5000);
    }

    function stopPolling() {
        clearInterval(statusPollInterval);
        statusPollInterval = null;
    }

    async function startBot(platform) {
        const token = localStorage.getItem('accessToken');
        if (!token) {
            alert('Please log in first.');
            return;
        }

        statusFalseCount = 0;
        botState = 'starting';
        
        let payload;
        let startButton;
        let apiUrl;

        if (platform === 'kick') {
            apiUrl = `${API_BASE_URL}/api/start`;
            startButton = startBtn;
            payload = {
                channel: channelInput.value,
                views: parseInt(viewersSlider.value, 10),
                duration: parseInt(durationSlider.value, 10),
                rapid: rapidToggle.checked
            };
            if(startButton) {
                startButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Starting...';
                startButton.disabled = true;
            }
        } else {
            return;
        }

        showCorrectScreen();

        try {
            const response = await fetch(apiUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify(payload)
            });

            if (response.ok) {
                playSuccessSound();
                botState = 'running';
                startPolling();
                showNotification(`Viewbot Started`, `Sending ${payload.views} views to ${payload.channel}`);
            } else {
                const errorData = await response.json();
                alert(`Error starting bot: ${errorData.detail}`);
                botState = 'idle';
            }
        } catch (error) {
            alert(`Failed to connect to the server: ${error}`);
            botState = 'idle';
        } finally {
            if(startButton) {
                const buttonText = 'Start Viewbot';
                startButton.innerHTML = `<i class="fas fa-play"></i> ${buttonText}`;
                startButton.disabled = false;
            }
            showCorrectScreen();
        }
    }

    async function stopBot() {
        const token = localStorage.getItem('accessToken');
        if (!token) return;

        botState = 'stopping';
        if(stopBotButton) {
            stopBotButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Stopping...';
            stopBotButton.disabled = true;
        }
        showCorrectScreen();

        try {
            await fetch(`${API_BASE_URL}/api/stop`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            showNotification('Viewbot Stopped', 'The viewbot has been stopped.');
        } catch (error) {
            alert(`Error stopping bot: ${error}`);
        } finally {
            if(stopBotButton) {
                stopBotButton.innerHTML = '<i class="fas fa-stop"></i> Stop Viewbot';
                stopBotButton.disabled = false;
            }
            await pollStatus();
        }
    }

    // --- Event Listeners ---
    if (loginButton) {
        loginButton.addEventListener('click', () => {
            // Redirect to the backend /login route to initiate Discord OAuth
            window.location.href = `${API_BASE_URL}/login`;
        });
    }

    if (logoutButton) {
        logoutButton.addEventListener('click', () => {
            localStorage.removeItem('accessToken');
            // We can just reload the page. checkUserSession will handle showing the login button.
            window.location.reload();
        });
    }

    menuItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            activePage = item.dataset.page;
            menuItems.forEach(i => i.classList.remove('active'));
            item.classList.add('active');

            // The header text is now managed by showCorrectScreen to handle the "Viewbot Running" state
            showCorrectScreen();
        });
    });

    if (viewersSlider) {
        viewersSlider.addEventListener('input', (e) => {
            viewersValue.textContent = e.target.value;
        });
    }

    if (durationSlider) {
        durationSlider.addEventListener('input', (e) => {
            durationValue.textContent = `${e.target.value} min`;
        });
    }

    if (startBtn) {
        startBtn.addEventListener('click', () => startBot('kick'));
    }

    if (stopBotButton) {
        stopBotButton.addEventListener('click', stopBot);
    }

    if (viewsEndedDoneBtn) {
        viewsEndedDoneBtn.addEventListener('click', () => {
            if(viewsEndedModal) viewsEndedModal.style.display = 'none';
            botState = 'idle';
            showCorrectScreen();
        });
    }

    if (themeSelect) {
        themeSelect.addEventListener('change', () => {
            applyTheme(themeSelect.value);
        });
    }

    if (notificationsToggle) {
        notificationsToggle.addEventListener('change', () => {
            notificationsEnabled = notificationsToggle.checked;
            localStorage.setItem('notifications', notificationsEnabled);
            if (notificationsEnabled) {
                requestNotificationPermission();
            }
        });
    }

    // --- Initial Load ---
    loadSettings();
    checkUserSession();
});
