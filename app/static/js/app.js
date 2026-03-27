/* 커머스리뷰 — 프론트엔드 JS */

function detectPlatform(url) {
    if (!url) return null;
    if (url.includes('douyin.com') || url.includes('v.douyin.com')) return 'douyin';
    if (url.includes('xiaohongshu.com') || url.includes('xhslink.com')) return 'xiaohongshu';
    if (url.includes('1688.com')) return '1688';
    return null;
}

const platformNames = {douyin:'더우인', xiaohongshu:'샤오홍슈', '1688':'1688'};
const statusNames = {pending:'대기',downloading:'다운로드',transcribing:'자막추출',translating:'번역중',rendering:'렌더링',done:'완료',error:'오류'};

function pollJobStatus(jobId, cb) {
    const poll = async () => {
        try {
            const r = await fetch('/api/jobs/' + jobId + '/status');
            const d = await r.json();
            cb(d);
            if (d.status !== 'done' && d.status !== 'error') setTimeout(poll, 3000);
        } catch(e) { setTimeout(poll, 5000); }
    };
    poll();
}

function showAlert(msg, type) {
    const colors = {info:'bg-blue-600',success:'bg-green-600',error:'bg-red-600'};
    const el = document.createElement('div');
    el.className = 'fixed top-4 left-1/2 -translate-x-1/2 ' + (colors[type]||colors.info) + ' text-white px-6 py-3 rounded-lg shadow-lg z-50';
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
}
