/**
 * 标签打印助手 —— 前端交互逻辑
 *
 * 核心功能:
 * - 地址输入 → 自动解析 → 表格预览
 * - 表格单元格可编辑（打印以编辑后结果为准）
 * - 模板参数调整（字号、位置）并持久化到 localStorage
 * - 单张预览 / 批量打印 + SSE 实时进度
 */

// ============================================================
// 状态管理
// ============================================================

const state = {
    items: [],                  // 解析后的地址列表 [{index, name, phone, address, fullAddress, parseError}]
    printerList: [],            // 可用打印机
    currentPrinter: '',         // 当前选中打印机
    strategy: '',               // 当前解析策略名称
    printing: false,            // 是否正在打印
    currentTaskId: '',          // 当前打印任务 ID
    cancelRequested: false,     // 是否已请求取消
};

// ============================================================
// 模板参数（默认值，与后端 DEFAULT_TEMPLATE 一致）
// ============================================================

const DEFAULT_TEMPLATE = {
    title:    { fontHeight: 2.5, y: 1 },
    name:     { fontHeight: 5.0, y: 6 },
    phone:    { fontHeight: 3.2, y: 14 },
    address:  { fontHeight: 3.2, y: 20 },
    darkness: 5,
    speed: 2,
    gapType: 2,
    copies: 1,
};

/** 从 localStorage 读取上次保存的模板，无则用默认 */
function loadTemplate() {
    try {
        const saved = localStorage.getItem('label-template');
        if (saved) {
            return { ...DEFAULT_TEMPLATE, ...JSON.parse(saved) };
        }
    } catch (_) { /* ignore */ }
    return { ...DEFAULT_TEMPLATE };
}

/** 保存模板到 localStorage */
function saveTemplate(tpl) {
    try {
        localStorage.setItem('label-template', JSON.stringify(tpl));
    } catch (_) { /* ignore */ }
}

let template = loadTemplate();

// ============================================================
// DOM 引用缓存
// ============================================================

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const dom = {
    inputArea:       $('#input-area'),
    tableBody:       $('#table-body'),
    emptyRow:        $('#empty-row'),
    itemCount:       $('#item-count'),
    strategyBadge:   $('#strategy-badge'),
    checkAll:        $('#check-all'),
    printerSelect:   $('#printer-select'),
    _previewModal:   null,  // 延迟初始化，避免 bootstrap 未加载时崩溃
    previewImage:    $('#preview-image'),
    previewPlaceholder: $('#preview-placeholder'),
    progressContainer: $('#progress-container'),
    progressBar:     $('#progress-bar'),
    progressText:    $('#progress-text'),
    progressStatus:  $('#progress-status'),
    btnPrint:        $('#btn-print'),
    btnPrintCount:   $('#btn-print-count'),
    btnStop:         $('#btn-stop'),
    btnPreview:      $('#btn-preview'),
    btnDeleteSelected: $('#btn-delete-selected'),
    fileInput:       $('#file-input'),

    /** 延迟获取 previewModal，首次调用时才初始化 */
    get previewModal() {
        if (!this._previewModal) {
            const el = $('#preview-modal');
            if (el && typeof bootstrap !== 'undefined') {
                this._previewModal = new bootstrap.Modal(el);
            }
        }
        return this._previewModal;
    },
};

// 模板输入控件
const tplInputs = {
    titleFont:   $('#tpl-title-font'),
    nameFont:    $('#tpl-name-font'),
    phoneFont:   $('#tpl-phone-font'),
    addressFont: $('#tpl-address-font'),
    titleY:      $('#tpl-title-y'),
    nameY:       $('#tpl-name-y'),
    phoneY:      $('#tpl-phone-y'),
    addressY:    $('#tpl-address-y'),
    copies:      $('#print-copies'),
    darkness:    $('#print-darkness'),
    speed:       $('#print-speed'),
};

// ============================================================
// 初始化
// ============================================================

function init() {
    try {
        console.log('[标签打印助手] 初始化开始...');
        console.log('[标签打印助手] Bootstrap 可用:', typeof bootstrap !== 'undefined');

        bindEvents();
        syncTemplateToUI();
        refreshPrinters();
        fetchHealth();

        console.log('[标签打印助手] 初始化完成');
    } catch (e) {
        console.error('[标签打印助手] 初始化失败:', e);
        alert('页面初始化失败: ' + e.message + '\n请检查浏览器控制台获取详细信息');
    }
}

