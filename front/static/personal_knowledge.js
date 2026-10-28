const personalFile = document.getElementById('personalKnowledgeFile');
const personalTitle = document.getElementById('personalKnowledgeTitle');
const personalContent = document.getElementById('personalKnowledgeContent');
const personalStatus = document.getElementById('personalKnowledgeStatus');
const personalDocuments = document.getElementById('personalKnowledgeDocuments');
const personalSummary = document.getElementById('personalKnowledgeSummary');
const personalResult = document.getElementById('personalKnowledgeResult');

const accessToken = localStorage.getItem('accessToken');
const apiKey = localStorage.getItem('knowledgeApiKey') || '';
const fallbackUserId = localStorage.getItem('userId');

function headers() {
    const value = { 'Content-Type': 'application/json' };
    if (accessToken) value.Authorization = `Bearer ${accessToken}`;
    if (apiKey) value['X-API-Key'] = apiKey;
    if (!accessToken && fallbackUserId) value['X-User-ID'] = fallbackUserId;
    return value;
}

function status(message, error = false) {
    personalStatus.textContent = message;
    personalStatus.className = `knowledge-status${error ? ' error' : ''}`;
}

async function api(url, options = {}) {
    const response = await fetch(url, { ...options, headers: { ...headers(), ...(options.headers || {}) } });
    let data = {};
    try { data = await response.json(); } catch (_) { data = {}; }
    if (!response.ok) throw new Error(data.error || `请求失败（${response.status}）`);
    return data;
}

function actionButton(label, handler) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.addEventListener('click', handler);
    return button;
}

function renderDocuments(items) {
    personalDocuments.textContent = '';
    personalSummary.textContent = `共 ${items.length} 个个人文档；导入后会自动发布到你的私有索引。`;
    if (!items.length) {
        personalDocuments.textContent = '暂无个人文档。';
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
        [item.title || item.source_name, item.status, `v${item.latest_version}`, item.updated_at || '-'].forEach((value) => {
            const cell = document.createElement('td');
            cell.textContent = value;
            row.appendChild(cell);
        });
        const actions = document.createElement('td');
        actions.appendChild(actionButton('删除', async () => {
            if (!window.confirm(`确认删除“${item.title}”吗？`)) return;
            await api(`/me/knowledge/documents/${encodeURIComponent(item.id)}`, { method: 'DELETE' });
            status('文档已删除，并已从个人索引移除');
            await loadDocuments();
        }));
        row.appendChild(actions);
        table.appendChild(row);
    });
    personalDocuments.appendChild(table);
}

async function loadDocuments() {
    const data = await api('/me/knowledge/documents');
    renderDocuments(data.items || []);
}

async function importDocument() {
    const file = personalFile.files[0];
    const content = personalContent.value.trim();
    if (!content) throw new Error('请先选择文件或粘贴文档内容');
    const sourceName = file?.name || 'personal-note.md';
    const data = await api('/me/knowledge/documents', {
        method: 'POST',
        body: JSON.stringify({ source_name: sourceName, title: personalTitle.value.trim() || null, content }),
    });
    status(`导入完成：${data.build?.index_version || '-'}`);
    personalContent.value = '';
    personalFile.value = '';
    await loadDocuments();
}

async function testRetrieval() {
    const query = document.getElementById('personalKnowledgeQuery').value.trim();
    if (!query) throw new Error('请输入检索问题');
    const data = await api('/me/knowledge/retrieval/test', {
        method: 'POST',
        body: JSON.stringify({ query, top_k: 4 }),
    });
    personalResult.textContent = JSON.stringify(data, null, 2);
}

async function safeCall(callback) {
    try { await callback(); } catch (error) { status(error.message || '请求失败', true); }
}

personalFile.addEventListener('change', async () => {
    const file = personalFile.files[0];
    if (!file) return;
    personalTitle.value = personalTitle.value || file.name.replace(/\.(txt|md)$/i, '');
    personalContent.value = await file.text();
});
document.getElementById('importPersonalKnowledge').addEventListener('click', () => safeCall(importDocument));
document.getElementById('refreshPersonalKnowledge').addEventListener('click', () => safeCall(loadDocuments));
document.getElementById('testPersonalKnowledge').addEventListener('click', () => safeCall(testRetrieval));
safeCall(loadDocuments);
