const chatMessages = document.getElementById('chatMessages');
const questionInput = document.getElementById('questionInput');
const sendBtn = document.getElementById('sendBtn');
const usernameInput = document.getElementById('usernameInput');
const passwordInput = document.getElementById('passwordInput');
const loginBtn = document.getElementById('loginBtn');
const registerBtn = document.getElementById('registerBtn');
const logoutBtn = document.getElementById('logoutBtn');
const authStatus = document.getElementById('authStatus');
const newConversationBtn = document.getElementById('newConversationBtn');
const conversationSelect = document.getElementById('conversationSelect');

let accessToken = localStorage.getItem('accessToken');
let refreshToken = localStorage.getItem('refreshToken');
let userId = localStorage.getItem('userId');
let conversationId = localStorage.getItem('conversationId');
let activeStreamController = null;

function addMessage(text, isUser, stats = null, options = [], metadata = {}) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isUser ? 'user-message' : 'bot-message'}`;
    if (metadata.id) messageDiv.dataset.messageId = String(metadata.id);
    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = isUser ? '👤' : '🤖';
    const contentWrapper = document.createElement('div');
    contentWrapper.className = 'message-content-wrapper';
    const content = document.createElement('div');
    content.className = 'content';
    content.textContent = text;
    contentWrapper.appendChild(content);

    if (stats && !isUser) {
        if (stats.type) {
            const statusDiv = document.createElement('div');
            statusDiv.className = `response-status ${stats.type}`;
            statusDiv.textContent = stats.type === 'clarification' ? '需要补充信息' : '已完成回答';
            contentWrapper.appendChild(statusDiv);
        }
        const statsDiv = document.createElement('div');
        statsDiv.className = 'stats';
        statsDiv.textContent = `响应时间: ${stats.time}s  检索次数: ${stats.retrieval}`;
        contentWrapper.appendChild(statsDiv);
    }

    if (!isUser && options.length) {
        const optionsDiv = document.createElement('div');
        optionsDiv.className = 'clarification-options';
        options.forEach((option) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'option-button';
            button.textContent = option.label || option.value;
            button.dataset.value = String(option.label ?? option.value ?? '');
            button.addEventListener('click', () => sendQuestion(button.dataset.value));
            optionsDiv.appendChild(button);
        });
        contentWrapper.appendChild(optionsDiv);
    }

    if (!isUser && (metadata.id || metadata.allowActions)) {
        appendMessageActions(contentWrapper, metadata.id, metadata.allowActions !== false);
    }

    messageDiv.appendChild(avatar);
    messageDiv.appendChild(contentWrapper);
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return { messageDiv, content, contentWrapper };
}

function appendMessageActions(wrapper, messageId, allowRegenerate = true) {
    const actions = document.createElement('div');
    actions.className = 'message-actions';
    const up = document.createElement('button');
    up.type = 'button';
    up.textContent = '有帮助';
    up.addEventListener('click', () => submitFeedback(messageId, 'up', actions));
    const down = document.createElement('button');
    down.type = 'button';
    down.textContent = '需改进';
    down.addEventListener('click', () => submitFeedback(messageId, 'down', actions));
    actions.appendChild(up);
    actions.appendChild(down);
    if (allowRegenerate) {
        const regenerate = document.createElement('button');
        regenerate.type = 'button';
        regenerate.textContent = '重新生成';
        regenerate.addEventListener('click', regenerateAnswer);
        actions.appendChild(regenerate);
    }
    wrapper.appendChild(actions);
}

function resetChat() {
    chatMessages.innerHTML = '';
    addMessage('你好！我是你的营养助手，可以帮你查询食物热量、推荐餐食组合。有什么可以帮你的吗？', false);
}

function showTyping() {
    const typingDiv = document.createElement('div');
    typingDiv.className = 'message bot-message';
    typingDiv.id = 'typingIndicator';
    typingDiv.innerHTML = '<div class="avatar">🤖</div><div class="typing-indicator"><span></span><span></span><span></span></div>';
    chatMessages.appendChild(typingDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function hideTyping() {
    const typing = document.getElementById('typingIndicator');
    if (typing) typing.remove();
}

function persistTokens(data) {
    accessToken = data.access_token;
    refreshToken = data.refresh_token;
    userId = data.user?.id || userId;
    localStorage.setItem('accessToken', accessToken);
    localStorage.setItem('refreshToken', refreshToken);
    if (userId) localStorage.setItem('userId', userId);
    updateAuthUi(data.user);
}

function clearTokens() {
    accessToken = null;
    refreshToken = null;
    localStorage.removeItem('accessToken');
    localStorage.removeItem('refreshToken');
    updateAuthUi(null);
}

function updateAuthUi(user = null) {
    const loggedIn = Boolean(accessToken);
    loginBtn.hidden = loggedIn;
    registerBtn.hidden = loggedIn;
    logoutBtn.hidden = !loggedIn;
    usernameInput.hidden = loggedIn;
    passwordInput.hidden = loggedIn;
    authStatus.textContent = user ? `已登录：${user.username}` : (loggedIn ? '已登录' : '开发模式');
}

async function apiFetch(url, options = {}, retry = true) {
    const headers = new Headers(options.headers || {});
    if (!headers.has('Content-Type') && options.body) headers.set('Content-Type', 'application/json');
    if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
    if (!accessToken && userId) headers.set('X-User-ID', userId);
    const response = await fetch(url, { ...options, headers });

    if (response.status === 401 && retry && refreshToken) {
        const refreshResponse = await fetch('/auth/refresh', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (refreshResponse.ok) {
            persistTokens(await refreshResponse.json());
            return apiFetch(url, options, false);
        }
        clearTokens();
    }
    return response;
}

async function authenticate(path) {
    const username = usernameInput.value.trim();
    const password = passwordInput.value;
    if (!username || !password) {
        authStatus.textContent = '请输入用户名和密码';
        return;
    }
    const response = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
    });
    const data = await response.json();
    if (!response.ok) {
        authStatus.textContent = data.error || '认证失败';
        return;
    }
    persistTokens(data);
    passwordInput.value = '';
    await loadConversations();
}

async function loadConversations() {
    if (!accessToken && !userId) return;
    const response = await apiFetch('/conversations');
    if (!response.ok) return;
    const data = await response.json();
    conversationSelect.innerHTML = '<option value="">当前会话</option>';
    (data.items || []).forEach((item) => {
        const option = document.createElement('option');
        option.value = item.id;
        option.textContent = item.title || item.id.slice(0, 8);
        conversationSelect.appendChild(option);
    });
    if (conversationId) {
        conversationSelect.value = conversationId;
        if (conversationSelect.value === conversationId) await openConversation(conversationId);
    }
}

async function openConversation(id) {
    conversationId = id;
    localStorage.setItem('conversationId', conversationId);
    const response = await apiFetch(`/conversations/${encodeURIComponent(id)}`);
    if (!response.ok) return;
    const data = await response.json();
    resetChat();
    (data.messages || []).forEach((message) => addMessage(
        message.content,
        message.role === 'user',
        message.role === 'assistant' && message.response_type ? {
            time: '-',
            retrieval: '-',
            type: message.response_type,
        } : null,
        [],
        { id: message.id, allowActions: message.role === 'assistant' },
    ));
}

async function createConversation() {
    const response = await apiFetch('/conversations', {
        method: 'POST',
        body: JSON.stringify({ title: '新会话' }),
    });
    if (response.ok) {
        const data = await response.json();
        conversationId = data.id;
    } else {
        conversationId = crypto.randomUUID();
    }
    localStorage.setItem('conversationId', conversationId);
    resetChat();
    await loadConversations();
}

function stageLabel(stage) {
    const labels = {
        understanding: '正在理解你的问题…',
        answer: '正在整理回答…',
        memory: '正在读取相关上下文…',
    };
    return labels[stage] || '正在处理…';
}

function createStreamingMessage() {
    const result = addMessage('', false, null, [], { allowActions: false });
    const status = document.createElement('div');
    status.className = 'stream-status';
    status.textContent = '正在理解你的问题…';
    result.contentWrapper.appendChild(status);
    result.status = status;
    return result;
}

function updateStreamStatus(result, text) {
    if (!result) return;
    result.status.textContent = text;
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function finalizeStreamingMessage(result, response) {
    if (!result || !response) return;
    result.content.textContent = response.answer || result.content.textContent;
    result.status.className = `response-status ${response.type || 'answer'}`;
    result.status.textContent = response.type === 'clarification' ? '需要补充信息' : '已完成回答';
    const stats = document.createElement('div');
    stats.className = 'stats';
    stats.textContent = `响应时间: ${response.response_time ?? '-'}s  检索次数: ${response.retrieval_count ?? '-'}`;
    result.contentWrapper.appendChild(stats);
    if (response.type === 'clarification' && (response.options || []).length) {
        const optionsDiv = document.createElement('div');
        optionsDiv.className = 'clarification-options';
        (response.options || []).forEach((option) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'option-button';
            button.textContent = option.label || option.value;
            button.addEventListener('click', () => sendQuestion(String(option.label ?? option.value ?? '')));
            optionsDiv.appendChild(button);
        });
        result.contentWrapper.appendChild(optionsDiv);
    }
    appendMessageActions(result.contentWrapper, response.message_id, true);
}

function parseSseBuffer(buffer) {
    const frames = buffer.split('\n\n');
    return { frames: frames.slice(0, -1), remainder: frames[frames.length - 1] };
}

async function consumeSse(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parsed = parseSseBuffer(buffer);
        buffer = parsed.remainder;
        for (const frame of parsed.frames) {
            const dataLine = frame.split('\n').find((line) => line.startsWith('data: '));
            if (!dataLine) continue;
            try {
                await onEvent(JSON.parse(dataLine.slice(6)));
            } catch (error) {
                console.error('无法解析 SSE 事件', error, frame);
            }
        }
    }
}

async function sendQuestion(questionOverride = null) {
    if (activeStreamController) {
        activeStreamController.abort();
        return;
    }
    const question = (questionOverride ?? questionInput.value).trim();
    if (!question) return;
    if (!userId) {
        userId = crypto.randomUUID();
        localStorage.setItem('userId', userId);
    }
    if (!conversationId) {
        conversationId = crypto.randomUUID();
        localStorage.setItem('conversationId', conversationId);
    }

    addMessage(question, true);
    questionInput.value = '';
    sendBtn.disabled = false;
    sendBtn.textContent = '停止';
    const controller = new AbortController();
    activeStreamController = controller;
    const result = createStreamingMessage();
    let finalResponse = null;
    try {
        const response = await apiFetch('/ask/stream', {
            method: 'POST',
            body: JSON.stringify({ question, user_id: userId, conversation_id: conversationId }),
            signal: controller.signal,
        });
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || '请求失败');
        }
        await consumeSse(response, async (event) => {
            const data = event.data || {};
            if (event.event === 'model.started') updateStreamStatus(result, stageLabel(data.stage));
            if (event.event === 'retrieval.started') updateStreamStatus(result, '正在检索相关资料…');
            if (event.event === 'retrieval.completed') updateStreamStatus(result, '已完成资料检索，正在整理…');
            if (event.event === 'tool.started') updateStreamStatus(result, `正在调用 ${data.tool || '工具'}…`);
            if (event.event === 'tool.completed') updateStreamStatus(result, '工具处理完成，正在生成回答…');
            if (event.event === 'grill.clarify') updateStreamStatus(result, '正在确认还需要哪些信息…');
            if (event.event === 'model.delta' && data.delta) {
                result.content.textContent += data.delta;
                updateStreamStatus(result, '正在生成回答…');
            }
            if (event.event === 'answer.completed') finalResponse = data;
            if (event.event === 'error') {
                if (data.code === 'cancelled') updateStreamStatus(result, '已停止生成');
                else throw new Error(data.message || '回答生成失败');
            }
        });
        if (finalResponse) finalizeStreamingMessage(result, finalResponse);
        else if (!result.content.textContent) updateStreamStatus(result, '回答未完成，请重试');
        await loadConversations();
    } catch (error) {
        if (error.name === 'AbortError') {
            updateStreamStatus(result, '已停止生成');
        } else {
            result.content.textContent = `出错了：${error.message || '网络错误'}`;
            updateStreamStatus(result, '请求失败');
            console.error(error);
        }
    } finally {
        activeStreamController = null;
        sendBtn.textContent = '发送';
        sendBtn.disabled = false;
        questionInput.focus();
    }
}

async function regenerateAnswer() {
    if (!conversationId || activeStreamController) return;
    const response = await apiFetch(`/conversations/${encodeURIComponent(conversationId)}/regenerate`, { method: 'POST' });
    const data = await response.json();
    if (!response.ok) {
        addMessage(`重新生成失败：${data.error || '未知错误'}`, false);
        return;
    }
    addMessage(data.answer, false, {
        time: data.response_time,
        retrieval: data.retrieval_count,
        type: data.type,
    }, data.type === 'clarification' ? (data.options || []) : [], { id: data.message_id, allowActions: true });
    await loadConversations();
}

async function submitFeedback(messageId, rating, actions) {
    if (!messageId) {
        actions.dataset.feedback = rating;
        actions.querySelectorAll('button').forEach((button) => { button.disabled = true; });
        return;
    }
    const response = await apiFetch(`/messages/${encodeURIComponent(messageId)}/feedback`, {
        method: 'POST',
        body: JSON.stringify({ rating }),
    });
    if (response.ok) {
        actions.dataset.feedback = rating;
        actions.querySelectorAll('button').forEach((button) => { button.disabled = true; });
    }
}

loginBtn.addEventListener('click', () => authenticate('/auth/login'));
registerBtn.addEventListener('click', () => authenticate('/auth/register'));
logoutBtn.addEventListener('click', async () => {
    await fetch('/auth/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
    });
    clearTokens();
});
newConversationBtn.addEventListener('click', createConversation);
conversationSelect.addEventListener('change', () => {
    if (conversationSelect.value) openConversation(conversationSelect.value);
});
sendBtn.addEventListener('click', () => sendQuestion());
questionInput.addEventListener('keypress', (event) => {
    if (event.key === 'Enter') sendQuestion();
});

updateAuthUi();
loadConversations();
