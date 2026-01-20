/**
 * UnlockFlowchart - Controller for submarine sector unlock visualization
 *
 * Uses vis.js Network for hierarchical flowchart display of sector
 * unlock dependencies across all 7 submarine exploration maps.
 */
class UnlockFlowchart {
    constructor(mapNames) {
        this.mapNames = mapNames || {};
        this.network = null;
        this.currentMapId = 1;
        this.currentFcId = 'all';
        this.container = null;
    }

    /**
     * Initialize the flowchart controller
     */
    init() {
        this.container = document.getElementById('flowchart-network');
        if (!this.container) {
            console.error('Flowchart container not found');
            return;
        }

        // Read initial FC from selector
        const fcSelector = document.getElementById('fc-selector');
        if (fcSelector) {
            this.currentFcId = fcSelector.value;
        }

        // Set up event listeners
        this.setupEventListeners();

        // Refresh map summary to handle browser form restoration
        // (browser may restore dropdown to different FC than server rendered)
        this.updateMapSummary();

        // Load initial map
        this.loadMap(1);
    }

    /**
     * Set up DOM event listeners
     */
    setupEventListeners() {
        // FC selector change
        const fcSelector = document.getElementById('fc-selector');
        if (fcSelector) {
            fcSelector.addEventListener('change', (e) => {
                this.currentFcId = e.target.value;
                this.refreshAll();
            });
        }

        // Map tab clicks
        const mapItems = document.querySelectorAll('.map-progress-item');
        mapItems.forEach(item => {
            item.addEventListener('click', (e) => {
                const mapId = parseInt(item.dataset.mapId);
                if (mapId && mapId >= 1 && mapId <= 7) {
                    this.selectMap(mapId);
                }
            });
        });
    }

    /**
     * Select and display a specific map
     */
    selectMap(mapId) {
        // Update active state
        document.querySelectorAll('.map-progress-item').forEach(item => {
            item.classList.remove('active');
            if (parseInt(item.dataset.mapId) === mapId) {
                item.classList.add('active');
            }
        });

        // Update map name display
        const mapNameEl = document.getElementById('current-map-name');
        if (mapNameEl) {
            mapNameEl.textContent = this.mapNames[mapId] || `Map ${mapId}`;
        }

        // Load the map data
        this.loadMap(mapId);
    }

