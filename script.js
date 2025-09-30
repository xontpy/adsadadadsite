document.addEventListener('DOMContentLoaded', () => {
    // --- Constants and Variables ---
    // const API_BASE_URL = 'https://kickaviewss.onrender.com/callback'; // Removed duplicate declaration

    // --- Element References ---
    const loginButton = document.getElementById('login-button');
    const logoutButton = document.getElementById('logout-button');
    const userProfile = document.getElementById('user-profile');
    const userAvatar = document.getElementById('user-avatar');
    const usernameSpan = document.getElementById('username');
    const permissionsSpan = document.getElementById('permissions');
    const controlPanel = document.getElementById('control-panel');

    const viewbotTab = document.querySelector('[data-tab="viewbot-content"]');
    const proxiesTab = document.querySelector('[data-tab="proxies-content"]');
    const viewbotContent = document.getElementById('viewbot-content');
    const proxiesContent = document.getElementById('proxies-content');

    const startBotButton = document.getElementById('start-bot-button');
    const stopBotButton = document.getElementById('stop-bot-button');
    const channelInput = document.getElementById('channel-input');
    const viewersSlider = document.getElementById('viewers-slider');
    const viewersCount = document.getElementById('viewers-count'); // Corrected reference
    const durationSlider = document.getElementById('duration-slider');
    const durationCount = document.getElementById('duration-count'); // Corrected reference
    const saveProxiesButton = document.getElementById('save-proxies-button');
    const proxiesTextarea = document.getElementById('proxies-textarea');
    const statusBox = document.getElementById('status-box');
    const botStatusContainer = document.getElementById('bot-status-container');
    const botStatusLine = document.getElementById('bot-status-line');

    let statusInterval; // To hold the interval ID for polling
    let isBotRunning = false;

    // --- Event Listeners for Sliders ---
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


    // --- Configuration ---
    // This is the critical line to fix.
    const API_BASE_URL = 'https://kickaviewss.onrender.com';
    // --- Authentication ---
    
    // Function to get the token from the URL hash
    if (loginButton) {
        loginButton.addEventListener('click', () => {
            window.location.href = `${API_BASE_URL}/login`;
        });
    }

    if (logoutButton) {
        logoutButton.addEventListener('click', () => {
            localStorage.removeItem('accessToken');
            showLoginState();
            showStatus('Logged out successfully.', 'success');
        });
    }

    async function checkUserSession() {
        const hash = window.location.hash;
        if (hash.startsWith('#token=')) {
            const token = hash.substring('#token='.length);
            localStorage.setItem('accessToken', token);
            // Use replaceState to clean the URL without reloading
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
        pollStatus(); // Start polling for status immediately on page load
    }


async function fetchUserData(token) {
        console.log("Attempting to fetch user data with token:", token); // DEBUG
        try {
            const response = await fetch(`${API_BASE_URL}/api/me`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
    
            console.log("Response from /api/me:", response.status, response.statusText); // DEBUG

            if (response.ok) {
                const user = await response.json();
                console.log("Received user data:", user); // DEBUG
                showLoggedInState(user);
            } else {
                console.error("Failed to fetch user data. Status:", response.status); // DEBUG
                localStorage.removeItem('accessToken');
                showLoginState();
                if (response.status === 401) {
                    showStatus('Session expired. Please log in again.', 'error');
                }
            }
        } catch (error) {
            console.error('Error fetching user data:', error);
            showLoginState();
            showStatus('Failed to connect to server.', 'error');
        }
    }
    function showLoginState() {
        if (loginButton) loginButton.style.display = 'block';
        if (userProfile) userProfile.style.display = 'none';
        if (proxiesTab) proxiesTab.style.display = 'none';
        if (proxiesContent) proxiesContent.style.display = 'none';
        if (viewbotTab) viewbotTab.classList.add('active');
        if (viewbotContent) viewbotContent.style.display = 'block';
    }

    function showLoggedInState(user) {
        if (loginButton) loginButton.style.display = 'none';
        if (userProfile) userProfile.style.display = 'flex';
        
        if (usernameSpan) usernameSpan.textContent = user.username;
        if (permissionsSpan) permissionsSpan.textContent = `(Level: ${user.level})`;
        if (userAvatar) userAvatar.src = `https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png`;

        if (viewersSlider) {
            viewersSlider.max = user.max_views;
            if (parseInt(viewersSlider.value) > user.max_views) {
                viewersSlider.value = user.max_views;
            }
            if(viewersCount) viewersCount.textContent = viewersSlider.value;
        }
        // Also update the duration slider if needed, though no max is provided from user data

        // Show the proxies tab only for owners
        if (user.is_owner) {
            if (proxiesTab) proxiesTab.style.display = 'block';
            loadProxies();
        } else {
            if (proxiesTab) proxiesTab.style.display = 'none';
        }
    }

    // --- Bot Actions ---
    controlPanel.addEventListener('click', (event) => {
        const startButton = document.getElementById('start-bot-button');
        if (event.target === startButton || startButton.contains(event.target)) {
            if (isBotRunning) {
                stopBot();
            } else {
                startBot();
            }
        }
    });

    function updateStartButton(text, state) {
        const startButton = document.getElementById('start-bot-button');
        const buttonText = startButton.querySelector('span');
        const icon = startButton.querySelector('img');

        if (text) {
            buttonText.textContent = text;
        }

        if (state === 'running') {
            icon.src = 'assets/icons/stop-view-icon.svg';
            startButton.classList.remove('btn-success');
            startButton.classList.add('btn-danger');
        } else if (state === 'stopped') {
            icon.src = 'assets/icons/start-view-icon.svg';
            startButton.classList.remove('btn-danger');
            startButton.classList.add('btn-success');
        }
    }

    async function startBot() {
        const channel = channelInput.value;
        const viewers = viewersSlider.value;
        const duration = durationSlider.value;

        if (!channel) {
            showStatus('Please enter a Kick channel name.', 'error');
            return;
        }

        const token = localStorage.getItem('accessToken');
        if (!token) {
            showStatus('You are not logged in. Please log in to start the bot.', 'error');
            return;
        }

        const num_viewers = parseInt(viewers);
        const duration_minutes = parseInt(duration);

        if (isNaN(duration_minutes) || duration_minutes <= 0) {
            showStatus(`Invalid duration value detected: ${duration}. Please ensure you select a positive number of minutes.`, 'error');
            return;
        }
        
        const startButton = document.getElementById('start-bot-button');
        startButton.querySelector('span').textContent = 'Starting...';
        startButton.disabled = true;


        const payload = {
            channel: channel,
            views: num_viewers,
            duration: duration_minutes
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
                showStatus(data.message || 'Bot started successfully!', 'success');
                isBotRunning = true;
                pollStatus(); // Start polling immediately
            } else {
                throw new Error(data.detail || 'Failed to start bot.');
            }
        } catch (error) {
            showStatus(`Error starting bot: ${error.message}`, 'error');
            isBotRunning = false;
            updateStartButton('Start Views', 'stopped');
        } finally {
            startButton.disabled = false;
        }
    }

    async function stopBot() {
        const startButton = document.getElementById('start-bot-button');
        startButton.querySelector('span').textContent = 'Stopping...';
        startButton.disabled = true;

        const token = localStorage.getItem('accessToken');
        try {
            const response = await fetch(`${API_BASE_URL}/api/stop`, {
                method: 'POST',
                 headers: {
                    'Authorization': `Bearer ${token}`
                }
            });
            const data = await response.json();
            if (response.ok) {
                showStatus(data.message || 'Bot stopped successfully.', 'success');
                isBotRunning = false;
                botStatusContainer.style.display = 'none';
                botStatusLine.textContent = '';
            } else {
                throw new Error(data.detail || 'Failed to stop bot.');
            }
        } catch (error) {
            showStatus(`Error stopping bot: ${error.message}`, 'error');
        } finally {
            startButton.disabled = false;
            updateStartButton('Start Views', 'stopped');
        }
    }

    function pollStatus() {
        if (statusInterval) {
            clearInterval(statusInterval);
        }
        statusInterval = setInterval(async () => {
            const token = localStorage.getItem('accessToken');
            if (!token) {
                clearInterval(statusInterval);
                return;
            }
            try {
                const response = await fetch(`${API_BASE_URL}/api/status`, {
                     headers: {
                        'Authorization': `Bearer ${token}`
                    }
                });
                if (!response.ok) {
                    if (response.status === 401) {
                        showStatus('Session expired. Please log in again.', 'error');
                        localStorage.removeItem('accessToken');
                        showLoginState();
                        clearInterval(statusInterval);
                    }
                    throw new Error('Failed to fetch status.');
                }
                
                const status = await response.json();
                isBotRunning = status.is_running;

                const startButton = document.getElementById('start-bot-button');
                if (!startButton.disabled) {
                    if (isBotRunning) {
                        updateStartButton('Stop Views', 'running');
                    } else {
                        updateStartButton('Start Views', 'stopped');
                    }
                }

                if (status.is_running && status.status_line) {
                    botStatusContainer.style.display = 'block';
                    botStatusLine.innerHTML = status.status_line;
                } else {
                    botStatusContainer.style.display = 'none';
                }

            } catch (error) {
                console.error('Polling error:', error.message);
                showStatus('Connection to server lost. Retrying...', 'error');
            }
        }, 2000);
    }

    // --- Proxies Actions ---
    if (saveProxiesButton) {
        saveProxiesButton.addEventListener('click', async () => {
            const proxies = proxiesTextarea.value;
            showStatus('Saving proxies...', 'info');

            const token = localStorage.getItem('accessToken');
            try {
                const response = await fetch(`${API_BASE_URL}/api/save-proxies`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${token}`
                    },
                    body: JSON.stringify({ proxies: proxies }),
                });
                const result = await response.json();
                if (response.ok) {
                    showStatus(result.message, 'success');
                } else {
                    showStatus(`Error: ${result.detail || result.error}`, 'error');
                }
            } catch (error) {
                showStatus(`Network Error: ${error.message}`, 'error');
            }
        });
    }
    
    function showStatus(message, type = 'info', isToast = false) {
        if (statusBox) {
            statusBox.textContent = message;
            statusBox.className = `status-box ${type}`;

            if (isToast) {
                statusBox.classList.add('is-toast', 'show');
                setTimeout(() => {
                    statusBox.classList.remove('show');
                    // Remove the is-toast class after the animation is done
                    setTimeout(() => statusBox.classList.remove('is-toast'), 500);
                }, 3000);
            }
        }
    }

    // --- Initial Load ---
    checkUserSession();

    // --- Tab Switching ---
    const tabs = document.querySelectorAll('.tab-button');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            // Remove active class from all tabs and content
            tabs.forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');

            // Add active class to the clicked tab and show its content
            tab.classList.add('active');
            const tabContentId = tab.getAttribute('data-tab');
            document.getElementById(tabContentId).style.display = 'block';
        });
    });
});


// Function to show status toast
function showStatus(message, type = 'info') {
    const statusBox = document.getElementById('status-box');
    statusBox.textContent = message;
    statusBox.className = 'status-box show ' + type;
    setTimeout(() => {
        statusBox.className = statusBox.className.replace(' show', '');
    }, 3000);
}

// Function to fetch and display proxies
async function loadProxies() {
    const token = localStorage.getItem('discord_token');
    if (!token) return;

    try {
        const response = await fetch('/api/get-proxies', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (response.ok) {
            const data = await response.json();
            document.getElementById('proxies-textarea').value = data.proxies;
        } else {
            console.error('Failed to load proxies:', await response.text());
        }
    } catch (error) {
        console.error('Error loading proxies:', error);
    }
}

// Function to check authentication status
async function checkAuth() {
    const token = localStorage.getItem('discord_token');
    if (!token) {
        document.getElementById('main-content').style.display = 'block';
        document.getElementById('login-button').style.display = 'none';
        pollStatus(); // Start polling for bot status
        loadProxies(); // Load proxies on page load
    } else {
        // Not authenticated
        document.getElementById('login-button').style.display = 'block';
    }
}