// ============================================================
// 事件绑定
// ============================================================

function bindEvents() {
    // 地址输入 —— debounce 500ms 自动解析
    let parseTimer = null;
    dom.inputArea.addEventListener('input', () => {
        clearTimeout(parseTimer);
        parseTimer = setTimeout(parseAddresses, 500);
    });

    // 全选
    dom.checkAll.addEventListener('change', (e) => {
        const checked = e.target.checked;
        $$('#table-body input.row-checkbox').forEach(cb => cb.checked = checked);
        updateSelectedCount();
    });

    // 全选按钮
    $('#btn-select-all').addEventListener('click', () => {
        $$('#table-body input.row-checkbox').forEach(cb => cb.checked = true);
        dom.checkAll.checked = true;
        updateSelectedCount();
    });

    // 反选
    $('#btn-invert').addEventListener('click', () => {
        $$('#table-body input.row-checkbox').forEach(cb => cb.checked = !cb.checked);
        updateSelectedCount();
    });

    // 删除选中
    $('#btn-delete-selected').addEventListener('click', deleteSelected);

    // 文件导入
    $('#btn-import').addEventListener('click', () => dom.fileInput.click());
    dom.fileInput.addEventListener('change', handleFileImport);

    // 清空
    $('#btn-clear-input').addEventListener('click', () => {
        dom.inputArea.value = '';
        state.items = [];
        renderTable();
    });

    // 打印机
    $('#btn-refresh-printer').addEventListener('click', refreshPrinters);
    dom.printerSelect.addEventListener('change', (e) => {
        state.currentPrinter = e.target.value;
    });

    // 预览
    dom.btnPreview.addEventListener('click', previewSelected);

    // 打印
    dom.btnPrint.addEventListener('click', startPrint);

    // 停止打印
    dom.btnStop.addEventListener('click', cancelPrint);

    // 恢复默认模板
    $('#btn-reset-template').addEventListener('click', () => {
        template = { ...DEFAULT_TEMPLATE };
        saveTemplate(template);
        syncTemplateToUI();
    });

    // 模板参数变化
    Object.values(tplInputs).forEach(input => {
        if (input) {
            input.addEventListener('change', onTemplateChanged);
        }
    });
}

// ============================================================
// API 调用
// ============================================================

async function apiGet(url) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
    return resp.json();
}

async function apiPost(url, body) {
    const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `${resp.status} ${resp.statusText}`);
    }
    return resp.json();
}

// ============================================================
// 健康检查 & 策略
// ============================================================

async function fetchHealth() {
    try {
        const data = await apiGet('/api/health');
        state.strategy = data.strategy || '--';
        dom.strategyBadge.textContent = `策略: ${state.strategy}`;
    } catch (_) {
        dom.strategyBadge.textContent = '策略: 离线';
        dom.strategyBadge.classList.replace('bg-secondary', 'bg-danger');
    }
}

// ============================================================
// 打印机
// ============================================================

async function refreshPrinters() {
    try {
        const data = await apiGet('/api/printers');
        state.printerList = data.printers || [];
        renderPrinterSelect();
    } catch (e) {
        console.error('获取打印机失败:', e);
    }
}

function renderPrinterSelect() {
    const sel = dom.printerSelect;
    sel.innerHTML = '';

    if (state.printerList.length === 0) {
        sel.innerHTML = '<option value="">-- 未检测到打印机 --</option>';
        state.currentPrinter = '';
    } else {
        state.printerList.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.name;
            opt.textContent = `${p.name}${p.hostname ? ' @' + p.hostname : ''}`;
            sel.appendChild(opt);
        });
        state.currentPrinter = state.printerList[0].name;
        sel.value = state.currentPrinter;
    }
}

// ============================================================
// 地址解析
// ============================================================

async function parseAddresses() {
    const text = dom.inputArea.value;
    if (!text.trim()) {
        state.items = [];
        renderTable();
        return;
    }

    try {
        const data = await apiPost('/api/address/parse', { text });
        state.items = data.items || [];
        state.strategy = data.strategy || state.strategy;
        dom.strategyBadge.textContent = `策略: ${state.strategy}`;
        renderTable();
    } catch (e) {
        console.error('解析失败:', e);
    }
}

