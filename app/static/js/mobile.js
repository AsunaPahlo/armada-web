// Armada Mobile PWA JavaScript
(function() {
    'use strict';

    // ========================================
    // Service Worker Registration
    // ========================================
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', async () => {
            try {
                const registration = await navigator.serviceWorker.register('/static/sw.js');
                console.log('[PWA] Service Worker registered:', registration.scope);
            } catch (error) {
                console.error('[PWA] Service Worker registration failed:', error);
            }
        });
    }

    // ========================================
    // Install Prompt
    // ========================================
    let deferredPrompt = null;

    window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault();
        deferredPrompt = e;
        showInstallPrompt();
    });

    function showInstallPrompt() {
        const prompt = document.getElementById('install-prompt');
        if (prompt && !localStorage.getItem('installPromptDismissed')) {
            prompt.classList.add('visible');
        }
    }

    window.installApp = async function() {
        if (!deferredPrompt) return;

        deferredPrompt.prompt();
        const { outcome } = await deferredPrompt.userChoice;

        if (outcome === 'accepted') {
            console.log('[PWA] App installed');
            showToast('App installed successfully!', 'success');
        }

        deferredPrompt = null;
        hideInstallPrompt();
    };

    window.dismissInstallPrompt = function() {
        localStorage.setItem('installPromptDismissed', 'true');
        hideInstallPrompt();
    };

    function hideInstallPrompt() {
        const prompt = document.getElementById('install-prompt');
        if (prompt) {
            prompt.classList.remove('visible');
        }
    }

    // ========================================
    // WebSocket Connection
    // ========================================
    let socket = null;
    let reconnectAttempts = 0;
    const maxReconnectAttempts = 5;

    function initWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}`;

        socket = io(wsUrl, {
            transports: ['websocket', 'polling'],
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionDelayMax: 5000,
            reconnectionAttempts: maxReconnectAttempts
        });

        socket.on('connect', () => {
            console.log('[WS] Connected');
            reconnectAttempts = 0;
            updateConnectionStatus(true);
            hideOfflineBanner();
        });

        socket.on('disconnect', () => {
            console.log('[WS] Disconnected');
            updateConnectionStatus(false);
        });

        socket.on('connect_error', (error) => {
            console.error('[WS] Connection error:', error);
            reconnectAttempts++;
            if (reconnectAttempts >= maxReconnectAttempts) {
                showOfflineBanner();
            }
        });

        socket.on('fleet_update', (data) => {
            console.log('[WS] Fleet update received');
            updateFleetData(data);
        });

        socket.on('submarine_ready', (data) => {
            showToast(`${data.submarine_name} is ready!`, 'success');
            triggerHaptic('success');
        });
    }

    function updateConnectionStatus(connected) {
        const dot = document.querySelector('.connection-dot');
        if (dot) {
            dot.classList.toggle('connected', connected);
            dot.classList.toggle('disconnected', !connected);
        }
    }

    // ========================================
    // Offline/Online Detection
    // ========================================
    function showOfflineBanner() {
        const banner = document.getElementById('offline-banner');
        if (banner) {
            banner.classList.add('visible');
        }
    }

    function hideOfflineBanner() {
        const banner = document.getElementById('offline-banner');
        if (banner) {
            banner.classList.remove('visible');
        }
    }

    window.addEventListener('online', () => {
        hideOfflineBanner();
        showToast('Back online', 'success');
    });

    window.addEventListener('offline', () => {
        showOfflineBanner();
        showToast('You are offline', 'warning');
    });

    // ========================================
    // Toast Notifications
    // ========================================
    window.showToast = function(message, type = 'info') {
        const container = document.getElementById('toast-container') || createToastContainer();

        const toast = document.createElement('div');
        toast.className = `mobile-toast ${type}`;
        toast.innerHTML = `
            <i class="bi bi-${type === 'success' ? 'check-circle' : type === 'warning' ? 'exclamation-triangle' : 'info-circle'}"></i>
            <span>${message}</span>
        `;

        container.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(-20px)';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    };

    function createToastContainer() {
        const container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
        return container;
    }

    // ========================================
    // Haptic Feedback
    // ========================================
    function triggerHaptic(type = 'light') {
        if ('vibrate' in navigator) {
            const patterns = {
                light: [10],
                medium: [20],
                heavy: [30],
                success: [10, 50, 10],
                error: [50, 50, 50]
            };
            navigator.vibrate(patterns[type] || patterns.light);
        }
    }

    // ========================================
    // Pull to Refresh
    // ========================================
    let touchStartY = 0;
    let touchEndY = 0;
    let isPulling = false;

    document.addEventListener('touchstart', (e) => {
        if (window.scrollY === 0) {
            touchStartY = e.touches[0].clientY;
            isPulling = true;
        }
    }, { passive: true });

    document.addEventListener('touchmove', (e) => {
        if (!isPulling) return;

        touchEndY = e.touches[0].clientY;
        const pullDistance = touchEndY - touchStartY;

        if (pullDistance > 50 && window.scrollY === 0) {
            const indicator = document.getElementById('pull-indicator');
            if (indicator) {
                indicator.classList.add('visible');
            }
        }
    }, { passive: true });

    document.addEventListener('touchend', () => {
        if (!isPulling) return;

        const pullDistance = touchEndY - touchStartY;

        if (pullDistance > 100 && window.scrollY === 0) {
            triggerHaptic('medium');
            refreshData();
        }

        const indicator = document.getElementById('pull-indicator');
        if (indicator) {
            indicator.classList.remove('visible');
        }

        isPulling = false;
        touchStartY = 0;
        touchEndY = 0;
    });

    // ========================================
    // Data Loading & Rendering
    // ========================================
    let fleetData = null;

    async function loadFleetData() {
        try {
            const response = await fetch('/m/api/fleet');
            if (!response.ok) throw new Error('Failed to load fleet data');
            fleetData = await response.json();
            renderDashboard();
        } catch (error) {
            console.error('[Data] Load error:', error);
            showToast('Failed to load data', 'error');
        }
    }

    async function refreshData() {
        const indicator = document.getElementById('pull-indicator');
        if (indicator) {
            indicator.textContent = 'Refreshing...';
            indicator.classList.add('visible');
        }

        await loadFleetData();

        if (indicator) {
            indicator.classList.remove('visible');
            indicator.textContent = 'Pull to refresh';
        }

        showToast('Data refreshed', 'success');
    }

    function updateFleetData(data) {
        fleetData = data;
        renderDashboard();
    }

    let currentFCFilter = 'all';

    function renderDashboard() {
        if (!fleetData) return;

        // Update stats
        const totalSubs = fleetData.total_submarines || 0;
        const readySubs = fleetData.ready_submarines || 0;
        const soonSubs = fleetData.soon_submarines || 0;
        const totalFCs = fleetData.total_fcs || 0;

        updateStat('stat-total', totalSubs);
        updateStat('stat-ready', readySubs, readySubs > 0 ? 'ready' : '');
        updateStat('stat-soon', soonSubs, soonSubs > 0 ? 'soon' : '');
        updateStat('stat-fcs', totalFCs);

        // Render FC cards with current filter
        renderFCList(fleetData.fcs || [], currentFCFilter);

        // Initialize FC filters (once)
        initFCFilters();
    }

    function initFCFilters() {
        const filterContainer = document.getElementById('fc-filters');
        if (!filterContainer || filterContainer.dataset.initialized) return;

        filterContainer.dataset.initialized = 'true';
        const pills = filterContainer.querySelectorAll('.filter-pill');

        pills.forEach(pill => {
            pill.addEventListener('click', (e) => {
                e.preventDefault();
                pills.forEach(p => p.classList.remove('active'));
                pill.classList.add('active');
                currentFCFilter = pill.dataset.filter;
                triggerHaptic('light');
                renderFCList(fleetData.fcs || [], currentFCFilter);
            });
        });
    }

    function updateStat(id, value, className = '') {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = value;
            el.className = 'stat-card-value ' + className;
        }
    }

    function renderFCList(fcs, filter = 'all') {
        const container = document.getElementById('fc-list');
        if (!container) return;

        // Apply filter
        let filtered = fcs;
        if (filter === 'ready') {
            filtered = fcs.filter(fc => fc.ready_subs > 0);
        } else if (filter === 'soon') {
            filtered = fcs.filter(fc => {
                // FC has submarines returning within 30 min but none ready
                return fc.ready_subs === 0 && fc.soonest_return !== null && fc.soonest_return > 0 && fc.soonest_return <= 0.5;
            });
        } else if (filter === 'voyaging') {
            filtered = fcs.filter(fc => {
                // FC has no ready subs and soonest return is > 30 min
                return fc.ready_subs === 0 && (fc.soonest_return === null || fc.soonest_return > 0.5);
            });
        }

        if (filtered.length === 0) {
            let emptyMessage = 'No Free Companies';
            let emptyDesc = 'Connect the plugin to see your fleet';

            if (filter === 'ready') {
                emptyMessage = 'No Ready Submarines';
                emptyDesc = 'All submarines are currently voyaging';
            } else if (filter === 'soon') {
                emptyMessage = 'None Returning Soon';
                emptyDesc = 'No submarines returning within 30 minutes';
            } else if (filter === 'voyaging') {
                emptyMessage = 'None Voyaging';
                emptyDesc = 'All submarines have returned';
            }

            container.innerHTML = `
                <div class="empty-state">
                    <i class="bi bi-${filter === 'all' ? 'inbox' : 'search'}"></i>
                    <div class="empty-state-title">${emptyMessage}</div>
                    <p>${emptyDesc}</p>
                </div>
            `;
            return;
        }

        // Sort by ready subs, then by soonest return
        filtered.sort((a, b) => {
            if (a.ready_subs !== b.ready_subs) return b.ready_subs - a.ready_subs;
            return (a.soonest_return || 999) - (b.soonest_return || 999);
        });

        container.innerHTML = filtered.map(fc => renderFCCard(fc)).join('');
    }

    function renderFCCard(fc) {
        const hasReady = fc.ready_subs > 0;
        const hasSoon = !hasReady && fc.soonest_return !== null && fc.soonest_return <= 0.5;
        const subs = fc.submarines || [];

        let cardClass = 'fc-card';
        if (hasReady) cardClass += ' has-ready';
        else if (hasSoon) cardClass += ' has-soon';

        let countdownText = '--:--';
        let countdownClass = '';

        if (hasReady) {
            countdownText = 'READY';
            countdownClass = 'ready';
        } else if (fc.soonest_return !== null) {
            if (fc.soonest_return <= 0) {
                countdownText = 'READY';
                countdownClass = 'ready';
            } else {
                countdownText = formatCountdown(fc.soonest_return);
                if (fc.soonest_return <= 0.5) countdownClass = 'soon';
            }
        }

        // Render submarine grid (up to 4 subs)
        const subGrid = subs.slice(0, 4).map(sub => {
            let statusClass = '';
            if (sub.hours_remaining <= 0) statusClass = 'ready';
            else if (sub.hours_remaining <= 0.5) statusClass = 'soon';

            const timeText = sub.hours_remaining <= 0 ? 'Ready' : formatCountdown(sub.hours_remaining);

            return `
                <div class="sub-grid-item ${statusClass}">
                    <div class="sub-grid-name">${sub.name}</div>
                    <div class="sub-grid-time">${timeText}</div>
                </div>
            `;
        }).join('');

        // Resources section (if available)
        let resourcesHtml = '';
        if (fc.ceruleum !== undefined || fc.repair_kits !== undefined) {
            const ceruleum = fc.ceruleum || 0;
            const kits = fc.repair_kits || 0;

            // Determine resource status
            const ceruleumClass = ceruleum < 200 ? 'critical' : ceruleum < 600 ? 'low' : '';
            const kitsClass = kits < 100 ? 'critical' : kits < 300 ? 'low' : '';

            resourcesHtml = `
                <div class="fc-resources">
                    <div class="fc-resource ${ceruleumClass}">
                        <i class="bi bi-fuel-pump"></i>
                        <span class="fc-resource-value">${ceruleum.toLocaleString()}</span>
                    </div>
                    <div class="fc-resource ${kitsClass}">
                        <i class="bi bi-wrench"></i>
                        <span class="fc-resource-value">${kits.toLocaleString()}</span>
                    </div>
                </div>
            `;
        }

        return `
            <div class="${cardClass}">
                <div class="fc-card-header">
                    <div class="fc-card-info">
                        <div class="fc-card-name">${fc.name}</div>
                        <div class="fc-card-meta">
                            ${fc.world ? `<span class="fc-card-world"><i class="bi bi-globe"></i> ${fc.world}</span>` : ''}
                            <span class="fc-card-sub-count">${subs.length} submarine${subs.length !== 1 ? 's' : ''}</span>
                        </div>
                    </div>
                    <div class="fc-card-status">
                        <div class="fc-card-countdown ${countdownClass}">${countdownText}</div>
                        ${hasReady ? `<div class="fc-card-ready-badge"><i class="bi bi-check-circle-fill"></i> ${fc.ready_subs} ready</div>` : ''}
                    </div>
                </div>
                <div class="fc-card-body">
                    <div class="sub-grid">${subGrid}</div>
                </div>
                ${resourcesHtml}
            </div>
        `;
    }

    function formatCountdown(hours) {
        if (hours <= 0) return 'Ready';

        const totalMinutes = Math.floor(hours * 60);
        const h = Math.floor(totalMinutes / 60);
        const m = totalMinutes % 60;

        if (h > 0) {
            return `${h}h ${m}m`;
        }
        return `${m}m`;
    }

    // ========================================
    // Submarine List Page
    // ========================================
    window.renderSubmarineList = function(submarines, filter = 'all') {
        const container = document.getElementById('sub-list');
        if (!container) return;

        let filtered = submarines;
        if (filter === 'ready') {
            filtered = submarines.filter(s => s.hours_remaining <= 0);
        } else if (filter === 'soon') {
            filtered = submarines.filter(s => s.hours_remaining > 0 && s.hours_remaining <= 0.5);
        } else if (filter === 'voyaging') {
            filtered = submarines.filter(s => s.hours_remaining > 0.5);
        }

        // Sort by time remaining
        filtered.sort((a, b) => a.hours_remaining - b.hours_remaining);

        if (filtered.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i class="bi bi-search"></i>
                    <div class="empty-state-title">No submarines found</div>
                    <p>Try a different filter</p>
                </div>
            `;
            return;
        }

        container.innerHTML = filtered.map(sub => {
            let itemClass = 'sub-list-item';
            let countdownClass = '';

            if (sub.hours_remaining <= 0) {
                itemClass += ' ready';
                countdownClass = 'ready';
            } else if (sub.hours_remaining <= 0.5) {
                itemClass += ' soon';
                countdownClass = 'soon';
            }

            const countdown = sub.hours_remaining <= 0 ? 'READY' : formatCountdown(sub.hours_remaining);

            return `
                <div class="${itemClass}">
                    <div class="sub-list-info">
                        <div class="sub-list-name">${sub.name}</div>
                        <div class="sub-list-fc">${sub.fc_name}</div>
                        <div class="sub-list-route">${sub.route || 'No route'}</div>
                    </div>
                    <div class="sub-list-status">
                        <div class="sub-list-countdown ${countdownClass}">${countdown}</div>
                        <div class="sub-list-level">Lv. ${sub.level}</div>
                    </div>
                </div>
            `;
        }).join('');
    };

    // ========================================
    // Search Functionality
    // ========================================
    window.initSearch = function(data, renderFn) {
        const searchInput = document.getElementById('search-input');
        if (!searchInput) return;

        let debounceTimer;
        searchInput.addEventListener('input', (e) => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                const query = e.target.value.toLowerCase().trim();
                const filtered = data.filter(item =>
                    item.name?.toLowerCase().includes(query) ||
                    item.fc_name?.toLowerCase().includes(query)
                );
                renderFn(filtered);
            }, 200);
        });
    };

    // ========================================
    // Filter Pills
    // ========================================
    window.initFilters = function(renderFn) {
        const pills = document.querySelectorAll('.filter-pill');
        pills.forEach(pill => {
            pill.addEventListener('click', (e) => {
                e.preventDefault();
                pills.forEach(p => p.classList.remove('active'));
                pill.classList.add('active');
                triggerHaptic('light');
                renderFn(pill.dataset.filter);
            });
        });
    };

    // ========================================
    // Countdown Timer Updates
    // ========================================
    function startCountdownUpdates() {
        setInterval(() => {
            if (fleetData) {
                // Decrement all countdowns
                (fleetData.fcs || []).forEach(fc => {
                    if (fc.soonest_return !== null) {
                        fc.soonest_return -= 1/60; // Subtract 1 minute
                    }
                    (fc.submarines || []).forEach(sub => {
                        if (sub.hours_remaining > 0) {
                            sub.hours_remaining -= 1/60;
                        }
                    });
                });
                renderDashboard();
            }
        }, 60000); // Update every minute
    }

    // ========================================
    // Initialization
    // ========================================
    document.addEventListener('DOMContentLoaded', () => {
        // Initialize WebSocket
        if (typeof io !== 'undefined') {
            initWebSocket();
        }

        // Load initial data
        loadFleetData();

        // Start countdown updates
        startCountdownUpdates();

        // Check if running as installed PWA
        if (window.matchMedia('(display-mode: standalone)').matches) {
            document.body.classList.add('pwa-standalone');
        }
    });

})();
