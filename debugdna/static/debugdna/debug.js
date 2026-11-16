'use strict';
const el = id => document.getElementById(id);
let busy = false, current = null, shownHints = 0, charts = [];
async function api(url, body) {
  const options = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value}, body: JSON.stringify(body)};
  const controller = new AbortController(); options.signal = controller.signal; const timeout = setTimeout(() => controller.abort(), 120000);
  try {const response = await fetch(url, options); const data = await response.json(); if (!response.ok) throw new Error(data.error || '요청에 실패했습니다.'); return data;}
  catch (error) {if (error.name === 'AbortError') throw new Error('분석이 오래 걸리고 있습니다. 입력을 유지한 채 다시 시도하세요.'); throw error;}
  finally {clearTimeout(timeout);}
}
function message(id, text, state = '') {el(id).textContent = text; el(id).dataset.state = state;}
function renderResult(data) {
  current = data; shownHints = 0; el('result').hidden = false; el('hints').replaceChildren(); el('next-hint').disabled = false; el('next-hint').textContent = '첫 번째 힌트 보기';
  el('summary').textContent = `${data.source === 'qwen' ? 'AI 오류 분석' : '기본 구조 분석'} · ${data.summary}`;
  el('syntax').textContent = `수정 전: ${data.original.valid ? '문법 유효' : data.original.error} / 수정 후: ${data.corrected.valid ? '문법 유효' : data.corrected.error}`;
  el('findings').replaceChildren();
  data.findings.forEach(finding => {
    const card = document.createElement('article'); card.className = 'requirement'; const title = document.createElement('h3'); title.textContent = finding.category;
    [['오류 원인', finding.explanation], ['개선 근거', finding.improvement], ['관련 역량', finding.related_skills.join(', ')], ['연습 과제', finding.practice]].forEach(([label, value]) => {const p = document.createElement('p'); p.textContent = `${label}: ${value}`; card.append(p);});
    if (finding.original_evidence || finding.corrected_evidence) {const evidence = document.createElement('pre'); evidence.className = 'evidence'; evidence.textContent = `수정 전: ${finding.original_evidence}\n수정 후: ${finding.corrected_evidence}`; card.append(evidence);}
    card.prepend(title); el('findings').append(card);
  });
  if (!data.findings.length) {el('findings').textContent = '근거가 확인된 오류 유형이 없습니다. 입력·변경점·예상 동작을 다시 확인하세요.';}
  el('diff').textContent = data.diff || '코드 변경점이 없습니다.'; el('ast').textContent = JSON.stringify({original: data.original.structures, corrected: data.corrected.structures, changes: data.changes}, null, 2);
}
el('next-hint').onclick = () => {if (!current || shownHints >= current.hints.length) return; const hint = current.hints[shownHints++]; const li = document.createElement('li'); li.textContent = hint.text; el('hints').append(li); el('next-hint').disabled = shownHints === current.hints.length; el('next-hint').textContent = shownHints === current.hints.length ? '모든 힌트를 확인했습니다' : '다음 단계 힌트 보기';};
function renderInsights(insights, analyses) {
  el('insight-summary').textContent = `${insights.analysis_count}개 코드 쌍에서 ${Object.keys(insights.categories).length}개 실수 유형을 관찰했습니다.`;
  el('weak-skills').replaceChildren();
  insights.weak_skills.forEach(skill => {const card = document.createElement('article'); card.className = 'requirement'; const title = document.createElement('h3'); title.textContent = `${skill.name} · 실수 관찰 ${skill.issue_count}건`; const p = document.createElement('p'); p.textContent = Object.entries(skill.categories).map(([name, count]) => `${name} ${count}회`).join(' · '); const note = document.createElement('p'); note.textContent = `GrowthPlan 우선순위 가산 ${skill.priority_boost} · 학습 과제: ${skill.practices.join(' / ')}`; card.append(title, p, note); el('weak-skills').append(card);});
  charts.forEach(chart => chart.destroy()); charts = []; el('chart-status').textContent = '';
  if (!window.Chart) {el('chart-status').textContent = '차트를 불러오지 못했습니다. 위 기록과 역량별 빈도를 확인하세요.'; return;}
  const chronological = [...analyses].reverse();
  charts.push(new Chart(el('categories'), {type: 'bar', data: {labels: Object.keys(insights.categories), datasets: [{label: '오류 관찰 코드 쌍 수', data: Object.values(insights.categories), backgroundColor: '#76dfc3'}]}, options: {responsive: true, maintainAspectRatio: false, scales: {y: {beginAtZero: true, ticks: {precision: 0}}}}}));
  charts.push(new Chart(el('trend'), {type: 'line', data: {labels: chronological.map(item => new Date(item.created_at).toLocaleDateString('ko-KR')), datasets: [{label: '분석별 실수 유형 수', data: chronological.map(item => item.categories.length), borderColor: '#76dfc3'}]}, options: {responsive: true, maintainAspectRatio: false, scales: {y: {beginAtZero: true, ticks: {precision: 0}}}}}));
}
async function history() {
  try {const data = await api('/api/debugdna/history/'); el('history').replaceChildren(); renderInsights(data.insights, data.analyses);
    data.analyses.forEach(item => {const card = document.createElement('article'); card.className = 'candidate'; const text = document.createElement('p'); text.textContent = `${new Date(item.created_at).toLocaleString('ko-KR')} · ${item.categories.join(', ') || '확인된 오류 없음'} · ${item.related_skills.join(', ')}`; const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary'; button.textContent = '분석 열기'; button.onclick = async () => {if (busy) return; try {const record = await api(`/api/debugdna/analyses/${item.id}/`); el('original').value = record.original_code; el('corrected').value = record.corrected_code; el('notes').value = record.notes; el('related-skills').value = (record.requested_skills || []).join(', '); el('use-llm').checked = record.source === 'qwen'; renderResult(record); el('result').scrollIntoView({block: 'start'});} catch (error) {message('history-status', error.message, 'error');}}; card.append(text, button); el('history').append(card);});
    message('history-status', data.analyses.length ? `${data.analyses.length}개 분석 기록을 불러왔습니다.` : '아직 저장된 분석 기록이 없습니다.');
  } catch (error) {message('history-status', error.message, 'error');}
}
el('load-history').onclick = () => {if (!busy) history();};
el('analysis-form').onsubmit = async event => {
  event.preventDefault(); if (busy) return; busy = true; el('analysis-controls').disabled = true; el('result').hidden = true; message('status', '코드 구조와 변경점을 분석하고 오류 원인을 확인하고 있습니다…');
  const related_skills = el('related-skills').value.split(',').map(name => name.trim()).filter(Boolean);
  try {const data = await api('/api/analyze/', {original: el('original').value, corrected: el('corrected').value, notes: el('notes').value, related_skills, use_llm: el('use-llm').checked}); renderResult(data); message('status', data.cached ? '동일한 입력의 저장된 분석입니다. 반복 빈도는 늘리지 않았습니다.' : '분석을 저장했습니다. 같은 세션의 성장 계획에 실수 기록을 반영합니다.', 'success'); await history();}
  catch (error) {message('status', error.message, 'error');}
  finally {busy = false; el('analysis-controls').disabled = false;}
};
async function loadSkills() {try {const data = await api('/api/debugdna/skills/'); el('skill-options').replaceChildren(); data.skills.forEach(name => el('skill-options').append(new Option(name, name))); if (data.attempt_id) {el('diagnosis-link').href = `/skillradar/?attempt=${encodeURIComponent(data.attempt_id)}`; el('diagnosis-link').textContent = '최근 SkillRadar 진단을 열고 성장 계획에 반영 →';}} catch {}}
window.addEventListener('load', () => {history(); loadSkills();});
