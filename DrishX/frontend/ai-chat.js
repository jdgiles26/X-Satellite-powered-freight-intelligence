/**
 * ARGUS Intelligence Chat Panel
 * Web-Worker-backed assistant UI for DrishX
 */
class AIChatPanel {
    constructor() {
        this.body = document.getElementById('ai-chat-body');
        this.drawer = document.getElementById('ai-chat-drawer');
        this.input = document.getElementById('ai-chat-input');
        this.sendBtn = document.getElementById('ai-chat-send');
        this.closeBtn = document.getElementById('close-chat');
        this.toggleBtn = document.getElementById('ai-chat-toggle');

        this.worker = new Worker('ai-worker.js', { type: 'module' });
        this.worker.onmessage = (e) => this.handleWorkerMessage(e.data);

        this.pending = new Map();
        this.msgId = 0;
        this.isTyping = false;

        this.renderQuickActions();
        this.bindEvents();
    }

    // ── UI Builders ──────────────────────────────────────────────────────────
    renderQuickActions() {
        const inputBar = this.drawer?.querySelector('.chat-input-bar');
        if (!inputBar) return;
        const existing = this.drawer.querySelector('.chat-quick-actions');
        if (existing) existing.remove();

        const actions = document.createElement('div');
        actions.className = 'chat-quick-actions';
        actions.innerHTML = `
            <button class="btn btn-hud-secondary btn-sm" data-action="summarize"><i class="fas fa-compress"></i> Summarize</button>
            <button class="btn btn-hud-secondary btn-sm" data-action="predict"><i class="fas fa-wind"></i> Predict</button>
            <button class="btn btn-hud-secondary btn-sm" data-action="correlate"><i class="fas fa-project-diagram"></i> Correlate</button>
            <button class="btn btn-hud-secondary btn-sm" data-action="explain"><i class="fas fa-brain"></i> Explain</button>
        `;
        inputBar.parentNode.insertBefore(actions, inputBar);

        actions.querySelectorAll('button[data-action]').forEach((btn) => {
            btn.addEventListener('click', () => this.handleQuickAction(btn.dataset.action));
        });
    }

