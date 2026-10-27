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

function addMessage(text, isUser, stats = null, options = []) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isUser ? 'user-message' : 'bot-message'}`;
    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = isUser ? '👤' : '🤖';
    const contentWrapper = document.createElement('div');
    contentWrapper.style.display = 'flex';
    contentWrapper.style.flexDirection = 'column';
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

    messageDiv.appendChild(avatar);
    messageDiv.appendChild(contentWrapper);
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
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
    if (conversationId) conversationSelect.value = conversationId;
}

async function openConversation(id) {
    conversationId = id;
    localStorage.setItem('conversationId', conversationId);
    const response = await apiFetch(`/conversations/${encodeURIComponent(id)}`);
    if (!response.ok) return;
    const data = await response.json();
    resetChat();
    (data.messages || []).forEach((message) => addMessage(message.content, message.role === 'user'));
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

async function sendQuestion(questionOverride = null) {
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
    sendBtn.disabled = true;
    showTyping();
    try {
        const response = await apiFetch('/ask', {
            method: 'POST',
            body: JSON.stringify({ question, user_id: userId, conversation_id: conversationId }),
        });
        const data = await response.json();
        hideTyping();
        if (response.ok) {
            addMessage(
                data.answer,
                false,
                { time: data.response_time, retrieval: data.retrieval_count, type: data.type },
                data.type === 'clarification' ? (data.options || []) : [],
            );
            await loadConversations();
        } else {
            addMessage(`出错了：${data.error || '未知错误'}`, false);
        }
    } catch (error) {
        hideTyping();
        addMessage('网络错误，请稍后重试。', false);
        console.error(error);
    } finally {
        sendBtn.disabled = false;
        questionInput.focus();
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
