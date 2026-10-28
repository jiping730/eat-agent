const knowledgeApiKeyInput = document.getElementById('knowledgeApiKey');
const knowledgeFileInput = document.getElementById('knowledgeFile');
const knowledgeTitleInput = document.getElementById('knowledgeTitle');
const knowledgeGroupsInput = document.getElementById('knowledgeGroups');
const knowledgeContentInput = document.getElementById('knowledgeContent');
const knowledgeStatus = document.getElementById('knowledgeStatus');
const knowledgeDocuments = document.getElementById('knowledgeDocuments');
const knowledgeSummary = document.getElementById('knowledgeSummary');
const knowledgeBuilds = document.getElementById('knowledgeBuilds');
const rollbackTarget = document.getElementById('rollbackTarget');
const retrievalResult = document.getElementById('retrievalResult');
const analyticsResult = document.getElementById('knowledgeAnalytics');

let accessToken = localStorage.getItem('accessToken');
let knowledgeApiKey = localStorage.getItem('knowledgeApiKey') || '';
knowledgeApiKeyInput.value = knowledgeApiKey;

function setStatus(message, error = false) {
    knowledgeStatus.textContent = message;
    knowledgeStatus.className = `knowledge-status${error ? ' error' : ''}`;
}

function authHeaders() {
    const headers = { 'Content-Type': 'application/json' };
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    if (knowledgeApiKey) headers['X-API-Key'] = knowledgeApiKey;
    return headers;
}

async function apiJson(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: { ...authHeaders(), ...(options.headers || {}) },
    });
    let data = {};
    try { data = await response.json(); } catch (_) { data = {}; }
    if (!response.ok) throw new Error(data.error || `请求失败（${response.status}）`);
    return data;
}

function button(label, handler, className = '') {
    const element = document.createElement('button');
    element.type = 'button';
    element.textContent = label;
    if (className) element.className = className;
    element.addEventListener('click', handler);
    return element;
}

function renderDocuments(items) {
    knowledgeDocuments.textContent = '';
    knowledgeSummary.textContent = `共 ${items.length} 个文档；可按状态审核、发布或下线。`;
    if (!items.length) {
        knowledgeDocuments.textContent = '暂无文档，请先上传。';
        return;
    }
    const table = document.createElement('table');
    table.className = 'knowledge-table';
    const header = document.createElement('tr');
    ['文档', '状态', '版本', '更新时间', '操作'].forEach((label) => {
        const cell = document.createElement('th');
        cell.textContent = label;
        header.appendChild(cell);
    });
    table.appendChild(header);
    items.forEach((item) => {
        const row = document.createElement('tr');
        [item.title || item.source_name, item.status, `v${item.latest_version}${item.published_version ? ` / 已发布 v${item.published_version}` : ''}`, item.updated_at || '-'].forEach((value) => {
            const cell = document.createElement('td');
            cell.textContent = value;
            row.appendChild(cell);
        });
        const actions = document.createElement('td');
        if (['draft', 'rejected', 'approved'].includes(item.status)) {
            actions.appendChild(button(item.status === 'approved' ? '重新审核' : '审核', () => reviewDocument(item)));
        }
        if (item.status === 'approved') actions.appendChild(button('发布', () => publishDocument(item), 'primary-action'));
        if (item.status === 'published') actions.appendChild(button('下线', () => unpublishDocument(item)));
        actions.appendChild(button('详情', () => showDocument(item.id)));
        row.appendChild(actions);
        table.appendChild(row);
    });
    knowledgeDocuments.appendChild(table);
}

async function loadDocuments() {
    const data = await apiJson('/admin/knowledge/documents');
    renderDocuments(data.items || []);
}

async function reviewDocument(item) {
    const approved = window.confirm(`审核通过“${item.title}”吗？\n点击“取消”将标记为驳回。`);
    const note = window.prompt('审核备注（可选）', item.review_note || '') || '';
    await apiJson(`/admin/knowledge/documents/${encodeURIComponent(item.id)}/review`, {
        method: 'POST',
        body: JSON.stringify({ approved, note }),
    });
    setStatus(approved ? '审核通过' : '已驳回');
    await loadDocuments();
}

async function publishDocument(item) {
    if (!window.confirm(`发布“${item.title}”，并构建新的知识库索引吗？`)) return;
    const data = await apiJson(`/admin/knowledge/documents/${encodeURIComponent(item.id)}/publish`, { method: 'POST' });
    setStatus(`发布完成：${data.build?.index_version || '-'}`);
    await refreshAll();
}

async function unpublishDocument(item) {
    if (!window.confirm(`确认下线“${item.title}”并重建索引吗？`)) return;
    await apiJson(`/admin/knowledge/documents/${encodeURIComponent(item.id)}/unpublish`, { method: 'POST' });
    setStatus('文档已下线');
    await refreshAll();
}

