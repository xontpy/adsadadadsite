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
    }
    // --- Bot Actions ---
    if (startBotButton) {
        startBotButton.addEventListener('click', () => {
            const channel = channelInput.value;
            const viewers = viewersSlider.value;
            const duration = durationSlider.value;
    
            if (!channel) {
                alert('Please enter a Kick channel name.');
                return;
            }
    
            const token = localStorage.getItem('accessToken');
            if (!token) {
                showStatus('You are not logged in. Please log in to start the bot.', 'error');
                return;
            }

            fetch(`${API_BASE_URL}/api/start`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({
                    channel: channel,
                    num_viewers: parseInt(viewers),
                    duration: parseInt(duration)
                }),
            })
            .then(response => response.json())
            .then(data => {
                if (data.message) {
                    showStatus('Views have been sent. Please wait for them to arrive.', 'success');
                } else {
                    showStatus(data.detail || 'An unknown error occurred.', 'error');
                }
            })
            .catch(error => {
                console.error('Error starting bot:', error);
                showStatus('Failed to communicate with the server.', 'error');
            });
        });
    }

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
    
    function showStatus(message, type = 'info') {
        if (statusBox) {
            statusBox.textContent = message;
            statusBox.className = `status-box ${type}`;

            // Add the 'show' class to trigger the animation
            statusBox.classList.add('show');

            // Remove the 'show' class after 3 seconds
            setTimeout(() => {
                statusBox.classList.remove('show');
            }, 3000);
        }
    }

    // --- Initial Load ---
    checkUserSession();
});
