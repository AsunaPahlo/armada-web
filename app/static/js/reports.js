/**
 * Armada Reports — Query Builder & Results
 */
class ArmadaReports {
    constructor() {
        this.schema = null;
        this.currentEntity = 'fcs';
        this.activeTab = 'visual';

        this.conditions = [];
        this.conditionId = 0;
        this.currentResults = null;
        this.currentQueryText = '';
        this.currentPage = 1;
        this.savedReportId = null;

        this.init();
    }

    async init() {
        await this.loadSchema();
        this.loadSavedReports();
        this.syncVisualToText();
    }

    async loadSchema() {
        try {
            const resp = await fetch('/reports/schema');
            this.schema = await resp.json();
        } catch (e) {
            console.error('Failed to load schema:', e);
        }
    }

    // ── Tab Switching ──

    switchTab(tab) {
        this.activeTab = tab;
        document.querySelectorAll('.tab-btn[data-tab]').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tab);
        });
        document.getElementById('tab-visual').style.display = tab === 'visual' ? '' : 'none';
        document.getElementById('tab-query').style.display = tab === 'query' ? '' : 'none';

        if (tab === 'query') {
            this.syncVisualToText();
        } else {
            // Try to parse text back to visual
            this.syncTextToVisual();
        }
    }

    // ── Entity Change ──

    onEntityChange() {
        this.currentEntity = document.getElementById('entity-select').value;
        this.conditions = [];
        this.renderConditions();
        this.syncVisualToText();
        this.hideError();
    }

    // ── Conditions Management ──

    getFieldsForEntity(entity) {
        if (!this.schema) return {};
        const entityDef = this.schema.entities[entity];
        return entityDef ? entityDef.fields : {};
    }

    addCondition() {
        this.conditionId++;
        this.conditions.push({
            id: this.conditionId,
            logic: this.conditions.length > 0 ? 'AND' : null,
            quantifier: null,
            field: '',
            operator: '=',
            value: '',
        });
        this.renderConditions();
        this.syncVisualToText();
    }

    removeCondition(id) {
        this.conditions = this.conditions.filter(c => c.id !== id);
        if (this.conditions.length > 0) {
            this.conditions[0].logic = null;
        }
        this.renderConditions();
        this.syncVisualToText();
    }

    updateCondition(id, key, value) {
        const cond = this.conditions.find(c => c.id === id);
        if (!cond) return;
        cond[key] = value;

        if (key === 'field') {
            // Reset operator and value when field changes
            const fields = this.getFieldsForEntity(this.currentEntity);
            const fieldDef = fields[value];
            if (fieldDef) {
                cond.operator = fieldDef.operators[0] || '=';
                cond.value = '';
                // Auto-show quantifier for child fields
                cond.quantifier = fieldDef.ref_type === 'child' ? 'ALL' : null;
            }
        }

        this.renderConditions();
        this.syncVisualToText();
    }

    renderConditions() {
        const container = document.getElementById('conditions-container');
        const fields = this.getFieldsForEntity(this.currentEntity);

        container.innerHTML = this.conditions.map(cond => {
            const fieldDef = fields[cond.field] || {};
            const operators = fieldDef.operators || ['=', '!=', '>', '<', '>=', '<=', 'CONTAINS'];
            const isChild = fieldDef.ref_type === 'child';
            const enumValues = fieldDef.enum_values;

            const showQuantifier = isChild;
            const isNullOp = cond.operator === 'IS EMPTY' || cond.operator === 'IS NOT EMPTY';

            return `
                <div class="condition-row" data-id="${cond.id}">
                    ${cond.logic !== null ? `
                        <select class="form-select form-select-sm" style="width: 80px;"
                                onchange="reports.updateCondition(${cond.id}, 'logic', this.value)">
                            <option value="AND" ${cond.logic === 'AND' ? 'selected' : ''}>AND</option>
                            <option value="OR" ${cond.logic === 'OR' ? 'selected' : ''}>OR</option>
                        </select>
                    ` : '<span style="width: 80px; display: inline-block;"></span>'}
                    ${showQuantifier ? `
                        <select class="form-select form-select-sm quantifier-select"
                                onchange="reports.updateCondition(${cond.id}, 'quantifier', this.value)">
                            <option value="ALL" ${cond.quantifier === 'ALL' ? 'selected' : ''}>ALL</option>
                            <option value="ANY" ${cond.quantifier === 'ANY' ? 'selected' : ''}>ANY</option>
                            <option value="NO" ${cond.quantifier === 'NO' ? 'selected' : ''}>NO</option>
                        </select>
                    ` : ''}
                    <select class="form-select form-select-sm"
                            onchange="reports.updateCondition(${cond.id}, 'field', this.value)">
                        <option value="">Select field...</option>
                        ${this._renderFieldOptions(fields, cond.field)}
                    </select>
                    <select class="form-select form-select-sm" style="width: auto;"
                            onchange="reports.updateCondition(${cond.id}, 'operator', this.value)">
                        ${operators.map(op =>
                            `<option value="${op}" ${cond.operator === op ? 'selected' : ''}>${op}</option>`
                        ).join('')}
                    </select>
                    ${!isNullOp ? `
                        ${enumValues ? `
                            <select class="form-select form-select-sm value-input"
                                    onchange="reports.updateCondition(${cond.id}, 'value', this.value)">
                                <option value="">Select...</option>
                                ${enumValues.map(v =>
                                    `<option value="${v}" ${cond.value === v ? 'selected' : ''}>${v}</option>`
                                ).join('')}
                            </select>
                        ` : `
                            <input type="${fieldDef.type === 'number' ? 'number' : 'text'}"
                                   class="form-control form-control-sm value-input"
                                   value="${cond.value}"
                                   placeholder="Value..."
                                   onchange="reports.updateCondition(${cond.id}, 'value', this.value)"
                                   onkeydown="if(event.key==='Enter'){event.preventDefault();reports.runQuery();}">
                        `}
                    ` : ''}
                    <button class="btn btn-outline-danger btn-remove"
                            onclick="reports.removeCondition(${cond.id})">
                        <i class="bi bi-x"></i>
                    </button>
                </div>
            `;
        }).join('');
    }

    _renderFieldOptions(fields, selectedField) {
        const directFields = [];
        const parentFields = [];
        const childFields = [];

        for (const [name, def] of Object.entries(fields)) {
            if (def.ref_type === 'parent') parentFields.push(name);
            else if (def.ref_type === 'child') childFields.push(name);
            else directFields.push(name);
        }

        let html = '';
        if (directFields.length) {
            html += `<optgroup label="Fields">`;
            html += directFields.map(f =>
                `<option value="${f}" ${selectedField === f ? 'selected' : ''}>${f}</option>`
            ).join('');
            html += `</optgroup>`;
        }
        if (parentFields.length) {
            html += `<optgroup label="Parent (FC)">`;
            html += parentFields.map(f =>
                `<option value="${f}" ${selectedField === f ? 'selected' : ''}>${f}</option>`
            ).join('');
            html += `</optgroup>`;
        }
        if (childFields.length) {
            html += `<optgroup label="Children">`;
            html += childFields.map(f =>
                `<option value="${f}" ${selectedField === f ? 'selected' : ''}>${f}</option>`
            ).join('');
            html += `</optgroup>`;
        }
        return html;
    }

    // ── Sync: Visual ↔ Text ──

    syncVisualToText() {
        let query = `FIND ${this.currentEntity}`;
        const validConditions = this.conditions.filter(c => c.field && c.operator);

        if (validConditions.length > 0) {
            query += ' WHERE ';
            query += validConditions.map((cond, i) => {
                let part = '';
                if (i > 0 && cond.logic) part += `${cond.logic} `;
                if (cond.quantifier) part += `${cond.quantifier} `;
                part += cond.field;
                part += ` ${cond.operator}`;
                if (cond.operator !== 'IS EMPTY' && cond.operator !== 'IS NOT EMPTY') {
                    const fields = this.getFieldsForEntity(this.currentEntity);
                    const fieldDef = fields[cond.field] || {};
                    if (fieldDef.type === 'number') {
                        part += ` ${cond.value}`;
                    } else {
                        part += ` "${cond.value}"`;
                    }
                }
                return part;
            }).join(' ');
        }

        this.currentQueryText = query;
        document.getElementById('query-editor').value = query;
    }

    syncTextToVisual() {
        const text = document.getElementById('query-editor').value.trim();
        if (!text) return;
        this.currentQueryText = text;

        // Extract entity
        const findMatch = text.match(/^FIND\s+(\w+)/i);
        if (!findMatch) return;

        const entity = findMatch[1].toLowerCase();
        const entityMap = { submarines: 'subs' };
        this.currentEntity = entityMap[entity] || entity;
        document.getElementById('entity-select').value = this.currentEntity;

        // Check if there are WHERE conditions
        const whereMatch = text.match(/WHERE\s+(.*?)(?:\s+(?:GROUP|ORDER|LIMIT)\s|$)/i);
        if (!whereMatch) {
            this.conditions = [];
            this.renderConditions();
            this.hideError();
            return;
        }

        // Show info banner that conditions should be edited in Query tab
        if (this.conditions.length === 0 && whereMatch[1].trim()) {
            this.showError('This query has conditions that were entered in the Query tab. Switch to the Query tab to edit them, or clear and rebuild here.');
        }
        // Don't clear conditions if user has been building in visual mode
    }

    // ── Query Execution ──

    async runQuery() {
        const queryText = this.activeTab === 'query'
            ? document.getElementById('query-editor').value.trim()
            : this.currentQueryText;

        if (!queryText) {
            this.showError('Enter a query to run');
            return;
        }

        this.hideError();
        document.getElementById('loading').style.display = '';
        document.getElementById('results-area').style.display = 'none';

        try {
            const resp = await fetch('/reports/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    query: queryText,
                    page: this.currentPage,
                }),
            });

            const data = await resp.json();
            if (!resp.ok || data.error) {
                this.showError(data.error || 'Query failed');
                document.getElementById('loading').style.display = 'none';
                return;
            }

            this.currentResults = data;
            this.currentQueryText = queryText;

            this.renderTable(data);

            document.getElementById('loading').style.display = 'none';
            document.getElementById('results-area').style.display = '';
        } catch (e) {
            this.showError('Network error: ' + e.message);
            document.getElementById('loading').style.display = 'none';
        }
    }

    // ── Results Rendering ──

    renderTable(data) {
        const header = document.getElementById('table-header');
        const body = document.getElementById('table-body');

        header.innerHTML = (data.columns || []).map(col =>
            `<th onclick="reports.sortBy('${col.name}')">${col.name}</th>`
        ).join('');

        body.innerHTML = (data.rows || []).map(row => {
            return '<tr>' + (data.columns || []).map(col => {
                let val = row[col.name];
                if (val === null || val === undefined) val = '';
                if (typeof val === 'object') val = JSON.stringify(val);
                return `<td>${this._escapeHtml(String(val))}</td>`;
            }).join('') + '</tr>';
        }).join('');

        const info = document.getElementById('results-info');
        let infoText = `${data.total} results`;
        if (data.truncated) infoText += ' (capped at 1000)';
        info.textContent = infoText;

        this.renderPagination(data);
    }

    renderPagination(data) {
        const nav = document.getElementById('pagination-nav');
        const pagination = document.getElementById('pagination');
        const totalPages = Math.ceil(data.total / data.per_page);

        if (totalPages <= 1) {
            nav.style.display = 'none';
            return;
        }

        nav.style.display = '';
        let html = '';

        html += `<li class="page-item ${data.page <= 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="event.preventDefault();reports.goToPage(${data.page - 1})">‹</a></li>`;

        for (let i = 1; i <= totalPages; i++) {
            if (i === 1 || i === totalPages || Math.abs(i - data.page) <= 2) {
                html += `<li class="page-item ${i === data.page ? 'active' : ''}">
                    <a class="page-link" href="#" onclick="event.preventDefault();reports.goToPage(${i})">${i}</a></li>`;
            } else if (Math.abs(i - data.page) === 3) {
                html += `<li class="page-item disabled"><span class="page-link">…</span></li>`;
            }
        }

        html += `<li class="page-item ${data.page >= totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="event.preventDefault();reports.goToPage(${data.page + 1})">›</a></li>`;

        pagination.innerHTML = html;
    }

    goToPage(page) {
        this.currentPage = page;
        this.runQuery();
    }

    // ── Saved Reports ──

    async loadSavedReports() {
        try {
            const resp = await fetch('/reports/saved');
            const reports = await resp.json();
            const list = document.getElementById('saved-reports-list');

            if (!reports.length) {
                list.innerHTML = '<div class="text-muted small text-center py-2">No saved reports</div>';
                return;
            }

            list.innerHTML = reports.map(r => `
                <div class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
                     data-report-id="${r.id}"
                     data-report-query="${this._escapeAttr(r.query_text)}">
                    <span>${this._escapeHtml(r.name)}</span>
                    <button class="btn btn-sm btn-outline-danger" data-delete-id="${r.id}">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            `).join('');

            // Add click handlers
            list.querySelectorAll('[data-report-id]').forEach(el => {
                el.addEventListener('click', (e) => {
                    if (e.target.closest('[data-delete-id]')) return;
                    reports.loadReport(
                        parseInt(el.dataset.reportId),
                        el.dataset.reportQuery
                    );
                });
            });
            list.querySelectorAll('[data-delete-id]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    reports.deleteReport(parseInt(btn.dataset.deleteId));
                });
            });
        } catch (e) {
            console.error('Failed to load saved reports:', e);
        }
    }

    loadReport(id, queryText) {
        this.savedReportId = id;
        document.getElementById('query-editor').value = queryText;
        this.currentQueryText = queryText;
        this.switchTab('query');
        this.runQuery();
    }

    async saveReport() {
        const name = prompt('Report name:');
        if (!name) return;

        const queryText = this.activeTab === 'query'
            ? document.getElementById('query-editor').value.trim()
            : this.currentQueryText;

        if (!queryText) {
            this.showError('Build a query before saving');
            return;
        }

        try {
            const resp = await fetch('/reports/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: name,
                    query: queryText,
                    display_config: {},
                }),
            });

            if (resp.ok) {
                this.loadSavedReports();
            }
        } catch (e) {
            this.showError('Failed to save report');
        }
    }

    async deleteReport(id) {
        if (!confirm('Delete this saved report?')) return;
        try {
            await fetch(`/reports/saved/${id}`, { method: 'DELETE' });
            this.loadSavedReports();
        } catch (e) {
            this.showError('Failed to delete report');
        }
    }

    // ── CSV Export ──

    async exportCsv() {
        if (!this.currentQueryText) return;
        try {
            const resp = await fetch('/reports/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: this.currentQueryText }),
            });
            if (!resp.ok) {
                const err = await resp.json();
                this.showError(err.error || 'Export failed');
                return;
            }
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'report.csv';
            a.click();
            URL.revokeObjectURL(url);
        } catch (e) {
            this.showError('Export failed: ' + e.message);
        }
    }

    // ── Helpers ──

    showError(msg) {
        const el = document.getElementById('parse-error');
        el.textContent = msg;
        el.style.display = '';
    }

    hideError() {
        document.getElementById('parse-error').style.display = 'none';
    }

    sortBy(field) {
        // Append or toggle ORDER BY in query text
        const text = this.currentQueryText;
        const orderMatch = text.match(/\s+ORDER\s+BY\s+(\w+(?:\.\w+)?)\s*(ASC|DESC)?/i);
        if (orderMatch && orderMatch[1] === field) {
            const dir = (orderMatch[2] || 'ASC').toUpperCase() === 'ASC' ? 'DESC' : 'ASC';
            this.currentQueryText = text.replace(/\s+ORDER\s+BY\s+\w+(?:\.\w+)?\s*(?:ASC|DESC)?/i, ` ORDER BY ${field} ${dir}`);
        } else if (orderMatch) {
            this.currentQueryText = text.replace(/\s+ORDER\s+BY\s+\w+(?:\.\w+)?\s*(?:ASC|DESC)?/i, ` ORDER BY ${field} ASC`);
        } else {
            this.currentQueryText = text + ` ORDER BY ${field} ASC`;
        }
        document.getElementById('query-editor').value = this.currentQueryText;
        this.runQuery();
    }

    _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    _escapeAttr(str) {
        return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
}

// Global instance and helper functions for onclick handlers
let reports;
document.addEventListener('DOMContentLoaded', () => {
    reports = new ArmadaReports();
});

function switchTab(tab) { reports.switchTab(tab); }

function onEntityChange() { reports.onEntityChange(); }
function addCondition() { reports.addCondition(); }
function runQuery() { reports.runQuery(); }
function saveReport() { reports.saveReport(); }
function exportCsv() { reports.exportCsv(); }