async function showDocument(id) {
    const data = await apiJson(`/admin/knowledge/documents/${encodeURIComponent(id)}`);
    const versions = (data.versions || []).map((item) => `v${item.version} · ${item.content_hash.slice(0, 12)} · ${item.created_at}`).join('\n');
    window.alert(`${data.title}\n状态：${data.status}\n来源：${data.source_name}\n版本：\n${versions}`);
}

async function uploadDocument() {
    let sourceName = knowledgeFileInput.files[0]?.name || 'managed-document.txt';
    let content = knowledgeContentInput.value;
    if (knowledgeFileInput.files[0]) content = await knowledgeFileInput.files[0].text();
    if (!content.trim()) throw new Error('请先选择文件或粘贴文档内容');
    const groups = knowledgeGroupsInput.value.split(',').map((item) => item.trim()).filter(Boolean);
    await apiJson('/admin/knowledge/documents', {
        method: 'POST',
        body: JSON.stringify({ source_name: sourceName, title: knowledgeTitleInput.value.trim() || null, content, access_groups: groups }),
    });
    setStatus('文档已上传为草稿');
    knowledgeContentInput.value = '';
    knowledgeFileInput.value = '';
    await loadDocuments();
}

async function loadBuilds() {
    const data = await apiJson('/admin/knowledge/index/builds');
    knowledgeBuilds.textContent = '';
    rollbackTarget.innerHTML = '<option value="">选择历史版本</option>';
    (data.items || []).forEach((item) => {
        const line = document.createElement('div');
        line.className = 'build-item';
        line.textContent = `${item.index_version} · ${item.status} · ${item.progress}% · ${item.document_count} 文档 / ${item.chunk_count} 分块`;
        knowledgeBuilds.appendChild(line);
        if (item.status !== 'failed' && item.status !== 'building') {
            const option = document.createElement('option');
            option.value = item.index_version;
            option.textContent = item.index_version;
            rollbackTarget.appendChild(option);
        }
    });
}

async function buildIndex() {
    const data = await apiJson('/admin/knowledge/index/build', { method: 'POST', body: JSON.stringify({ confirm: true }) });
    setStatus(`索引发布完成：${data.index_version}`);
    await refreshAll();
}

async function rollbackIndex() {
    if (!rollbackTarget.value) throw new Error('请先选择历史版本');
    if (!window.confirm(`确认回滚到 ${rollbackTarget.value} 吗？`)) return;
    const data = await apiJson('/admin/knowledge/index/rollback', {
        method: 'POST',
        body: JSON.stringify({ target: rollbackTarget.value }),
    });
    setStatus(`已回滚到 ${data.active_version}`);
    await refreshAll();
}

async function testRetrieval() {
    const query = document.getElementById('retrievalQuery').value.trim();
    if (!query) throw new Error('请输入检索问题');
    const data = await apiJson('/admin/knowledge/retrieval/test', {
        method: 'POST',
        body: JSON.stringify({ query, top_k: 4, access_groups: ['public'] }),
    });
    retrievalResult.textContent = JSON.stringify(data, null, 2);
}

async function loadAnalytics() {
    const data = await apiJson('/admin/knowledge/analytics');
    analyticsResult.textContent = JSON.stringify(data, null, 2);
}

async function refreshAll() {
    await loadDocuments();
    await loadBuilds();
    await loadAnalytics();
}

async function safeCall(callback) {
    try {
        await callback();
    } catch (error) {
        setStatus(error.message || '请求失败', true);
    }
}

document.getElementById('saveKnowledgeAuth').addEventListener('click', () => {
    knowledgeApiKey = knowledgeApiKeyInput.value.trim();
    localStorage.setItem('knowledgeApiKey', knowledgeApiKey);
    safeCall(refreshAll);
});
knowledgeFileInput.addEventListener('change', async () => {
    const file = knowledgeFileInput.files[0];
    if (!file) return;
    knowledgeTitleInput.value = knowledgeTitleInput.value || file.name.replace(/\.(txt|md)$/i, '');
    knowledgeContentInput.value = await file.text();
});
document.getElementById('uploadKnowledge').addEventListener('click', () => safeCall(uploadDocument));
document.getElementById('refreshKnowledge').addEventListener('click', () => safeCall(loadDocuments));
document.getElementById('buildKnowledge').addEventListener('click', () => safeCall(buildIndex));
document.getElementById('rollbackKnowledge').addEventListener('click', () => safeCall(rollbackIndex));
document.getElementById('testRetrieval').addEventListener('click', () => safeCall(testRetrieval));
document.getElementById('refreshAnalytics').addEventListener('click', () => safeCall(loadAnalytics));
safeCall(refreshAll);
