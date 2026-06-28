import { pipeline } from 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.0.0';

// ── Cached pipelines (downloaded once) ───────────────────────────────────────
let sentimentPipe = null;
let zeroShotPipe = null;
let embedPipe = null;

async function getSentimentPipe() {
    if (!sentimentPipe) {
        self.postMessage({ type: 'status', message: 'Loading sentiment model…' });
        sentimentPipe = await pipeline('sentiment-analysis', 'Xenova/distilbert-base-uncased-finetuned-sst-2-english');
    }
    return sentimentPipe;
}

async function getZeroShotPipe() {
    if (!zeroShotPipe) {
        self.postMessage({ type: 'status', message: 'Loading zero-shot model…' });
        zeroShotPipe = await pipeline('zero-shot-classification', 'Xenova/nli-deberta-v3-small');
    }
    return zeroShotPipe;
}

async function getEmbedPipe() {
    if (!embedPipe) {
        self.postMessage({ type: 'status', message: 'Loading embedding model…' });
        embedPipe = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2');
    }
    return embedPipe;
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function serializeEmbedding(output) {
    // Transformers.js Tensor objects expose .tolist()
    if (output && typeof output.tolist === 'function') {
        const arr = output.tolist();
        return Array.isArray(arr[0]) ? arr[0] : arr;
    }
    // Raw nested arrays
    if (Array.isArray(output)) {
        if (Array.isArray(output[0])) return output[0];
        return output;
    }
    // Flat typed array fallback
    if (output && output.data) return Array.from(output.data);
    return output;
}

// ── Message router ───────────────────────────────────────────────────────────
self.onmessage = async (e) => {
    const { id, type, text, labels } = e.data;
    try {
        if (type === 'sentiment') {
            const pipe = await getSentimentPipe();
            const result = await pipe(text);
            self.postMessage({ id, type: 'sentiment', result });
        } else if (type === 'classify') {
            const pipe = await getZeroShotPipe();
            const result = await pipe(text, labels);
            self.postMessage({ id, type: 'classify', result });
        } else if (type === 'embed') {
            const pipe = await getEmbedPipe();
            const result = await pipe(text, { pooling: 'mean', normalize: true });
            const embedding = serializeEmbedding(result);
            self.postMessage({ id, type: 'embed', embedding });
        } else {
            self.postMessage({ id, type: 'error', error: 'Unknown message type: ' + type });
        }
    } catch (err) {
        self.postMessage({ id, type: 'error', error: err.message });
    }
};