// ============================================================
// 表格渲染
// ============================================================

function renderTable() {
    const tbody = dom.tableBody;
    tbody.innerHTML = '';

    if (state.items.length === 0) {
        tbody.innerHTML = `<tr id="empty-row">
            <td colspan="5" class="text-center text-muted py-4">
                请在左侧输入收货地址，或从文件导入
            </td></tr>`;
        dom.itemCount.textContent = '0';
        dom.btnPrintCount.textContent = '(0)';
        dom.checkAll.checked = false;
        dom.btnDeleteSelected.disabled = true;
        return;
    }

    state.items.forEach((item, idx) => {
        const tr = document.createElement('tr');
        if (item.parseError) {
            tr.classList.add('parse-error');
        }

        tr.innerHTML = `
            <td>
                <input type="checkbox" class="row-checkbox" data-index="${idx}"
                       ${!item.parseError ? 'checked' : ''}>
            </td>
            <td contenteditable="true" data-field="name" data-index="${idx}"
                title="双击编辑">${escapeHtml(item.name)}</td>
            <td contenteditable="true" data-field="phone" data-index="${idx}"
                title="双击编辑">${escapeHtml(item.phone)}</td>
            <td contenteditable="true" data-field="address" data-index="${idx}"
                title="双击编辑">${escapeHtml(item.address)}</td>
            <td class="text-muted small" title="${escapeHtml(item.fullAddress || '')}">
                ${escapeHtml(truncate(item.fullAddress, 20))}</td>
        `;

        tbody.appendChild(tr);
    });

    // 绑定编辑事件
    $$('#table-body td[contenteditable]').forEach(td => {
        td.addEventListener('input', onCellEdited);
    });

    // 绑定复选框事件
    $$('#table-body input.row-checkbox').forEach(cb => {
        cb.addEventListener('change', updateSelectedCount);
    });

    dom.itemCount.textContent = String(state.items.length);
    updateSelectedCount();
    dom.checkAll.checked = true;  // 默认全选
}

/** 单元格编辑回调 */
function onCellEdited(e) {
    const td = e.target;
    const idx = parseInt(td.dataset.index);
    const field = td.dataset.field;

    if (idx >= 0 && idx < state.items.length && field) {
        state.items[idx][field] = td.textContent.trim();
        // 标记该行为已编辑
        td.closest('tr')?.classList.add('edited');
    }
}

/** 更新选中计数和按钮状态 */
function updateSelectedCount() {
    const checked = $$('#table-body input.row-checkbox:checked');
    const count = checked.length;

    dom.btnPrintCount.textContent = `(${count})`;
    dom.btnDeleteSelected.disabled = (count === 0 || state.printing);
    dom.btnPrint.disabled = (count === 0 || state.printing);
    dom.btnPreview.disabled = (count === 0);

    // 更新全选 checkbox
    const total = $$('#table-body input.row-checkbox').length;
    dom.checkAll.checked = (count > 0 && count === total);
    dom.checkAll.indeterminate = (count > 0 && count < total);
}

// ============================================================
// 选中项操作
// ============================================================

/** 获取所有选中的 items（已含用户编辑后的最新值） */
function getSelectedItems() {
    const checked = $$('#table-body input.row-checkbox:checked');
    return Array.from(checked).map(cb => {
        const idx = parseInt(cb.dataset.index);
        return state.items[idx];
    }).filter(Boolean);
}

/** 删除选中行 */
function deleteSelected() {
    const checked = $$('#table-body input.row-checkbox:checked');
    const indices = Array.from(checked)
        .map(cb => parseInt(cb.dataset.index))
        .sort((a, b) => b - a);  // 从后往前删，避免索引错位

    indices.forEach(i => state.items.splice(i, 1));

    // 更新原始输入文本（同步回去）
    dom.inputArea.value = state.items
        .map(it => `${it.name}  ${it.phone}  ${it.fullAddress || it.address}`)
        .join('\n');

    renderTable();
}

// ============================================================
// 模板参数变更
// ============================================================

