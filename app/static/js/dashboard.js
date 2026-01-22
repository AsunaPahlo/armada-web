/**
 * Armada Dashboard JavaScript
 * Handles WebSocket connections and real-time updates
 */

class ArmadaDashboard {
    constructor() {
        this.socket = null;
        this.connected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 3000;
        this.timerInterval = null;

        // Sort state for FC table (default: soonest return first)
        this.fcSort = { column: 'return', direction: 'asc' };

        // Pagination state
        this.currentPage = 1;
        this.pageSize = parseInt(localStorage.getItem('armada-page-size') || '10');

        this.init();
    }

    init() {
        this.connectWebSocket();
        // Don't call updateTimers() immediately - let server-rendered values display first
        // Timer updates will start after 1 second via startTimerUpdates()
        this.startTimerUpdates();
        this.updateLastUpdateTime();
        this.fetchPluginStatus();
    }

    async fetchPluginStatus() {
        try {
            const response = await fetch('/api/plugins');
            if (response.ok) {
                const plugins = await response.json();
                this.updatePluginStatus(plugins);
            }
        } catch (error) {
            console.error('[Armada] Failed to fetch plugin status:', error);
        }
    }

    updatePluginStatus(plugins) {
        const countEl = document.getElementById('plugin-count');
        const listEl = document.getElementById('plugin-list');

        if (!listEl) return;

        const canDelete = listEl.dataset.canDelete === 'true';
        const connectedCount = plugins.filter(p => p.connected).length;

        if (countEl) {
            countEl.textContent = `${connectedCount} connected`;
            countEl.className = 'badge ' + (connectedCount > 0 ? 'bg-success' : 'bg-secondary');
        }

        if (plugins.length === 0) {
            const colspan = canDelete ? 4 : 3;
            listEl.innerHTML = `<tr><td colspan="${colspan}" class="text-center text-muted py-4">No clients have connected yet</td></tr>`;
            return;
        }

        listEl.innerHTML = plugins.map(plugin => {
            const actionCol = canDelete
                ? `<td><button class="btn btn-sm btn-outline-danger" onclick="clearClientData('${plugin.plugin_id}')"><i class="bi bi-trash"></i></button></td>`
                : '';
            return `<tr>
                <td>${plugin.connected
                    ? '<span class="badge bg-success">Connected</span>'
                    : '<span class="badge bg-secondary">Disconnected</span>'}</td>
                <td>${plugin.plugin_id}</td>
                <td class="text-muted">${plugin.last_received_at
                    ? this.formatTimestamp(plugin.last_received_at)
                    : 'Never'}</td>
                ${actionCol}
            </tr>`;
        }).join('');
    }

    formatTimestamp(isoString) {
        if (!isoString) return '-';
        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);