    /**
     * Load flowchart data for a specific map
     */
    async loadMap(mapId) {
        this.currentMapId = mapId;
        this.showLoading(true);

        try {
            const response = await fetch(`/unlocks/api/flowchart/${this.currentFcId}/${mapId}`);
            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }

            const data = await response.json();
            this.renderNetwork(data);
        } catch (error) {
            console.error('Failed to load flowchart data:', error);
            this.showError('Failed to load flowchart data');
        } finally {
            this.showLoading(false);
        }
    }

    /**
     * Render the vis.js network
     */
    renderNetwork(data) {
        if (!this.container) return;

        const nodes = new vis.DataSet(data.nodes);
        const edges = new vis.DataSet(data.edges);

        const options = {
            layout: {
                hierarchical: {
                    enabled: true,
                    direction: 'UD',  // Up-Down (top to bottom)
                    sortMethod: 'directed',
                    levelSeparation: 80,
                    nodeSpacing: 100,
                    treeSpacing: 150,
                    blockShifting: true,
                    edgeMinimization: true,
                    parentCentralization: true
                }
            },
            nodes: {
                font: {
                    size: 14,
                    face: 'Segoe UI, system-ui, sans-serif',
                    bold: {
                        color: '#ffffff'
                    }
                },
                margin: 10,
                widthConstraint: {
                    minimum: 40,
                    maximum: 80
                }
            },
            edges: {
                smooth: {
                    enabled: true,
                    type: 'cubicBezier',
                    forceDirection: 'vertical',
                    roundness: 0.4
                },
                arrows: {
                    to: {
                        enabled: true,
                        scaleFactor: 0.7
                    }
                }
            },
            physics: {
                enabled: false  // Disable physics for hierarchical layout
            },
            interaction: {
                hover: true,
                tooltipDelay: 100,
                navigationButtons: false,
                keyboard: {
                    enabled: true,
                    bindToWindow: false
                },
                zoomView: true,
                dragView: true
            }
        };

        // Destroy previous network if exists
        if (this.network) {
            this.network.destroy();
        }

        // Create new network
        this.network = new vis.Network(this.container, { nodes, edges }, options);

        // Set up network event handlers
        this.setupNetworkEvents();

        // Fit to view after render
        this.network.once('stabilized', () => {
            this.fitNetwork();
        });
    }

    /**
     * Set up vis.js network event handlers
     */
    setupNetworkEvents() {
        if (!this.network) return;

        // Click event for sector details
        this.network.on('click', (params) => {
            if (params.nodes.length > 0) {
                const nodeId = params.nodes[0];
                this.onSectorClick(nodeId);
            }
        });

        // Hover events for highlighting
        this.network.on('hoverNode', (params) => {
            document.body.style.cursor = 'pointer';
        });

        this.network.on('blurNode', (params) => {
            document.body.style.cursor = 'default';
        });
    }

    /**
     * Handle sector node click
     */
    onSectorClick(sectorId) {
        // Get node data
        const nodes = this.network.body.data.nodes;
        const node = nodes.get(sectorId);

        if (node) {
            console.log('Sector clicked:', node);
            // Could show a modal with sector details in the future
        }
    }

    /**
     * Refresh all data (map summary and current flowchart)
     */
    async refreshAll() {
        await Promise.all([
            this.updateMapSummary(),
            this.loadMap(this.currentMapId)
        ]);
    }

    /**
     * Update the map progress summary bars
     */
    async updateMapSummary() {
        try {
            const response = await fetch(`/unlocks/api/summary?fc_id=${this.currentFcId}`);
            if (!response.ok) return;

            const summary = await response.json();

            // Update each map progress item
            for (let mapId = 1; mapId <= 7; mapId++) {
                const mapData = summary[mapId];
                const item = document.querySelector(`.map-progress-item[data-map-id="${mapId}"]`);

                if (item && mapData) {
                    // Update progress text
                    const progressText = item.querySelector('.progress-text');
                    if (progressText) {
                        progressText.textContent = `${mapData.unlocked}/${mapData.total}`;
                    }

                    // Update progress bar
                    const progressFill = item.querySelector('.progress-bar-fill');
                    if (progressFill) {
                        progressFill.style.width = `${mapData.percent}%`;
                    }

                    // Update locked/complete state
                    item.classList.toggle('locked', !mapData.accessible);
                    item.classList.toggle('complete', mapData.complete);
                }
            }
        } catch (error) {
            console.error('Failed to update map summary:', error);
        }
    }

    /**
     * Fit network to container
     */
    fitNetwork() {
        if (this.network) {
            this.network.fit({
                animation: {
                    duration: 500,
                    easingFunction: 'easeInOutQuad'
                }
            });
        }
    }

    /**
     * Reset network view to initial state
     */
    resetView() {
        if (this.network) {
            this.network.fit();
            this.network.moveTo({
                scale: 1,
                animation: {
                    duration: 500,
                    easingFunction: 'easeInOutQuad'
                }
            });
        }
    }

    /**
     * Zoom in on the network
     */
    zoomIn() {
        if (this.network) {
            const scale = this.network.getScale();
            this.network.moveTo({
                scale: scale * 1.3,
                animation: {
                    duration: 300,
                    easingFunction: 'easeInOutQuad'
                }
            });
        }
    }

    /**
     * Zoom out on the network
     */
    zoomOut() {
        if (this.network) {
            const scale = this.network.getScale();
            this.network.moveTo({
                scale: scale / 1.3,
                animation: {
                    duration: 300,
                    easingFunction: 'easeInOutQuad'
                }
            });
        }
    }

    /**
     * Show/hide loading overlay
     */
    showLoading(show) {
        const overlay = document.getElementById('loading-overlay');
        if (overlay) {
            overlay.classList.toggle('hidden', !show);
        }
    }

    /**
     * Show error message
     */
    showError(message) {
        console.error(message);
        // Could show a toast notification in the future
    }
}
