// ==UserScript==
// @name         Adult Time to Buttplug.io Bridge
// @namespace    https://github.com/yourusername/adulttime-buttplug-bridge
// @version      0.3
// @description  Connect Adult Time videos to Intiface/Buttplug.io devices with auto-funscript
// @author       Your Name
// @match        *://*.adulttime.com/*
// @match        *://*.adultempire.com/*
// @match        *://adulttime.com/*
// @require      https://cdn.jsdelivr.net/npm/buttplug@3.0.0/dist/web/buttplug.min.js
// @grant        GM_xmlhttpRequest
// @grant        unsafeWindow
// @connect      localhost
// @connect      transform.gammacdn.com
// @connect      coll.lovense.com
// @run-at       document-end
// @noframes
// ==/UserScript==

/* global Buttplug */

(function() {
    'use strict';

    // Defensive programming - prevent conflicts with other scripts
    try {
        // Prevent attempts to modify read-only properties
        if (typeof window.ethereum !== 'undefined') {
            // Don't interfere with existing ethereum property
        }
    } catch (e) {
        // Silently ignore ethereum property errors
        console.debug('[AT-BP Bridge] Ethereum property access ignored:', e.message);
    }

    // Configuration
    const config = {
        // Bridge server URL (running on localhost)
        bridgeUrl: 'http://localhost:8080',

        // Use bridge mode (true for bridge, false for direct connection)
        useBridge: true,

        // Auto-download funscripts
        autoFunscript: true,

        // Debug mode
        debug: true
    };

    // Logging function
    const log = (...args) => {
        if (config.debug) {
            console.log('[AT-BP Bridge]', ...args);
        }
    };

    // Global variables
    let videoElement = null;
    let lastSendTime = 0;
    let connected = false;
    let uiContainer = null;
    let funscriptData = null;
    let funscriptActions = [];
    let lastActionIndex = 0;
    let currentVideoUrl = null;

    // --------------------------------
    // Bridge Server Communication
    // --------------------------------

    function sendToBridge(eventType, data = {}) {
        if (!config.useBridge) {
            return;
        }

        const payload = {
            type: eventType,
            ...data,
            timestamp: Date.now()
        };

        GM_xmlhttpRequest({
            method: 'POST',
            url: `${config.bridgeUrl}/api/video-event`,
            data: JSON.stringify(payload),
            headers: {
                'Content-Type': 'application/json'
            },
            onload: function(response) {
                log('Bridge response:', response.responseText);
            },
            onerror: function(error) {
                log('Bridge error:', error);
            }
        });
    }

    // --------------------------------
    // Auto Funscript Download
    // --------------------------------

    function autoDownloadFunscript() {
        if (!config.autoFunscript) return;

        const currentUrl = window.location.href;
        if (currentUrl === currentVideoUrl) return; // Already processed this video

        currentVideoUrl = currentUrl;
        log('Attempting auto-funscript download for:', currentUrl);

        try {
            const videoTitle = document.title || '';
            const videoDuration = videoElement ? Math.floor(videoElement.duration * 1000) : 0;

            const requestData = {
                url: currentUrl,
                title: videoTitle,
                duration: videoDuration
            };

            // Use GM_xmlhttpRequest to bypass CSP restrictions
            GM_xmlhttpRequest({
                method: 'POST',
                url: `${config.bridgeUrl}/api/auto-funscript`,
                data: JSON.stringify(requestData),
                headers: {
                    'Content-Type': 'application/json'
                },
                onload: function(response) {
                    try {
                        const result = JSON.parse(response.responseText);
                        
                        if (result.success) {
                            processFunscript(result.funscript);
                            showNotification(`🎯 Auto-loaded ${result.actions} funscript actions!`);
                            log('Auto-funscript download successful:', result);
                        } else {
                            log('No funscript available for this video:', result.error);
                            showNotification('ℹ️ No interactive content found for this video');
                        }
                    } catch (parseError) {
                        log('Error parsing funscript response:', parseError);
                        showNotification('⚠️ Error processing funscript response');
                    }
                },
                onerror: function(error) {
                    log('Auto-funscript download failed:', error);
                    showNotification('⚠️ Auto-funscript download failed');
                }
            });

        } catch (error) {
            log('Auto-funscript download error:', error);
            showNotification('⚠️ Auto-funscript download error');
        }
    }

    // --------------------------------
    // Funscript Handling
    // --------------------------------

    function processFunscript(funscript) {
        try {
            funscriptData = funscript;
            funscriptActions = funscript.actions || [];
            
            // Sort actions by timestamp to ensure proper order
            funscriptActions.sort((a, b) => a.at - b.at);
            
            lastActionIndex = 0;
            
            log('Funscript loaded:', {
                version: funscript.version,
                actions: funscriptActions.length,
                duration: funscriptActions.length > 0 ? 
                    (funscriptActions[funscriptActions.length - 1].at / 1000).toFixed(1) + 's' : '0s',
                range: funscript.range || 100
            });
            
            updateFunscriptUI();
        } catch (error) {
            log('Error processing funscript:', error);
            showNotification('Error processing funscript: ' + error.message);
        }
    }

    function getFunscriptIntensity(currentTimeMs) {
        if (!funscriptActions || funscriptActions.length === 0) {
            return null;
        }

        // Find the current and next action points
        let currentAction = null;
        let nextAction = null;

        // Optimize search by starting from last known position
        for (let i = Math.max(0, lastActionIndex - 1); i < funscriptActions.length; i++) {
            if (funscriptActions[i].at <= currentTimeMs) {
                currentAction = funscriptActions[i];
                lastActionIndex = i;
            } else {
                nextAction = funscriptActions[i];
                break;
            }
        }

        if (!currentAction) {
            // Before first action
            return funscriptActions[0].pos / 100;
        }

        if (!nextAction) {
            // After last action
            return currentAction.pos / 100;
        }

        // Interpolate between current and next action
        const timeDiff = nextAction.at - currentAction.at;
        const timeProgress = (currentTimeMs - currentAction.at) / timeDiff;
        const posDiff = nextAction.pos - currentAction.pos;
        const interpolatedPos = currentAction.pos + (posDiff * timeProgress);

        // Convert position (0-100) to intensity (0-1)
        return Math.max(0, Math.min(1, interpolatedPos / 100));
    }

    function clearFunscript() {
        funscriptData = null;
        funscriptActions = [];
        lastActionIndex = 0;
        updateFunscriptUI();
        showNotification('Funscript cleared');
        log('Funscript cleared');
    }

    function updateFunscriptUI() {
        if (uiContainer) {
            const statusElement = uiContainer.querySelector('#bp-funscript-status');
            if (statusElement) {
                if (funscriptData && funscriptActions.length > 0) {
                    statusElement.textContent = `📜 ${funscriptActions.length} actions loaded`;
                    statusElement.style.color = '#4CAF50';
                } else {
                    statusElement.textContent = '📜 No funscript loaded';
                    statusElement.style.color = '#FF9800';
                }
            }
        }
    }

    // --------------------------------
    // Image Proxy for CORS Issues
    // --------------------------------

    function loadImageThroughProxy(imageUrl) {
        /**
         * Load images through the bridge server proxy to bypass CORS restrictions
         * Usage: loadImageThroughProxy('https://transform.gammacdn.com/path/to/image.jpg')
         * Returns: Proxied URL that can be used without CORS issues
         */
        const encodedUrl = encodeURIComponent(imageUrl);
        return `${config.bridgeUrl}/api/proxy-image?url=${encodedUrl}`;
    }

    function createImageElement(originalImageUrl) {
        /**
         * Create an image element that uses the proxy to avoid CORS issues
         */
        const img = document.createElement('img');
        img.src = loadImageThroughProxy(originalImageUrl);
        img.style.crossOrigin = 'anonymous';
        return img;
    }

    // --------------------------------
    // Video Detection & Event Handling
    // --------------------------------

    function findVideoElement() {
        // Check for common video elements on Adult Time
        const videoSelectors = [
            'video',                   // Generic video tag
            '.vjs-tech',               // VideoJS player
            '.at-video-player video',  // Adult Time specific
            '.video-player video'      // General player
        ];

        for (const selector of videoSelectors) {
            const videos = document.querySelectorAll(selector);
            if (videos.length > 0) {
                // Return the first video element found
                return videos[0];
            }
        }

        return null;
    }

    function setupVideoEventListeners() {
        log('Looking for video element...');

        // Video might load dynamically, so we'll check periodically
        const checkInterval = setInterval(() => {
            videoElement = findVideoElement();

            if (videoElement) {
                clearInterval(checkInterval);
                log('Video element found:', videoElement);

                // Attach event listeners
                videoElement.addEventListener('play', onVideoPlay);
                videoElement.addEventListener('pause', onVideoPause);
                videoElement.addEventListener('ended', onVideoEnd);
                videoElement.addEventListener('timeupdate', onTimeUpdate);

                // Create UI
                createUI();

                // Auto-download funscript
                autoDownloadFunscript();

                // If video is already playing, trigger play event
                if (!videoElement.paused) {
                    onVideoPlay();
                }
            }
        }, 1000);
    }

    function onVideoPlay() {
        log('Video started playing');
        sendToBridge('play');
    }

    function onVideoPause() {
        log('Video paused');
        sendToBridge('pause');
    }

    function onVideoEnd() {
        log('Video ended');
        sendToBridge('pause');
    }

    function onTimeUpdate() {
        if (!videoElement) return;

        // Process video playback position
        const currentTime = videoElement.currentTime;
        const currentTimeMs = currentTime * 1000;

        // Only process if playing
        if (videoElement.paused) return;

        // Try to get intensity from funscript first
        let intensity = getFunscriptIntensity(currentTimeMs);
        
        if (intensity === null) {
            // Fallback to estimated intensity based on current playback position
            intensity = Math.sin(currentTime / 10) * 0.5 + 0.5;
        }

        // Apply user intensity scaling
        intensity = intensity * intensityScale;

        sendToBridge('audio_level', { 
            level: intensity,
            timestamp: currentTimeMs,
            source: funscriptData ? 'funscript' : 'estimated'
        });
    }

    // --------------------------------
    // User Interface
    // --------------------------------

    function createUI() {
        // Create UI container if it doesn't exist
        if (!uiContainer) {
            try {
                uiContainer = document.createElement('div');
                uiContainer.id = 'buttplug-bridge-ui';
                uiContainer.style.cssText = `
                    position: fixed;
                    bottom: 20px;
                    right: 20px;
                    background: rgba(0, 0, 0, 0.8);
                    color: white;
                    padding: 10px;
                    border-radius: 5px;
                    z-index: 9999;
                    font-family: Arial, sans-serif;
                    width: 250px;
                `;

                // Add the UI content with error handling
                try {
                    uiContainer.innerHTML = 
                        '<div style="display: flex; justify-content: space-between; align-items: center;">' +
                            '<h3 style="margin: 0; font-size: 16px;">Buttplug Bridge</h3>' +
                            '<button id="bp-minimize" style="background: none; border: none; color: white; cursor: pointer;">_</button>' +
                        '</div>' +
                        '<hr style="border: 1px solid #333; margin: 5px 0;">' +
                        '<div id="bp-content">' +
                            '<div style="margin-bottom: 10px;">' +
                                '<span id="bp-status" style="font-size: 14px;">Checking connection...</span>' +
                            '</div>' +
                            '<div style="margin-bottom: 10px;">' +
                                '<span id="bp-funscript-status" style="font-size: 12px; display: block;">📜 Auto-loading...</span>' +
                            '</div>' +
                            '<div style="margin-bottom: 10px;">' +
                                '<label for="bp-intensity">Intensity:</label>' +
                                '<input type="range" id="bp-intensity" min="0" max="100" value="50" style="width: 100%;">' +
                                '<span id="bp-intensity-value" style="font-size: 12px;">50%</span>' +
                            '</div>' +
                            '<div style="display: flex; justify-content: space-between;">' +
                                '<button id="bp-refresh" style="padding: 5px 10px; background: #4CAF50; color: white; border: none; border-radius: 3px; cursor: pointer;">Refresh</button>' +
                                '<button id="bp-test" style="padding: 5px 10px; background: #2196F3; color: white; border: none; border-radius: 3px; cursor: pointer;">Test</button>' +
                            '</div>' +
                        '</div>';
                } catch (innerHtmlError) {
                    log('Error setting innerHTML:', innerHtmlError);
                    // Fallback to simple text content
                    uiContainer.textContent = 'Buttplug Bridge - UI Error';
                }

                // Safely append to body with retry logic
                const appendToBody = () => {
                    try {
                        if (document.body) {
                            document.body.appendChild(uiContainer);
                            
                            // Add event listeners to buttons with error handling
                            try {
                                const minimizeBtn = uiContainer.querySelector('#bp-minimize');
                                const refreshBtn = uiContainer.querySelector('#bp-refresh');
                                const testBtn = uiContainer.querySelector('#bp-test');
                                const intensitySlider = uiContainer.querySelector('#bp-intensity');
                                
                                if (minimizeBtn) minimizeBtn.addEventListener('click', toggleUI);
                                if (refreshBtn) refreshBtn.addEventListener('click', handleConnectClick);
                                if (testBtn) testBtn.addEventListener('click', handleTestClick);
                                if (intensitySlider) intensitySlider.addEventListener('input', handleIntensityChange);
                            } catch (eventError) {
                                log('Error adding event listeners:', eventError);
                            }
                        } else {
                            // Retry if body is not ready
                            setTimeout(appendToBody, 100);
                        }
                    } catch (appendError) {
                        log('Error appending UI to body:', appendError);
                        // Try again after a short delay
                        setTimeout(appendToBody, 500);
                    }
                };
                
                appendToBody();
                
            } catch (createError) {
                log('Error creating UI:', createError);
            }
        }
    }

    function createButtplugUI() {
        // Update UI to show connected state
        if (uiContainer) {
            const statusElement = uiContainer.querySelector('#bp-status');
            if (statusElement) {
                if (connected) {
                    statusElement.textContent = '✅ Connected to bridge';
                    statusElement.style.color = '#4CAF50';
                } else {
                    statusElement.textContent = '❌ Bridge not connected';
                    statusElement.style.color = '#F44336';
                }
            }
        }
    }

    let intensityScale = 0.5; // Default 50%

    function handleIntensityChange(e) {
        intensityScale = e.target.value / 100;
        log(`Intensity set to ${intensityScale}`);
        
        // Update intensity display
        const intensityValue = uiContainer.querySelector('#bp-intensity-value');
        if (intensityValue) {
            intensityValue.textContent = `${e.target.value}%`;
        }
    }

    function handleConnectClick() {
        if (!connected) {
            // Check bridge status
            GM_xmlhttpRequest({
                method: 'GET',
                url: `${config.bridgeUrl}/status`,
                onload: function(response) {
                    try {
                        const statusData = JSON.parse(response.responseText);
                        
                        if (statusData.buttplug_connected) {
                            connected = true;
                            createButtplugUI();
                            showNotification(`Bridge connected! Found ${statusData.active_devices} device(s).`);
                        } else {
                            createButtplugUI();
                            showNotification('Bridge found but not connected to Buttplug. Make sure Intiface Central is running.');
                        }
                    } catch (parseError) {
                        showNotification('Error parsing bridge status response');
                    }
                },
                onerror: function(error) {
                    showNotification('Bridge server not found. Make sure it\'s running on localhost:8080');
                }
            });
        } else {
            // Refresh status
            initialize();
        }
    }

    async function handleTestClick() {
        if (connected) {
            sendToBridge('test', { intensity: 'medium' });
            showNotification('Test signal sent to bridge');
        } else {
            showNotification('Bridge not connected. Make sure bridge server is running.');
        }
    }

    let minimized = false;

    function toggleUI() {
        const content = uiContainer.querySelector('#bp-content');
        const minButton = uiContainer.querySelector('#bp-minimize');

        minimized = !minimized;

        if (minimized) {
            content.style.display = 'none';
            minButton.textContent = '+';
        } else {
            content.style.display = 'block';
            minButton.textContent = '_';
        }
    }

    function showNotification(message, duration = 3000) {
        try {
            // Create notification element if it doesn't exist
            let notification = document.getElementById('bp-notification');
            if (!notification) {
                notification = document.createElement('div');
                notification.id = 'bp-notification';
                notification.style.cssText = `
                    position: fixed;
                    top: 20px;
                    right: 20px;
                    background: rgba(0, 0, 0, 0.8);
                    color: white;
                    padding: 10px 20px;
                    border-radius: 5px;
                    z-index: 10000;
                    font-family: Arial, sans-serif;
                    transition: opacity 0.3s ease;
                `;
                
                // Safely append to body
                try {
                    if (document.body) {
                        document.body.appendChild(notification);
                    } else {
                        // Wait for body to be available
                        setTimeout(() => showNotification(message, duration), 100);
                        return;
                    }
                } catch (appendError) {
                    log('Error appending notification:', appendError);
                    return;
                }
            }

            // Show notification
            notification.textContent = message;
            notification.style.opacity = '1';

            // Hide after duration
            setTimeout(() => {
                try {
                    notification.style.opacity = '0';
                } catch (hideError) {
                    log('Error hiding notification:', hideError);
                }
            }, duration);
        } catch (notificationError) {
            log('Error creating notification:', notificationError);
            // Fallback to console log
            console.log('[AT-BP Bridge] Notification:', message);
        }
    }

    // --------------------------------
    // Initialization
    // --------------------------------

    function initialize() {
        log('Initializing Adult Time to Buttplug bridge...');

        // Setup video detection and event listeners
        setupVideoEventListeners();

        // Always use bridge mode - direct connection conflicts with bridge server
        GM_xmlhttpRequest({
            method: 'GET',
            url: `${config.bridgeUrl}/status`,
            onload: function(response) {
                try {
                    const data = JSON.parse(response.responseText);
                    log('Bridge status:', data);
                    
                    if (data.buttplug_connected) {
                        connected = true;
                        createUI(); // Create UI since we're connected
                        showNotification(`Bridge connected! Found ${data.active_devices} device(s).`);
                    } else {
                        createUI(); // Create UI even if not connected so user can see status
                        showNotification('Bridge found but not connected to Buttplug. Make sure Intiface Central is running.');
                    }
                } catch (parseError) {
                    log('Error parsing bridge status:', parseError);
                    createUI(); // Create UI so user can see error status
                    showNotification('Error connecting to bridge server');
                }
            },
            onerror: function(error) {
                log('Bridge not available:', error);
                createUI(); // Create UI so user can see error status
                showNotification('Bridge server not found. Make sure it\'s running on localhost:8080');
            }
        });
    }

    // Check if we're on the Adult Time website and prevent multiple instances
    if ((window.location.hostname.includes('adulttime') ||
         window.location.hostname.includes('adultempire')) &&
        !window.buttplugBridgeLoaded) {
        
        // Mark as loaded to prevent multiple instances
        window.buttplugBridgeLoaded = true;
        
        log('Adult Time website detected');

        // Wait for page to load fully
        if (document.readyState === 'complete') {
            initialize();
        } else {
            window.addEventListener('load', initialize);
        }
    } else if (window.buttplugBridgeLoaded) {
        log('Buttplug bridge already loaded, skipping initialization');
    }
})();