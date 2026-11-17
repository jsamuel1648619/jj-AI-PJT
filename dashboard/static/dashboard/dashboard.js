'use strict';
const el = id => document.getElementById(id), store = window.DevDNAProgress;
let selected = new URLSearchParams(window.location.search).get('roadmap') || '', fetching = false, queued = false, changing = false, charts = [], fingerprint = '';
function text(id, value) {el(id).textContent = value;}
function status(message, error = false) {text('sync-status', message); el('sync-status').dataset.state = error ? 'error' : 'success';}
function sourceLink(container, url, label) {try {const parsed = new URL(url); if (!['http:', 'https:'].includes(parsed.protocol)) return; const link = document.createElement('a'); link.href = parsed.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = label; container.append(link);} catch {}}
function renderWeaknesses(data) {
  const scores = data.diagnosis ? data.diagnosis.scores : [];
  const assessed = scores.filter(item => Number.isFinite(item.score) && Number.isFinite(item.required_level));
  const weaknesses = assessed.map(item => ({...item, deficit: item.required_level - item.score})).filter(item => item.deficit > 0).sort((a, b) => b.deficit - a.deficit);
  const missing = scores.length - assessed.length;
  text('weakness-summary', !scores.length ? '진단을 완료하면 보완할 역량을 확인할 수 있습니다.' : !assessed.length ? '점수 또는 요구 수준이 없어 비교할 수 없습니다.' : weaknesses.length ? `보완할 역량 ${weaknesses.length}개 · 격차가 큰 상위 3개${missing ? ` · 미평가 또는 요구 수준 미확인 ${missing}개 제외` : ''}` : `평가된 역량은 모두 요구 수준에 도달했습니다.${missing ? ` 미평가 또는 요구 수준 미확인 ${missing}개는 별도로 확인하세요.` : ''}`);
  el('weakness-list').replaceChildren();
  weaknesses.slice(0, 3).forEach((item, index) => {
    const card = document.createElement('article'); card.className = 'weakness-card';
    const rank = document.createElement('span'); rank.className = 'section-badge'; rank.textContent = `보완 순위 ${index + 1}`;
    const title = document.createElement('h3'); title.textContent = item.name;
    const gap = document.createElement('strong'); gap.className = 'gap-value'; gap.textContent = `${Number(item.deficit.toFixed(2))}점 차이`;
    const levels = document.createElement('p'); levels.textContent = `현재 ${item.score} / 5 → 요구 ${item.required_level} / 5`;
    card.append(rank, title, gap, levels);
    if (item.evaluation_reason) {const reason = document.createElement('p'); reason.className = 'hint'; reason.textContent = item.evaluation_reason; card.append(reason);}
    el('weakness-list').append(card);
  });
}
function drawCharts(data) {
  charts.forEach(chart => chart.destroy()); charts = [];
  const scores = data.diagnosis ? data.diagnosis.scores : [], counts = Object.fromEntries(Object.entries(data.debugdna.categories).sort((a, b) => b[1] - a[1]));
  const entries = Object.entries(counts);
  text('mistake-summary', entries.length ? `최다 유형: ${entries[0][0]} · ${entries[0][1]}개 코드 쌍 (전체 분석 ${data.debugdna.analysis_count}개)` : '코드를 분석하면 반복되는 실수를 확인할 수 있습니다.');
  el('score-chart-wrap').hidden = !scores.length; el('mistake-chart-wrap').hidden = !Object.keys(counts).length;
  text('scores-empty', scores.length ? '' : '저장된 역량 진단 결과가 없습니다. SkillRadar에서 첫 진단을 시작하세요.');
  text('mistakes-empty', Object.keys(counts).length ? '' : '저장된 실수 유형이 없습니다. DebugDNA에서 분석한 오류를 이곳에서 확인할 수 있습니다.');
  el('scores-details').hidden = !scores.length; el('scores-table').replaceChildren();
  scores.forEach(item => {const row = document.createElement('tr'); [item.name, item.score === null ? '미평가' : `${item.score} / 5`, item.required_level === null ? '미확인' : `${item.required_level} / 5`].forEach(value => {const cell = document.createElement('td'); cell.textContent = value; row.append(cell);}); el('scores-table').append(row);});
  el('mistakes-list').replaceChildren(); Object.entries(counts).forEach(([name, count]) => {const item = document.createElement('li'); item.textContent = `${name}: ${count}개 코드 쌍`; el('mistakes-list').append(item);});
  if (!window.Chart) {el('score-chart-wrap').hidden = true; el('mistake-chart-wrap').hidden = true; if (scores.length) text('scores-empty', '차트를 불러오지 못했습니다. 점수 표에서 확인하세요.'); return;}
  if (scores.length) charts.push(new Chart(el('scores-chart'), {type: 'radar', data: {labels: scores.map(x => x.name), datasets: [{label: '진단 점수', data: scores.map(x => x.score), borderColor: '#c4f044', backgroundColor: '#c4f04422'}, {label: '직무 요구 수준', data: scores.map(x => x.required_level), borderColor: '#89909e', backgroundColor: '#89909e22'}]}, options: {responsive: true, maintainAspectRatio: false, scales: {r: {min: 0, max: 5, ticks: {stepSize: 1, color: '#858c9a', backdropColor: 'transparent'}, grid: {color: '#343844'}, angleLines: {color: '#343844'}, pointLabels: {color: '#b7bdc8'}, pointLabels: {color: '#e8edf5'}}}}}));
  if (Object.keys(counts).length) charts.push(new Chart(el('mistakes-chart'), {type: 'bar', data: {labels: Object.keys(counts), datasets: [{label: '오류 관찰 코드 쌍 수', data: Object.values(counts), backgroundColor: '#ff884d'}]}, options: {responsive: true, maintainAspectRatio: false, indexAxis: 'y', plugins: {legend: {display: false}}, scales: {x: {beginAtZero: true, ticks: {precision: 0, color: '#afbdd0'}}, y: {ticks: {color: '#e8edf5'}}}}}));
}
async function complete(task, value, control) {
  if (changing) {if (control.type === 'checkbox') control.checked = task.completed; return;}
  changing = true; controls(true); text('task-status', value ? '과제 완료를 저장하고 있습니다…' : '완료 취소를 저장하고 있습니다…');
  try {await store.complete(task.id, value); text('task-status', value ? '과제 완료를 저장했습니다.' : '완료를 취소했습니다.'); el('task-status').dataset.state = 'success';}
  catch (error) {if (control.type === 'checkbox') control.checked = task.completed; text('task-status', error.message); el('task-status').dataset.state = 'error';}
  finally {changing = false; controls(false); await refresh();}
}
function controls(disabled) {document.querySelectorAll('.task-control').forEach(control => {control.disabled = disabled;}); el('roadmap-select').disabled = disabled || !el('roadmap-select').options.length || el('roadmap-select').value === '';}
function renderTasks(data) {
  el('priority-tasks').replaceChildren(); el('task-list').replaceChildren();
  const plan = data.roadmap;
  if (!plan) {text('priority-tasks', '저장된 학습 계획이 없습니다. 진단 결과로 GrowthPlan을 생성하거나 직접 학습 목표를 설정하세요.'); el('all-tasks').hidden = true; return;}
  if (!data.priority_tasks.length) text('priority-tasks', plan.tasks.length ? '이 계획의 모든 과제를 완료했습니다. 진단을 다시 받아 다음 목표를 정해 보세요.' : '이 계획에는 배정된 과제가 없습니다. 목표 수준과 기간을 확인하세요.');
  data.priority_tasks.forEach((task, index) => {
    const card = document.createElement('article'); card.className = 'task-card'; const title = document.createElement('h3'); title.textContent = `${index === 0 ? '먼저 시작 · ' : ''}${task.week}주차 · ${task.skill}`;
    const objective = document.createElement('p'); objective.textContent = task.objective;
    const exercise = document.createElement('p'); exercise.textContent = `실습: ${task.exercise}`;
    const row = document.createElement('div'); row.className = 'task-actions'; const basis = document.createElement('small'); basis.textContent = `${task.hours}시간 계획${task.debug_boost ? ' · DebugDNA 우선순위 가산 ' + task.debug_boost : ''}`;
    const button = document.createElement('button'); button.type = 'button'; button.className = 'task-control'; button.dataset.taskId = task.id; button.textContent = '과제 완료'; button.onclick = () => complete(task, true, button);
    row.append(basis, button); card.append(title, objective, exercise, row); el('priority-tasks').append(card);
  });
  el('all-tasks').hidden = !plan.tasks.length;
  plan.tasks.forEach(task => {const row = document.createElement('div'); row.className = 'task-row' + (task.completed ? ' done' : ''); const label = document.createElement('label'); const check = document.createElement('input'); check.type = 'checkbox'; check.className = 'task-control'; check.dataset.taskId = task.id; check.checked = task.completed; check.onchange = () => complete(task, check.checked, check); const span = document.createElement('span'); span.textContent = `${task.week}주차 · ${task.skill} · ${task.objective}${task.completed ? ' (완료 · 체크 해제로 취소)' : ''}`; label.append(check, span); row.append(label); el('task-list').append(row);});
}
function render(data) {
  const job = data.target_job, plan = data.roadmap;
  text('target-title', job ? [job.company, job.division, job.role].filter(Boolean).join(' · ') || job.title || '저장된 채용공고' : '아직 저장한 목표 직무가 없습니다');
  text('target-detail', job ? job.title || (job.posting_excerpt ? '공고 원문: ' + job.posting_excerpt : '저장된 공고의 진단과 학습 계획입니다.') : 'SkillRadar에서 기업과 직무를 찾아 나의 역량을 진단하세요.');
  el('target-source').replaceChildren(); if (job && job.source_url) sourceLink(el('target-source'), job.source_url, '채용공고 출처 확인');
  text('diagnosis-count', data.diagnosis_count); text('analysis-count', data.debugdna.analysis_count);
  text('progress-percent', plan ? `${plan.progress.percent}%` : '—'); text('pending-count', plan ? plan.progress.total - plan.progress.completed : '—');
  el('learning-progress').hidden = !plan; el('learning-progress').value = plan ? plan.progress.percent : 0;
  text('progress-detail', plan ? `${plan.progress.completed} / ${plan.progress.total}개 과제 완료 · 완료 과제에 배정된 학습 시간 ${plan.progress.completed_planned_hours} / ${plan.progress.planned_hours}시간` : '학습 계획을 만들면 완료한 과제의 비율을 확인할 수 있습니다.');
  text('diagnosis-context', data.diagnosis ? `${data.diagnosis_matches_roadmap ? '선택한 계획과 연결된 진단' : '최근 완료한 진단'} · ${new Date(data.diagnosis.completed_at).toLocaleString('ko-KR')}` : '아직 완료한 진단이 없습니다.');
  el('diagnosis-link').href = data.diagnosis ? `/skillradar/?attempt=${data.diagnosis.attempt_id}` : '/skillradar/';
  el('plan-link').href = plan ? `/growthplan/?roadmap=${plan.roadmap_id}` : '/growthplan/';
  el('roadmap-select').replaceChildren();
  if (!data.roadmaps.length) el('roadmap-select').add(new Option('저장된 계획 없음', ''));
  data.roadmaps.forEach(item => el('roadmap-select').add(new Option(`${new Date(item.created_at).toLocaleString('ko-KR')} · ${item.target || '진단 기반 계획'} · ${item.total_weeks}주`, item.id)));
  if (plan) el('roadmap-select').value = plan.roadmap_id; el('roadmap-select').disabled = !plan || changing;
  renderWeaknesses(data); drawCharts(data); renderTasks(data);
  el('recent-analyses').replaceChildren();
  if (!data.recent_analyses.length) text('recent-analyses', '아직 코드 분석 이력이 없습니다.');
  data.recent_analyses.forEach(item => {const article = document.createElement('article'); const p = document.createElement('p'); p.textContent = `${new Date(item.created_at).toLocaleString('ko-KR')} · ${item.categories.join(', ') || '확인된 오류 없음'}`; const summary = document.createElement('p'); summary.textContent = item.summary; const link = document.createElement('a'); link.href = '/debugdna/'; link.textContent = 'DebugDNA에서 이력 확인 →'; article.append(p, summary, link); el('recent-analyses').append(article);});
}
async function refresh() {
  if (changing) return;
  if (fetching) {queued = true; return;}
  fetching = true; el('dashboard-content').setAttribute('aria-busy', 'true');
  const selection = selected;
  try {const data = await store.json('/api/dashboard/' + (selection ? '?roadmap=' + encodeURIComponent(selection) : '')); if (selection !== selected || changing) {queued = true; return;} const next = JSON.stringify({...data, updated_at: ''}); if (next !== fingerprint) {render(data); fingerprint = next;} status(`마지막 반영 ${new Date(data.updated_at).toLocaleTimeString('ko-KR')} · 자동 동기화`);}
  catch (error) {status(error.message + ' · 새로고침으로 다시 확인할 수 있습니다.', true);}
  finally {fetching = false; el('dashboard-content').setAttribute('aria-busy', 'false'); if (queued) {queued = false; refresh();}}
}
el('refresh').onclick = () => refresh();
el('roadmap-select').onchange = () => {selected = el('roadmap-select').value; const url = new URL(window.location.href); if (selected) url.searchParams.set('roadmap', selected); else url.searchParams.delete('roadmap'); history.replaceState(null, '', url); refresh();};
store.subscribe(() => refresh());
setInterval(() => {if (!document.hidden) refresh();}, 5000);
window.addEventListener('focus', () => refresh());
document.addEventListener('visibilitychange', () => {if (!document.hidden) refresh();});
refresh();
const drawerToggle = el('drawer-toggle'), drawerPanels = el('drawer-panels');
drawerToggle.onclick = () => {const expanded = drawerToggle.getAttribute('aria-expanded') === 'true'; drawerToggle.setAttribute('aria-expanded', String(!expanded)); drawerPanels.hidden = expanded; drawerToggle.querySelector('b').textContent = expanded ? '+' : '−';};
