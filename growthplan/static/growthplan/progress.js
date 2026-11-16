(function () {
  'use strict';
  const listeners = new Set(), seen = new Set();
  let channel = null;
  try {if (typeof BroadcastChannel === 'function') channel = new BroadcastChannel('devdna-progress');} catch {}
  function receive(event) {
    if (!event || !event.event_id || seen.has(event.event_id)) return;
    seen.add(event.event_id); if (seen.size > 100) seen.delete(seen.values().next().value);
    listeners.forEach(listener => listener(event));
  }
  if (channel) channel.onmessage = event => receive(event.data);
  window.addEventListener('storage', event => {if (event.key === 'devdna-progress-event') {try {receive(JSON.parse(event.newValue));} catch {}}});
  async function json(url, options = {}) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 15000);
    try {const response = await fetch(url, {...options, cache: 'no-store', signal: controller.signal}); let data;
      try {data = await response.json();} catch {throw new Error('서버 응답을 확인하지 못했습니다.');}
      if (!response.ok) throw new Error(data.error || '저장한 학습 기록을 확인하지 못했습니다.'); return data;
    } catch (error) {if (error.name === 'AbortError') throw new Error('연결이 지연되고 있습니다. 다시 확인해 주세요.'); throw error;}
    finally {clearTimeout(timeout);}
  }
  function publish(roadmapId) {
    const event = {type: 'learning-progress', roadmap_id: roadmapId, event_id: `${Date.now()}-${Math.random()}`};
    if (channel) channel.postMessage(event);
    try {localStorage.setItem('devdna-progress-event', JSON.stringify(event));} catch {}
  }
  window.DevDNAProgress = {
    json, publish, subscribe(listener) {listeners.add(listener); return () => listeners.delete(listener);},
    async complete(taskId, completed) {
      const token = document.querySelector('[name=csrfmiddlewaretoken]');
      const data = await json(`/api/growthplan/tasks/${encodeURIComponent(taskId)}/completion/`, {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': token ? token.value : ''}, body: JSON.stringify({completed})});
      publish(data.roadmap_id); return data;
    },
    roadmap(id) {return json(`/api/growthplan/roadmaps/${encodeURIComponent(id)}/`);}
  };
})();
