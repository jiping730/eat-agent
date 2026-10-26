const chatMessages = document.getElementById('chatMessages');
const questionInput = document.getElementById('questionInput');
const sendBtn = document.getElementById('sendBtn');

// 添加消息到界面。追问响应可携带候选项，点击候选项会直接作为下一轮用户输入。
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
            // 对话中发送用户可读的标签，后端仍会通过 known_values 映射回内部值。
            button.dataset.value = String(option.label ?? option.value ?? '');
            button.addEventListener('click', () => {
                sendQuestion(button.dataset.value);
            });
            optionsDiv.appendChild(button);
        });
        contentWrapper.appendChild(optionsDiv);
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
async function sendQuestion(questionOverride = null) {
    const question = (questionOverride ?? questionInput.value).trim();
    if (!question) return;
    addMessage(question, true);
    questionInput.value = '';
    sendBtn.disabled = true;
    showTyping();

    // 获取或创建用户 ID（存储在 localStorage）
    let userId = localStorage.getItem('userId');
    if (!userId) {
        userId = crypto.randomUUID();   // 生成唯一 ID
        localStorage.setItem('userId', userId);
    }

    try {
        const response = await fetch('/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question, user_id: userId })
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