        if (diffMins < 1) return 'just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        if (diffHours < 24) return `${diffHours}h ago`;
        return date.toLocaleString();
    }

    connectWebSocket() {
        try {
            this.socket = io({
                transports: ['websocket', 'polling'],
                reconnection: true,
                reconnectionAttempts: this.maxReconnectAttempts,
                reconnectionDelay: this.reconnectDelay
            });

            this.socket.on('connect', () => {
                console.log('[Armada] WebSocket connected');
                this.connected = true;
                this.reconnectAttempts = 0;
                this.updateConnectionStatus(true);
                // Don't request_update on connect - page already has fresh server-rendered data
                // Updates will be pushed via WebSocket when data changes
            });

            this.socket.on('disconnect', () => {
                console.log('[Armada] WebSocket disconnected');
                this.connected = false;
                this.updateConnectionStatus(false);
            });

            this.socket.on('connect_error', (error) => {
                console.error('[Armada] Connection error:', error);
                this.reconnectAttempts++;
                this.updateConnectionStatus(false);
            });

            this.socket.on('dashboard_update', (data) => {
                console.log('[Armada] Received dashboard update:', {
                    summary: data.summary,
                    fc_count: data.fc_summaries ? data.fc_summaries.length : 0,
                    sub_count: data.submarines ? data.submarines.length : 0
                });
                this.updateDashboard(data);
            });

            this.socket.on('plugin_data_update', (data) => {
                console.log('[Armada] Plugin data received from:', data.plugin_id, '- accounts:', data.account_count);
                // Refresh plugin status when data is received
                this.fetchPluginStatus();
            });

            this.socket.on('plugin_connected', (data) => {
                console.log('[Armada] Plugin connected:', data.plugin_id);
                this.fetchPluginStatus();
            });

            this.socket.on('plugin_disconnected', (data) => {
                console.log('[Armada] Plugin disconnected:', data.plugin_id);
                this.fetchPluginStatus();
            });

            this.socket.on('fc_update', (fcData) => {
                console.log('[Armada] Received FC update:', fcData.fc_name);
                this.updateFCCard(fcData);
            });

            this.socket.on('alert', (data) => {
                console.log('[Armada] Alert received:', data);
                // Refresh the alert bell in navbar
                if (typeof loadAlertDropdown === 'function') {
                    loadAlertDropdown();
                }
            });

        } catch (error) {
            console.error('[Armada] Failed to initialize WebSocket:', error);
        }
    }

    updateConnectionStatus(connected) {
        const indicator = document.getElementById('connection-status');

        if (indicator) {
            indicator.className = 'connection-dot ' + (connected ? 'connected' : 'disconnected');
            indicator.innerHTML = connected
                ? '<i class="bi bi-circle-fill"></i>'
                : '<i class="bi bi-circle"></i>';
            indicator.title = connected ? 'Connected' : 'Disconnected';
        }
    }

    updateDashboard(data) {
        // Only update on dashboard page
        if (!document.getElementById('fc-table') && !document.getElementById('fc-cards')) {
            return;
        }

        // Update summary cards
        if (data.summary) {
            this.updateElement('total-subs', data.summary.total_subs);
            this.updateElement('ready-subs', data.summary.ready_subs);
            this.updateElement('voyaging-subs', data.summary.voyaging_subs);
            this.updateElement('leveling-subs', data.summary.leveling_subs);
            this.updateElement('leveling-subs-top', data.summary.leveling_subs);
            this.updateElement('gil-per-day', this.formatNumber(data.summary.total_gil_per_day));
        }

        // Update supply forecast
        if (data.supply_forecast) {
            this.updateSupplyForecast(data.supply_forecast);
        }

        // Update FC summaries (table and cards)
        // Note: FC count badge is updated by applyTagFilter after fc-table-updated event
        if (data.fc_summaries) {
            this.updateFCTable(data.fc_summaries);
            this.updateFCCards(data.fc_summaries);
        }

        // Update last update time
        this.updateLastUpdateTime();

        // Update submarine table if present
        if (data.submarines && document.getElementById('upcoming-table')) {
            this.updateSubmarineTable(data.submarines);
        }
    }

    updateSupplyForecast(forecast) {
        // Update supply values
        this.updateElement('total-ceruleum', this.formatNumber(forecast.total_ceruleum || 0));
        this.updateElement('total-repair-kits', this.formatNumber(forecast.total_repair_kits || 0));
        this.updateElement('ceruleum-per-day', forecast.ceruleum_per_day || 0);
        this.updateElement('kits-per-day', forecast.kits_per_day || 0);

        // Update days until restock with color coding
        const daysEl = document.getElementById('days-until-restock');
        const limitingEl = document.getElementById('limiting-info');

        if (daysEl) {
            const days = forecast.days_until_restock;
            if (days === null || days === undefined || days >= 999) {
                daysEl.textContent = '-';
                daysEl.className = 'text-success fs-5';
                if (limitingEl) {
                    limitingEl.textContent = 'No data';
                    limitingEl.className = 'text-muted d-block';
                }
            } else {
                daysEl.textContent = days;
                if (days < 7) {
                    daysEl.className = 'text-danger fs-5';
                    if (limitingEl) limitingEl.className = 'text-danger d-block';
                } else if (days < 14) {
                    daysEl.className = 'text-warning fs-5';
                    if (limitingEl) limitingEl.className = 'text-muted d-block';
                } else {
                    daysEl.className = 'text-success fs-5';
                    if (limitingEl) limitingEl.className = 'text-muted d-block';
                }

                if (limitingEl && forecast.limiting_fc) {
                    limitingEl.textContent = `${forecast.limiting_fc} (${forecast.limiting_resource || 'unknown'})`;
                }
            }
        }
    }

    updateFCTable(fcSummaries) {
        const tbody = document.querySelector('#fc-table tbody');
        if (!tbody) return;

        // Preserve expanded row state
        const expandedFCs = new Set();
        document.querySelectorAll('.fc-row.expanded').forEach(row => {
            expandedFCs.add(row.dataset.fcId);
        });

        // Sort using current sort state
        const sorted = this.sortFCData(fcSummaries);

        tbody.innerHTML = sorted.map(fc => {
            const fcIdStr = String(fc.fc_id);
            const isExpanded = expandedFCs.has(fcIdStr);
            const tagIds = (fc.tags || []).map(t => t.id).join(',');
            const tagNames = (fc.tags || []).map(t => t.name).join(' ');
            // Determine row highlight class: has-ready takes priority, then has-soon for subs within 30 min
            const highlightClass = fc.ready_subs > 0 ? 'has-ready' : (fc.soonest_return !== null && fc.soonest_return <= 0.5 ? 'has-soon' : '');
            return `
            <tr class="fc-row ${highlightClass} ${isExpanded ? 'expanded' : ''}"
                data-fc-id="${fcIdStr}"
                data-fc="${fc.fc_name || ''}"
                data-subs="${fc.total_subs}"
                data-ready="${fc.ready_subs}"
                data-return="${fc.soonest_return !== null ? fc.soonest_return : 9999}"
                data-gil="${fc.gil_per_day}"
                data-restock="${fc.days_until_restock !== null ? fc.days_until_restock : 9999}"
                data-mode="${fc.mode || ''}"
                data-character="${fc.unified_character || ''}"
                data-tags="${tagIds}"
                data-tag-names="${tagNames}"
                data-accounts="${fc.accounts ? fc.accounts.join(' ') : ''}">
                <td class="expand-toggle" style="cursor: pointer;">
                    <i class="bi ${isExpanded ? 'bi-chevron-down' : 'bi-chevron-right'}"></i>
                </td>
                <td>
                    <strong>${fc.fc_name || 'Unknown FC'}</strong>
                    ${fc.house_address ? `<i class="bi bi-house-door-fill text-info ms-1" data-bs-toggle="tooltip" data-bs-placement="top" title="${fc.house_address}"></i>` : ''}
                    <a href="/unlocks?fc_id=${fcIdStr}" class="text-decoration-none ms-1" data-bs-toggle="tooltip" data-bs-placement="top" title="View Sector Unlocks">
                        <i class="bi bi-diagram-3 text-muted unlock-link-icon"></i>
                    </a>
                    ${(fc.tags || []).map(t => `<span class="badge bg-${t.color} ms-1 fc-tag-badge">${t.name}</span>`).join('')}
                    ${(fc.routes || []).map(r => `<span class="badge bg-dark ms-1">${r}</span>`).join('')}
                    <br><small class="text-muted">${fc.accounts ? fc.accounts.join(', ') : ''}</small>
                </td>
                <td>
                    ${fc.unified_character || '<span class="text-muted">-</span>'}
                </td>
                <td class="text-center">
                    <span class="badge bg-secondary">${fc.total_subs}</span>
                </td>
                <td class="text-center">
                    ${fc.ready_subs > 0
                        ? `<span class="badge bg-success">${fc.ready_subs}</span>`
                        : '<span class="text-muted">0</span>'}
                </td>
                <td class="text-center">
                    ${this.formatFCMode(fc.mode)}
                </td>
                <td class="text-end">
                    ${this.formatReturnTime(fc.soonest_return, fc.soonest_return_time)}
                </td>
                <td class="text-end text-warning">${this.formatNumber(fc.gil_per_day)}</td>
                <td class="text-center">
                    <small>
                        <span class="text-info" title="Ceruleum">${fc.ceruleum}</span>
                        /
                        <span class="text-info" title="Repair Kits">${fc.repair_kits}</span>
                    </small>
                </td>
                <td class="text-center">
                    ${this.formatRestockDays(fc.days_until_restock, fc.limiting_resource)}
                </td>
            </tr>
            <!-- Expandable Detail Row -->
            <tr class="fc-detail-row" data-fc-id="${fcIdStr}" style="display: ${isExpanded ? 'table-row' : 'none'};">
                <td colspan="10" class="p-0">
                    <div class="fc-detail-content">
                        <table class="table table-sm table-dark mb-0 sub-table" style="table-layout: fixed;">
                            <thead>
                                <tr class="text-muted">
                                    <th style="padding-left: 40px; width: 18%;">Submarine</th>
                                    <th style="width: 25%;">Character</th>
                                    <th style="width: 12%;">Build</th>
                                    <th style="width: 20%;">Route</th>
                                    <th class="text-center" style="width: 10%;">Level</th>
                                    <th class="text-end" style="width: 15%;">Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${this.renderFCSubmarines(fc.submarines)}
                            </tbody>
                        </table>
                    </div>
                </td>
            </tr>
        `}).join('');

        // Re-attach click handlers for expandable rows
        this.attachFCRowHandlers();

        // Apply pagination
        this.applyPagination();

        // Re-initialize Bootstrap tooltips
        this.initTooltips();

        // Dispatch event for tag filter reapplication
        document.dispatchEvent(new CustomEvent('fc-table-updated'));
    }

    initTooltips() {
        // Initialize Bootstrap tooltips for newly added elements
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.forEach(function (tooltipTriggerEl) {
            // Dispose existing tooltip if any
            const existingTooltip = bootstrap.Tooltip.getInstance(tooltipTriggerEl);
            if (existingTooltip) {
                existingTooltip.dispose();
            }
            new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }

    renderFCSubmarines(submarines) {
        if (!submarines || submarines.length === 0) {
            return '<tr><td colspan="6" class="text-muted text-center">No submarines</td></tr>';
        }

        // Sort by hours remaining
        const sorted = [...submarines].sort((a, b) => a.hours_remaining - b.hours_remaining);

        return sorted.map(sub => `
            <tr class="${sub.status === 'ready' ? 'sub-ready' : sub.status === 'returning_soon' ? 'sub-soon' : ''}">
                <td style="padding-left: 40px;">
                    <strong>${sub.name}</strong>
                </td>
                <td>
                    ${sub.character}
                    <small class="text-muted">@ ${sub.world}</small>
                </td>
                <td><code>${sub.build || '-'}</code></td>
                <td>${sub.route || '-'}</td>
                <td class="text-center">
                    ${sub.level}
                    ${sub.exp_progress > 0 ? `
                        <div class="progress exp-bar-mini mt-1">
                            <div class="progress-bar bg-info" style="width: ${sub.exp_progress}%"></div>
                        </div>
                    ` : ''}
                </td>
                <td class="text-end">
                    ${this.formatSubStatus(sub)}
                </td>
            </tr>
        `).join('');
    }

    formatReturnTime(hours, returnTime) {
        if (hours === null || hours === undefined) {
            return '<span class="text-muted">-</span>';
        }
        if (hours <= 0) {
            return '<span class="badge bg-success" data-state="ready">READY</span>';
        }
        const dataAttr = returnTime ? ` data-return="${returnTime}"` : '';
        if (hours <= 0.5) {
            return `<span class="badge bg-warning text-dark timer-countdown"${dataAttr} data-state="warning"><i class="bi bi-hourglass-split"></i> ${Math.round(hours * 60)}m</span>`;
        }
        if (hours < 1) {
            return `<span class="timer-countdown text-muted"${dataAttr} data-state="normal"><i class="bi bi-clock"></i> ${Math.round(hours * 60)}m</span>`;
        }
        return `<span class="timer-countdown text-muted"${dataAttr} data-state="normal"><i class="bi bi-clock"></i> ${hours.toFixed(1)}h</span>`;
    }

    formatRestockDays(days, resource) {
        if (days === null || days === undefined) {
            return '<span class="text-muted">-</span>';
        }
        const cls = days < 7 ? 'text-danger' : days < 14 ? 'text-warning' : 'text-success';
        return `<span class="${cls}" title="${resource || ''}">${days}d</span>`;
    }

    formatFCMode(mode) {
        switch (mode) {
            case 'farming':
                return '<span class="badge bg-warning text-dark">Farming</span>';
            case 'leveling':
                return '<span class="badge bg-purple">Leveling</span>';
            case 'mixed':
                return '<span class="badge bg-info">Mixed</span>';
            default:
                return '<span class="text-muted">-</span>';
        }
    }

    formatSubStatus(sub) {
        if (sub.status === 'ready') {
            return '<span class="badge bg-success" data-state="ready">READY</span>';
        }
        const dataAttr = sub.return_time ? ` data-return="${sub.return_time}"` : '';
        if (sub.status === 'returning_soon' || sub.hours_remaining <= 0.5) {
            return `<span class="badge bg-warning text-dark timer-countdown"${dataAttr} data-state="warning"><i class="bi bi-hourglass-split"></i> ${Math.round(sub.hours_remaining * 60)}m</span>`;
        }
        if (sub.hours_remaining < 1) {
            return `<span class="timer-countdown text-muted"${dataAttr} data-state="normal"><i class="bi bi-clock"></i> ${Math.round(sub.hours_remaining * 60)}m</span>`;
        }
        return `<span class="timer-countdown text-muted"${dataAttr} data-state="normal"><i class="bi bi-clock"></i> ${sub.hours_remaining.toFixed(1)}h</span>`;
    }

    attachFCRowHandlers() {
        document.querySelectorAll('.fc-row').forEach(row => {
            row.addEventListener('click', (e) => {
                if (e.target.closest('a')) return;

                const fcId = row.dataset.fcId;
                const detailRow = document.querySelector(`.fc-detail-row[data-fc-id="${fcId}"]`);

                if (detailRow) {
                    const isExpanded = detailRow.style.display !== 'none';
                    detailRow.style.display = isExpanded ? 'none' : 'table-row';
                    row.classList.toggle('expanded', !isExpanded);

                    // Toggle chevron icon
                    const icon = row.querySelector('.expand-toggle i');
                    if (icon) {
                        icon.classList.toggle('bi-chevron-right', isExpanded);
                        icon.classList.toggle('bi-chevron-down', !isExpanded);
                    }
                }
            });
        });
    }

    sortFCData(fcSummaries) {
        const columnMap = {
            'fc': 'fc_name',
            'character': 'unified_character',
            'subs': 'total_subs',
            'ready': 'ready_subs',
            'mode': 'mode',
            'return': 'soonest_return',
            'gil': 'gil_per_day',
            'restock': 'days_until_restock'
        };
        const numericColumns = ['subs', 'ready', 'return', 'gil', 'restock'];
        const field = columnMap[this.fcSort.column] || 'ready_subs';
        const isNumeric = numericColumns.includes(this.fcSort.column);

        return [...fcSummaries].sort((a, b) => {
            let aVal = a[field];
            let bVal = b[field];

            // Handle null/undefined for numeric sorts
            if (isNumeric) {
                aVal = aVal ?? 9999;
                bVal = bVal ?? 9999;
                return this.fcSort.direction === 'asc' ? aVal - bVal : bVal - aVal;
            } else {
                aVal = (aVal || '').toLowerCase();
                bVal = (bVal || '').toLowerCase();
                return this.fcSort.direction === 'asc'
                    ? aVal.localeCompare(bVal)
                    : bVal.localeCompare(aVal);
            }
        });
    }

    setFCSort(column, direction) {
        this.fcSort.column = column;
        this.fcSort.direction = direction;
    }

    updateFCCards(fcSummaries) {
        const cardsContainer = document.getElementById('fc-cards');
        if (!cardsContainer) return;

        // Sort by soonest return ascending (null values last)
        const sorted = [...fcSummaries].sort((a, b) => {
            const aVal = a.soonest_return ?? 9999;
            const bVal = b.soonest_return ?? 9999;
            return aVal - bVal;
        });

        cardsContainer.innerHTML = sorted.map(fc => {
            const fcIdStr = String(fc.fc_id);
            const tagIds = (fc.tags || []).map(t => t.id).join(',');
            const tagNames = (fc.tags || []).map(t => t.name).join(' ');
            const charNames = (fc.characters || []).map(c => c.name).join(' ');
            return `
            <div class="col-lg-6 col-xl-4 mb-4 fc-card-wrapper" data-tags="${tagIds}" data-tag-names="${tagNames}" data-characters="${charNames}" data-accounts="${fc.accounts ? fc.accounts.join(' ') : ''}">
                <div class="card fc-card" data-fc-id="${fcIdStr}">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <div>
                            <h5 class="mb-0">
                                <i class="bi bi-building"></i>
                                ${fc.fc_name || 'Unknown FC'}
                                ${fc.house_address ? `<i class="bi bi-house-door-fill text-info ms-1" style="font-size: 0.8em;" data-bs-toggle="tooltip" data-bs-placement="top" title="${fc.house_address}"></i>` : ''}
                                <a href="/unlocks?fc_id=${fcIdStr}" class="text-decoration-none ms-1" data-bs-toggle="tooltip" data-bs-placement="top" title="View Sector Unlocks">
                                    <i class="bi bi-diagram-3 text-muted unlock-link-icon" style="font-size: 0.8em;"></i>
                                </a>
                                ${(fc.tags || []).map(t => `<span class="badge bg-${t.color} ms-1 fc-tag-badge">${t.name}</span>`).join('')}
                                ${(fc.routes || []).map(r => `<span class="badge bg-dark ms-1">${r}</span>`).join('')}
                            </h5>
                            <small class="text-muted">${fc.accounts ? fc.accounts.join(', ') : ''}</small>
                        </div>
                        <div class="text-end">
                            <span class="badge ${fc.ready_subs > 0 ? 'bg-success' : 'bg-secondary'}">
                                ${fc.ready_subs}/${fc.total_subs} Ready
                            </span>
                        </div>
                    </div>
                    <div class="card-body">
                        <!-- FC Stats Row -->
                        <div class="row mb-3 fc-stats">
                            <div class="col-4 text-center">
                                <small class="text-muted d-block">Estimated Gil/Day</small>
                                <strong class="text-warning">${this.formatNumber(fc.gil_per_day)}</strong>
                            </div>
                            <div class="col-4 text-center">
                                <small class="text-muted d-block">Ceruleum</small>
                                <strong class="text-info">${this.formatNumber(fc.ceruleum)}</strong>
                            </div>
                            <div class="col-4 text-center">
                                <small class="text-muted d-block">Repair Kits</small>
                                <strong class="text-info">${this.formatNumber(fc.repair_kits)}</strong>
                            </div>
                        </div>

                        <!-- Submarines List -->
                        <div class="submarine-list">
                            ${this.renderCardSubmarines(fc.submarines)}
                        </div>
                    </div>
                    <div class="card-footer">
                        ${fc.soonest_return && fc.soonest_return > 0 ? `
                            <small class="text-muted float-end">
                                Next return: ${fc.soonest_return <= 0.5
                                    ? `<span class="badge bg-warning text-dark timer-countdown" data-return="${fc.soonest_return_time}" data-state="warning"><i class="bi bi-hourglass-split"></i> ${Math.round(fc.soonest_return * 60)}m</span>`
                                    : fc.soonest_return < 1
                                        ? `<span class="timer-countdown text-muted" data-return="${fc.soonest_return_time}" data-state="normal"><i class="bi bi-clock"></i> ${Math.round(fc.soonest_return * 60)}m</span>`
                                        : `<span class="timer-countdown text-muted" data-return="${fc.soonest_return_time}" data-state="normal"><i class="bi bi-clock"></i> ${fc.soonest_return.toFixed(1)}h</span>`
                                }
                            </small>
                        ` : ''}
                    </div>
                </div>
            </div>
        `}).join('');

        // Apply pagination
        this.applyPagination();

        // Re-initialize Bootstrap tooltips
        this.initTooltips();

        // Dispatch event for tag filter reapplication
        document.dispatchEvent(new CustomEvent('fc-cards-updated'));
    }

    renderCardSubmarines(submarines) {
        if (!submarines || submarines.length === 0) {
            return '<div class="text-muted text-center py-2">No submarines</div>';
        }

        // Sort by hours remaining
        const sorted = [...submarines].sort((a, b) => a.hours_remaining - b.hours_remaining);

        return sorted.map(sub => `
            <div class="submarine-row ${sub.status === 'ready' ? 'ready' : sub.status === 'returning_soon' ? 'soon' : ''}">
                <div class="d-flex justify-content-between align-items-center">
                    <div class="sub-info">
                        <span class="sub-name">${sub.name}</span>
                        <span class="sub-build badge bg-dark">${sub.build || '?'}</span>
                        ${sub.route ? `<span class="sub-route badge bg-secondary">${sub.route}</span>` : ''}
                    </div>
                    <div class="sub-timer text-end">
                        ${sub.status === 'ready'
                            ? '<span class="text-success fw-bold" data-state="ready"><i class="bi bi-check-circle-fill"></i> READY</span>'
                            : sub.hours_remaining <= 0.5
                                ? `<span class="badge bg-warning text-dark timer-countdown" data-return="${sub.return_time}" data-state="warning"><i class="bi bi-hourglass-split"></i> ${Math.round(sub.hours_remaining * 60)}m</span>`
                                : sub.hours_remaining < 1
                                    ? `<span class="text-muted timer-countdown" data-return="${sub.return_time}" data-state="normal"><i class="bi bi-clock"></i> ${Math.round(sub.hours_remaining * 60)}m</span>`
                                    : `<span class="text-muted timer-countdown" data-return="${sub.return_time}" data-state="normal"><i class="bi bi-clock"></i> ${sub.hours_remaining.toFixed(1)}h</span>`
                        }
                    </div>
                </div>
                <div class="sub-details">
                    <small class="text-muted">
                        Lv.${sub.level} | ${sub.character} @ ${sub.world}
                    </small>
                    ${sub.exp_progress > 0 ? `
                        <div class="progress exp-bar mt-1">
                            <div class="progress-bar bg-info" style="width: ${sub.exp_progress}%"></div>
                        </div>
                    ` : ''}
                </div>
            </div>
        `).join('');
    }

    updateFCCard(fcData) {
        const card = document.querySelector(`[data-fc-id="${fcData.fc_id}"]`);
        if (!card) return;

        // Update ready count badge
        const badge = card.querySelector('.badge');
        if (badge) {
            badge.textContent = `${fcData.ready_subs}/${fcData.total_subs} Ready`;
            badge.className = 'badge ' + (fcData.ready_subs > 0 ? 'bg-success' : 'bg-secondary');
        }

        // Could update submarine list here if needed
    }

    updateSubmarineTable(submarines) {
        const tbody = document.querySelector('#upcoming-table tbody');
        if (!tbody) return;

        // Only update the first 15
        const subsToShow = submarines.slice(0, 15);

        tbody.innerHTML = subsToShow.map(sub => `
            <tr class="${this.getRowClass(sub.status)}">
                <td>
                    <strong>${sub.name}</strong>
                    <br><small class="text-muted">${sub.character}</small>
                </td>
                <td>${sub.fc_name || 'Unknown'}</td>
                <td><code>${sub.build || '-'}</code></td>
                <td>${sub.route || '-'}</td>
                <td>${sub.level}</td>
                <td class="text-end">
                    ${this.getStatusBadge(sub)}
                </td>
                <td class="text-end text-muted">${sub.return_time ? formatLocalTime(new Date(sub.return_time), 'short') : '-'}</td>
            </tr>
        `).join('');
    }

    getRowClass(status) {
        switch (status) {
            case 'ready': return 'table-success';
            case 'returning_soon': return 'table-warning';
            default: return '';
        }
    }

    getStatusBadge(sub) {
        if (sub.status === 'ready') {
            return '<span class="badge bg-success">READY</span>';
        } else if (sub.hours_remaining >= 1) {
            return `<span class="timer-countdown" data-return="${sub.return_time}">${sub.hours_remaining.toFixed(1)}h</span>`;
        } else {
            return `<span class="timer-countdown" data-return="${sub.return_time}">${Math.round(sub.hours_remaining * 60)}m</span>`;
        }
    }

    startTimerUpdates() {
        // Update countdown timers and clock every second
        this.timerInterval = setInterval(() => {
            this.updateTimers();
            this.updateLastUpdateTime();
        }, 1000);
    }

    updateTimers() {
        const timers = document.querySelectorAll('.timer-countdown');
        const now = new Date();

        timers.forEach(timer => {
            const returnTime = timer.dataset.return;
            if (!returnTime) return;

            const returnDate = new Date(returnTime);
            const diffMs = returnDate - now;
            const diffHours = diffMs / (1000 * 60 * 60);
            const row = timer.closest('tr');
            const fcRow = timer.closest('.fc-row');

            // Determine new state (thresholds match server: <= 0 ready, <= 0.5 warning)
            let newState;
            if (diffMs <= 0) {
                newState = 'ready';
            } else if (diffHours <= 0.5) {
                newState = 'warning';
            } else {
                newState = 'normal';
            }

            // Only update if state changed or time display needs refresh
            const currentState = timer.dataset.state;
            const minutes = Math.round(diffMs / (1000 * 60));

            if (newState === 'ready') {
                if (currentState !== 'ready') {
                    timer.innerHTML = 'READY';
                    timer.className = 'badge bg-success';
                    timer.dataset.state = 'ready';
                    if (row && !row.classList.contains('table-success')) {
                        row.classList.remove('table-warning');
                        row.classList.add('table-success');
                    }
                    // Update FC row highlighting
                    if (fcRow) {
                        fcRow.classList.remove('has-soon');
                        fcRow.classList.add('has-ready');
                    }
                }
            } else if (newState === 'warning') {
                timer.innerHTML = `<i class="bi bi-hourglass-split"></i> ${minutes}m`;
                if (currentState !== 'warning') {
                    timer.className = 'badge bg-warning text-dark timer-countdown';
                    timer.dataset.state = 'warning';
                    if (row && !row.classList.contains('table-warning')) {
                        row.classList.remove('table-success');
                        row.classList.add('table-warning');
                    }
                    // Update FC row highlighting (only if not already has-ready)
                    if (fcRow && !fcRow.classList.contains('has-ready')) {
                        fcRow.classList.add('has-soon');
                    }
                }
            } else {
                // Normal state (> 30 min)
                if (diffHours < 1) {
                    timer.innerHTML = `<i class="bi bi-clock"></i> ${minutes}m`;
                } else {
                    timer.innerHTML = `<i class="bi bi-clock"></i> ${diffHours.toFixed(1)}h`;
                }
                if (currentState !== 'normal') {
                    timer.className = 'timer-countdown text-muted';
                    timer.dataset.state = 'normal';
                    if (row && (row.classList.contains('table-success') || row.classList.contains('table-warning'))) {
                        row.classList.remove('table-success', 'table-warning');
                    }
                    // Don't remove FC row highlighting here - it's based on soonest sub, not this specific timer
                }
            }
        });
    }

    updateLastUpdateTime() {
        const timeEl = document.getElementById('update-time');
        if (timeEl) {
            const now = new Date();
            timeEl.textContent = now.toLocaleTimeString();
        }
    }

    updateElement(id, value) {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = value;
        }
    }

    formatNumber(num) {
        return num.toLocaleString();
    }

    requestUpdate() {
        if (this.socket && this.connected) {
            this.socket.emit('request_update');
        }
    }

    applyPagination() {
        const currentView = localStorage.getItem('armada-view') || 'table';
        const pageInfo = document.getElementById('pagination-info');
        const prevBtn = document.getElementById('page-prev');
        const nextBtn = document.getElementById('page-next');

        if (!pageInfo || !prevBtn || !nextBtn) return;

        // Only count visible (non-filtered) items
        let total;
        if (currentView === 'table') {
            total = document.querySelectorAll('#fc-table tbody > tr.fc-row:not(.tag-hidden):not(.search-hidden)').length;
        } else {
            total = document.querySelectorAll('#fc-cards > div:not(.tag-hidden):not(.search-hidden)').length;
        }

        // If pageSize is 0 (All), show all non-filtered items
        if (this.pageSize === 0) {
            if (currentView === 'table') {
                document.querySelectorAll('#fc-table tbody > tr.fc-row:not(.tag-hidden):not(.search-hidden)').forEach(row => {
                    row.style.display = '';
                    const fcId = row.dataset.fcId;
                    const detailRow = document.querySelector(`.fc-detail-row[data-fc-id="${fcId}"]`);
                    if (detailRow && row.classList.contains('expanded')) {
                        detailRow.style.display = 'table-row';
                    }
                });
                // Keep filtered rows hidden
                document.querySelectorAll('#fc-table tbody > tr.fc-row.tag-hidden, #fc-table tbody > tr.fc-row.search-hidden').forEach(row => {
                    row.style.display = 'none';
                });
            } else {
                document.querySelectorAll('#fc-cards > div:not(.tag-hidden):not(.search-hidden)').forEach(card => {
                    card.style.display = '';
                });
                document.querySelectorAll('#fc-cards > div.tag-hidden, #fc-cards > div.search-hidden').forEach(card => {
                    card.style.display = 'none';
                });
            }
            pageInfo.textContent = `1-${total} of ${total}`;
            prevBtn.disabled = true;
            nextBtn.disabled = true;
            return;
        }

        const totalPages = Math.ceil(total / this.pageSize);
        this.currentPage = Math.min(this.currentPage, Math.max(1, totalPages));

        const startIdx = (this.currentPage - 1) * this.pageSize;
        const endIdx = startIdx + this.pageSize;

        if (currentView === 'table') {
            // Only paginate visible (non-filtered) rows
            const fcRows = document.querySelectorAll('#fc-table tbody > tr.fc-row:not(.tag-hidden):not(.search-hidden)');
            fcRows.forEach((row, idx) => {
                const fcId = row.dataset.fcId;
                const detailRow = document.querySelector(`.fc-detail-row[data-fc-id="${fcId}"]`);
                if (idx >= startIdx && idx < endIdx) {
                    row.style.display = '';
                    if (detailRow && row.classList.contains('expanded')) {
                        detailRow.style.display = 'table-row';
                    }
                } else {
                    row.style.display = 'none';
                    if (detailRow) detailRow.style.display = 'none';
                }
            });
            // Keep filtered rows hidden
            document.querySelectorAll('#fc-table tbody > tr.fc-row.tag-hidden, #fc-table tbody > tr.fc-row.search-hidden').forEach(row => {
                row.style.display = 'none';
                const fcId = row.dataset.fcId;
                const detailRow = document.querySelector(`.fc-detail-row[data-fc-id="${fcId}"]`);
                if (detailRow) detailRow.style.display = 'none';
            });
        } else {
            // Only paginate visible (non-filtered) cards
            const cards = document.querySelectorAll('#fc-cards > div:not(.tag-hidden):not(.search-hidden)');
            cards.forEach((card, idx) => {
                card.style.display = (idx >= startIdx && idx < endIdx) ? '' : 'none';
            });
            // Keep filtered cards hidden
            document.querySelectorAll('#fc-cards > div.tag-hidden, #fc-cards > div.search-hidden').forEach(card => {
                card.style.display = 'none';
            });
        }

        // Update info text
        const showStart = total === 0 ? 0 : startIdx + 1;
        const showEnd = Math.min(endIdx, total);
        pageInfo.textContent = `${showStart}-${showEnd} of ${total}`;

        // Update button states
        prevBtn.disabled = this.currentPage <= 1;
        nextBtn.disabled = this.currentPage >= totalPages;
    }

    destroy() {
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
        }
        if (this.socket) {
            this.socket.disconnect();
        }
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    window.armada = new ArmadaDashboard();
    convertTimestampsToLocal();
});

/**
 * Convert all timestamps with data-timestamp attribute to local timezone
 */
function convertTimestampsToLocal() {
    document.querySelectorAll('[data-timestamp]').forEach(el => {
        const ts = el.dataset.timestamp;
        if (!ts) return;

        try {
            const date = new Date(ts);
            if (isNaN(date.getTime())) return;

            const format = el.dataset.format || 'datetime';
            el.textContent = formatLocalTime(date, format);
            el.classList.add('timestamp-converted'); // Show element after conversion
        } catch (e) {
            console.error('Failed to convert timestamp:', ts, e);
            el.classList.add('timestamp-converted'); // Show anyway to avoid hidden content
        }
    });
}

/**
 * Format a date to local timezone string
 * @param {Date} date - The date to format
 * @param {string} format - 'datetime', 'date', 'time', or 'short'
 */
function formatLocalTime(date, format = 'datetime') {
    switch (format) {
        case 'date':
            return date.toLocaleDateString();
        case 'time':
            return date.toLocaleTimeString();
        case 'short':
            return date.toLocaleString(undefined, {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        case 'datetime':
        default:
            return date.toLocaleString(undefined, {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
    }
}

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    if (window.armada) {
        window.armada.destroy();
    }
});