function syncTemplateToUI() {
    tplInputs.titleFont.value   = template.title.fontHeight;
    tplInputs.nameFont.value    = template.name.fontHeight;
    tplInputs.phoneFont.value   = template.phone.fontHeight;
    tplInputs.addressFont.value = template.address.fontHeight;
    tplInputs.titleY.value      = template.title.y;
    tplInputs.nameY.value       = template.name.y;
    tplInputs.phoneY.value      = template.phone.y;
    tplInputs.addressY.value    = template.address.y;
    tplInputs.copies.value      = template.copies || 1;
    tplInputs.darkness.value    = template.darkness || 5;
    tplInputs.speed.value       = String(template.speed ?? 2);
}

function onTemplateChanged() {
    template.title.fontHeight    = parseFloat(tplInputs.titleFont.value) || 2.5;
    template.name.fontHeight     = parseFloat(tplInputs.nameFont.value) || 5.0;
    template.phone.fontHeight    = parseFloat(tplInputs.phoneFont.value) || 3.2;
    template.address.fontHeight  = parseFloat(tplInputs.addressFont.value) || 3.2;
    template.title.y             = parseFloat(tplInputs.titleY.value) || 1;
    template.name.y              = parseFloat(tplInputs.nameY.value) || 6;
    template.phone.y             = parseFloat(tplInputs.phoneY.value) || 14;
    template.address.y           = parseFloat(tplInputs.addressY.value) || 20;
    template.copies              = parseInt(tplInputs.copies.value) || 1;
    template.darkness            = parseInt(tplInputs.darkness.value) || 5;
    template.speed               = parseInt(tplInputs.speed.value) || 2;

    saveTemplate(template);
}

/** 构建发送给后端的模板对象 */
function buildTemplatePayload() {
    return {
        title:    { fontHeight: template.title.fontHeight, y: template.title.y },
        name:     { fontHeight: template.name.fontHeight, y: template.name.y },
        phone:    { fontHeight: template.phone.fontHeight, y: template.phone.y },
        address:  { fontHeight: template.address.fontHeight, y: template.address.y },
        darkness: template.darkness,
        speed:    template.speed,
        gapType:  template.gapType,
    };
}

// ============================================================
// 预览
// ============================================================

async function previewSelected() {
    const selected = getSelectedItems();
    if (selected.length === 0) return;

    // 预览第一项
    const item = selected[0];
    dom.previewPlaceholder.style.display = 'none';
    dom.previewImage.src = '';
    dom.previewImage.style.display = 'none';
    if (dom.previewModal) {
        dom.previewModal.show();
    } else {
        // Bootstrap 未加载，直接展示图片
        dom.previewPlaceholder.innerHTML =
            '<p class="text-warning small mt-2">⚠ Bootstrap 未加载，无法弹窗。请刷新页面重试</p>';
        dom.previewPlaceholder.style.display = '';
        return;
    }

    try {
        const data = await apiPost('/api/address/preview', {
            name: item.name,
            phone: item.phone,
            address: item.address,
            printerName: state.currentPrinter,
            template: buildTemplatePayload(),
        });

        if (data.image) {
            dom.previewImage.src = data.image;
            dom.previewImage.style.display = '';
            dom.previewPlaceholder.style.display = 'none';
        } else {
            dom.previewPlaceholder.innerHTML =
                '<p class="text-warning small mt-2">⚠ 预览图生成失败，请确认打印机已连接</p>';
            dom.previewPlaceholder.style.display = '';
        }
    } catch (e) {
        dom.previewPlaceholder.innerHTML =
            `<p class="text-danger small mt-2">预览失败: ${escapeHtml(e.message)}</p>`;
        dom.previewPlaceholder.style.display = '';
    }
}

// ============================================================
// 打印
// ============================================================

async function startPrint() {
    const selected = getSelectedItems();
    if (selected.length === 0) {
        alert('请先勾选要打印的地址');
        return;
    }
    if (!state.currentPrinter) {
        alert('请先选择打印机');
        return;
    }
    if (state.printing) return;

    state.printing = true;
    state.cancelRequested = false;
    setUIState('printing');

    try {
        const data = await apiPost('/api/address/print', {
            items: selected.map(it => ({
                name: it.name,
                phone: it.phone,
                address: it.address,
            })),
            printerName: state.currentPrinter,
            template: buildTemplatePayload(),
            copies: template.copies || 1,
        });

        state.currentTaskId = data.taskId;
        listenProgress(data.taskId, data.total);
    } catch (e) {
        alert(`启动打印失败: ${e.message}`);
        state.printing = false;
        setUIState('idle');
    }
}

