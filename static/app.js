/*
 * app.js - NotebookMH 前端交互逻辑
 */

(function () {
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    const messagesDiv = document.getElementById('messages');
    const modeSwitch = document.getElementById('mode-switch');
    const teacherSelect = document.getElementById('teacher-select');
    const teacherBadge = document.getElementById('teacher-badge');
    const emotionBadge = document.getElementById('emotion-badge');

    let currentMode = 'adult';           // 'child' | 'adult'
    let currentTeacher = 'auto';         // 'socratic' | 'strict' | 'auto'
    let waitingForAnswer = false;        // 是否正在等待用户回答系统题目
    let isProcessing = false;

    const USER_ID = 'user_' + Math.random().toString(36).slice(2, 10);

    // ------------------------------------------------------------------
    // 事件绑定
    // ------------------------------------------------------------------
    sendBtn.addEventListener('click', onSend);
    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            onSend();
        }
    });
    userInput.addEventListener('input', autoResize);

    modeSwitch.addEventListener('change', () => {
        currentMode = modeSwitch.checked ? 'child' : 'adult';
        updateTeacherBadge();
        addMessage('system', `已切换到${currentMode === 'child' ? '儿童' : '成人'}模式`);
    });

    teacherSelect.addEventListener('change', () => {
        currentTeacher = teacherSelect.value;
        updateTeacherBadge();
        addMessage('system', `已切换到${teacherLabel(currentTeacher)}`);
    });

    // ------------------------------------------------------------------
    // 核心发送逻辑
    // ------------------------------------------------------------------
    async function onSend() {
        const text = userInput.value.trim();
        if (!text || isProcessing) return;

        addMessage('user', text);
        userInput.value = '';
        autoResize();
        isProcessing = true;
        sendBtn.disabled = true;
        const loadingId = addLoading();

        try {
            const payload = {
                user_id: USER_ID,
                query: text,
                mode: currentMode,
                teacher_type: currentTeacher,
                answer_to_question: waitingForAnswer ? text : '',
            };

            const res = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            if (!res.ok) throw new Error('网络错误 ' + res.status);
            const data = await res.json();
            removeLoading(loadingId);
            renderAssistantMessage(data);

            // 更新角色标签
            if (data.teacher_label) {
                teacherBadge.textContent = data.teacher_label;
            }

            // 如果有新题目，进入等待答题状态
            if (data.question) {
                waitingForAnswer = true;
            } else {
                waitingForAnswer = false;
            }
        } catch (err) {
            removeLoading(loadingId);
            addMessage('system', '抱歉，连接出错了，请稍后再试。');
            console.error(err);
        } finally {
            isProcessing = false;
            sendBtn.disabled = false;
            userInput.focus();
        }
    }

    // ------------------------------------------------------------------
    // 渲染助手消息
    // ------------------------------------------------------------------
    function renderAssistantMessage(data) {
        let html = `<div class="bubble">${escapeHtml(data.explanation)}</div>`;

        if (data.is_correct === true) {
            html += `<div class="correct-indicator">✓ 回答正确！${escapeHtml(data.encouragement || '')}</div>`;
        } else if (data.is_correct === false) {
            html += `<div class="wrong-indicator">✗ 再想想看。${escapeHtml(data.encouragement || '')}</div>`;
        }

        if (data.question) {
            html += `<div class="question-box">📝 ${escapeHtml(data.question)}</div>`;
        }
        if (data.hint) {
            html += `<div class="hint-box">💡 提示：${escapeHtml(data.hint)}</div>`;
        }
        if (data.encouragement && data.is_correct === undefined) {
            html += `<div class="encouragement">${escapeHtml(data.encouragement)}</div>`;
        }

        const wrapper = document.createElement('div');
        wrapper.className = 'message assistant';
        wrapper.innerHTML = html;
        messagesDiv.appendChild(wrapper);
        scrollToBottom();
    }

    // ------------------------------------------------------------------
    // 消息工具函数
    // ------------------------------------------------------------------
    function addMessage(role, text) {
        const div = document.createElement('div');
        div.className = `message ${role}`;
        div.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
        messagesDiv.appendChild(div);
        scrollToBottom();
    }

    function addLoading() {
        const id = 'loading-' + Date.now();
        const div = document.createElement('div');
        div.id = id;
        div.className = 'message assistant';
        div.innerHTML = `<div class="bubble loading-dots">正在思考</div>`;
        messagesDiv.appendChild(div);
        scrollToBottom();
        return id;
    }

    function removeLoading(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    function scrollToBottom() {
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    function autoResize() {
        userInput.style.height = 'auto';
        userInput.style.height = Math.min(userInput.scrollHeight, 120) + 'px';
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function teacherLabel(type) {
        const map = {
            'auto': '自适应',
            'socratic': '启发型',
            'strict': '严师型',
        };
        return map[type] || type;
    }

    function updateTeacherBadge() {
        const modeText = currentMode === 'child' ? '儿童' : '成人';
        const teacherText = teacherLabel(currentTeacher);
        teacherBadge.textContent = `${teacherText}·${modeText}`;
    }

    // ------------------------------------------------------------------
    // 主动提示轮询（每 15 秒检查一次思考空窗）
    // ------------------------------------------------------------------
    setInterval(async () => {
        if (!waitingForAnswer || isProcessing) return;
        try {
            const res = await fetch('/proactive', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: USER_ID }),
            });
            const data = await res.json();
            if (data.triggered) {
                addMessage('assistant', `${data.encouragement}\n${data.hint ? '提示：' + data.hint : ''}`);
            }
        } catch (e) {
            // 静默忽略轮询错误
        }
    }, 15000);
})();