    bindEvents() {
        this.sendBtn?.addEventListener('click', () => this.handleSend());
        this.input?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.handleSend();
        });
        this.closeBtn?.addEventListener('click', () => this.hide());
        this.toggleBtn?.addEventListener('click', () => this.toggle());
    }

    // ── Drawer controls ──────────────────────────────────────────────────────
    toggle() {
        this.drawer?.classList.toggle('hidden');
        if (!this.drawer?.classList.contains('hidden') && this.input) {
            this.input.focus();
        }
    }

    hide() {
        this.drawer?.classList.add('hidden');
    }

    // ── Messaging ────────────────────────────────────────────────────────────
    handleSend() {
        const text = this.input?.value.trim();
        if (!text) return;
        this.sendMessage(text);
        if (this.input) this.input.value = '';
    }

    async sendMessage(text) {
        this.addMessage('user', text);
        const typingId = this.addTypingIndicator();

        try {
            const resp = await fetch('/api/ai/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text })
            });

            this.removeTypingIndicator(typingId);

            if (!resp.ok) throw new Error('Backend error ' + resp.status);

            const contentType = resp.headers.get('content-type') || '';
            if (contentType.includes('application/json')) {
                const data = await resp.json();
                const reply = data.reply || data.message || JSON.stringify(data);
                await this.typeMessage('assistant', reply);
            } else {
                // Streaming / plain-text fallback
                const reader = resp.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';
                const msgEl = this.addMessage('assistant', '');

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    msgEl.textContent = buffer;
                    this.scrollToBottom();
                }
            }
        } catch (err) {
            this.removeTypingIndicator(typingId);
            this.addMessage('assistant', 'ARGUS Intelligence link offline. Analysis unavailable.');
            console.error('AI chat error:', err);
        }
    }

    // ── Worker analytics ─────────────────────────────────────────────────────
    async analyzeText(text) {
        try {
            const sentiment = await this.workerRequest('sentiment', { text });
            const labels = ['tactical', 'logistics', 'anomaly', 'forecast', 'threat'];
            const classification = await this.workerRequest('classify', { text, labels });
            this.displayAnalysisBadges(sentiment, classification);
        } catch (e) {
            console.error('Analysis error:', e);
        }
    }

    async getEmbedding(text) {
        return this.workerRequest('embed', { text });
    }

    workerRequest(type, payload) {
        return new Promise((resolve, reject) => {
            const id = ++this.msgId;
            this.pending.set(id, { resolve, reject });
            this.worker.postMessage({ id, type, ...payload });
        });
    }

    handleWorkerMessage(data) {
        const { id, type, result, embedding, error } = data;
        if (type === 'status') {
            this.showStatusBadge(result);
            return;
        }
        const pending = this.pending.get(id);
        if (!pending) return;
        this.pending.delete(id);
        if (error) pending.reject(new Error(error));
        else pending.resolve(result || embedding);
    }

    // ── Rendering helpers ────────────────────────────────────────────────────
    showStatusBadge(text) {
        if (!this.body) return;
        const badge = document.createElement('div');
        badge.className = 'chat-status-badge';
        badge.innerHTML = `<i class="fas fa-spinner fa-spin"></i> ${text}`;
        this.body.appendChild(badge);
        this.scrollToBottom();
        setTimeout(() => badge.remove(), 3000);
    }

    addMessage(role, text) {
        if (!this.body) return document.createElement('div');
        const msg = document.createElement('div');
        msg.className = `chat-message ${role}`;
        msg.textContent = text;
        this.body.appendChild(msg);
        this.scrollToBottom();
        return msg;
    }

    async typeMessage(role, text) {
        if (!this.body) return;
        const msg = document.createElement('div');
        msg.className = `chat-message ${role}`;
        this.body.appendChild(msg);
        this.scrollToBottom();

        this.isTyping = true;
        for (let i = 0; i < text.length; i++) {
            msg.textContent += text[i];
            this.scrollToBottom();
            await new Promise((r) => setTimeout(r, 8));
        }
        this.isTyping = false;
    }

    addTypingIndicator() {
        if (!this.body) return 0;
        const id = Date.now();
        const el = document.createElement('div');
        el.className = 'chat-message assistant typing-indicator';
        el.id = `typing-${id}`;
        el.innerHTML = '<span></span><span></span><span></span>';
        this.body.appendChild(el);
        this.scrollToBottom();
        return id;
    }

    removeTypingIndicator(id) {
        const el = document.getElementById(`typing-${id}`);
        if (el) el.remove();
    }

    scrollToBottom() {
        if (this.body) this.body.scrollTop = this.body.scrollHeight;
    }

    // ── Quick actions ────────────────────────────────────────────────────────
    handleQuickAction(action) {
        const queries = {
            summarize: 'Summarize current tactical intelligence and mission status.',
            predict: 'Predict freight logistics patterns for the next 14 days based on current data.',
            correlate: 'Correlate anomaly signals with corridor density and temporal trends.',
            explain: 'Explain the most recent detection anomalies and their spectral signatures.'
        };
        const text = queries[action];
        if (text) this.sendMessage(text);
    }

    displayAnalysisBadges(sentiment, classification) {
        if (!this.body) return;
        const wrapper = document.createElement('div');
        wrapper.className = 'analysis-badges';

        if (sentiment && sentiment[0]) {
            const s = sentiment[0];
            const color = s.label === 'POSITIVE' ? 'var(--accent-emerald)' : s.label === 'NEGATIVE' ? '#ef4444' : 'var(--accent-amber)';
            wrapper.innerHTML += `<span class="intel-badge" style="border-color:${color};color:${color}">${s.label} ${(s.score * 100).toFixed(0)}%</span>`;
        }

        if (classification && classification.labels && classification.scores) {
            const topIdx = classification.scores.indexOf(Math.max(...classification.scores));
            const topLabel = classification.labels[topIdx];
            const topScore = classification.scores[topIdx];
            wrapper.innerHTML += `<span class="intel-badge" style="border-color:var(--accent-blue);color:var(--accent-blue)">${topLabel} ${(topScore * 100).toFixed(0)}%</span>`;
        }

        this.body.appendChild(wrapper);
        this.scrollToBottom();
    }

    destroy() {
        this.worker.terminate();
    }
}