/** 通过 SSE 监听打印进度 */
function listenProgress(taskId, total) {
    const url = `/api/address/print/${taskId}/status`;
    const es = new EventSource(url);

    dom.progressContainer.style.display = '';
    dom.progressBar.style.width = '0%';
    dom.progressText.textContent = `0/${total}`;
    dom.progressStatus.textContent = '准备打印...';

    es.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        const { current, total: t, status, item, error } = msg;

        const pct = t > 0 ? Math.round((current / t) * 100) : 0;
        dom.progressBar.style.width = `${pct}%`;
        dom.progressText.textContent = `${current}/${t}`;

        switch (status) {
            case 'printing':
                dom.progressStatus.textContent =
                    `正在打印: ${item?.name || '--'}`;
                dom.progressBar.classList.remove('bg-success', 'bg-danger', 'bg-warning');
                dom.progressBar.classList.add('bg-primary');
                break;
            case 'done':
                dom.progressStatus.textContent =
                    `✅ ${item?.name || '--'} 打印完成`;
                dom.progressBar.classList.add('bg-success');
                break;
            case 'error':
                dom.progressStatus.textContent =
                    `❌ ${item?.name || '--'} 失败: ${error || '未知错误'}`;
                dom.progressBar.classList.add('bg-danger');
                break;
            case 'cancelled':
                dom.progressStatus.textContent = '⏹ 打印已取消';
                dom.progressBar.classList.add('bg-warning');
                es.close();
                finishPrint();
                break;
            case 'finished':
                dom.progressStatus.textContent = '✅ 全部打印完成!';
                dom.progressBar.classList.add('bg-success');
                es.close();
                finishPrint();
                break;
        }
    };

    es.onerror = () => {
        es.close();
        if (!state.cancelRequested) {
            dom.progressStatus.textContent = '⚠ 连接中断';
        }
        finishPrint();
    };
}

function cancelPrint() {
    state.cancelRequested = true;
    if (state.currentTaskId) {
        apiPost(`/api/address/print/${state.currentTaskId}/cancel`, {})
            .catch(() => {});
    }
}

function finishPrint() {
    state.printing = false;
    state.currentTaskId = '';
    setUIState('idle');
}

// ============================================================
// UI 状态切换
// ============================================================

function setUIState(mode) {
    if (mode === 'printing') {
        dom.btnPrint.disabled = true;
        dom.btnPrint.classList.add('d-none');
        dom.btnStop.classList.remove('d-none');
        dom.btnDeleteSelected.disabled = true;
        dom.progressContainer.style.display = '';
    } else {
        dom.btnPrint.disabled = false;
        dom.btnPrint.classList.remove('d-none');
        dom.btnStop.classList.add('d-none');
        dom.progressContainer.style.display = 'none';
        updateSelectedCount();
    }
}

// ============================================================
// 文件导入
// ============================================================

function handleFileImport(e) {
    const file = e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (ev) => {
        let text = ev.target.result;

        // 简单处理 CSV（取第一列或合并前几列）
        if (file.name.endsWith('.csv')) {
            const lines = text.split('\n').filter(ln => ln.trim());
            const converted = [];
            for (const ln of lines) {
                const cols = ln.split(',').map(c => c.trim().replace(/^"|"$/g, ''));
                // 尝试：姓名,电话,地址 → 空格拼接
                if (cols.length >= 3) {
                    converted.push(`${cols[0]}  ${cols[1]}  ${cols.slice(2).join(' ')}`);
                } else {
                    converted.push(ln);
                }
            }
            text = converted.join('\n');
        }

        dom.inputArea.value = text;
        parseAddresses();
    };
    reader.readAsText(file, 'UTF-8');

    // 允许重复选择同一文件
    e.target.value = '';
}

// ============================================================
// 工具函数
// ============================================================

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function truncate(str, maxLen) {
    if (!str) return '';
    return str.length > maxLen ? str.slice(0, maxLen) + '…' : str;
}

// ============================================================
// 启动
// ============================================================

document.addEventListener('DOMContentLoaded', init);
