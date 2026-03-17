const chatMessages = document.getElementById('chatMessages');
const questionInput = document.getElementById('questionInput');
const sendBtn = document.getElementById('sendBtn');

// 添加消息到界面
function addMessage(text, isUser, stats = null) {
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
        const statsDiv = document.createElement('div');
        statsDiv.className = 'stats';
        statsDiv.textContent = `响应时间: ${stats.time}s  检索次数: ${stats.retrieval}`;
        contentWrapper.appendChild(statsDiv);
    }

    messageDiv.appendChild(avatar);
    messageDiv.appendChild(contentWrapper);
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// 显示“正在输入”指示器
function showTyping() {
    const typingDiv = document.createElement('div');
    typingDiv.className = 'message bot-message';
    typingDiv.id = 'typingIndicator';

    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = '🤖';

    const indicator = document.createElement('div');
    indicator.className = 'typing-indicator';
    indicator.innerHTML = '<span></span><span></span><span></span>';

    typingDiv.appendChild(avatar);
    typingDiv.appendChild(indicator);
    chatMessages.appendChild(typingDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function hideTyping() {
    const typing = document.getElementById('typingIndicator');
    if (typing) typing.remove();
}

// 发送问题
async function sendQuestion() {
    const question = questionInput.value.trim();
    if (!question) return;

    // 显示用户消息
    addMessage(question, true);
    questionInput.value = '';
    sendBtn.disabled = true;

    // 显示加载
    showTyping();

    try {
        const response = await fetch('http://localhost:5000/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question })
        });
        const data = await response.json();

        hideTyping();

        if (response.ok) {
            addMessage(data.answer, false, {
                time: data.response_time,
                retrieval: data.retrieval_count
            });
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

// 事件监听
sendBtn.addEventListener('click', sendQuestion);
questionInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendQuestion();
});