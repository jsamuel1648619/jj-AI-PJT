'use strict';
const el = id => document.getElementById(id);
const kinds = {required: '필수', preferred: '우대', unspecified: '관련 역량'};
const levels = ['경험 없음', '입문', '기초 실습', '프로젝트 활용', '독립적 문제 해결', '설계·최적화·리딩'];
const state = {step: 1, busy: false, body: '', source: '', title: '', extracted: null, diagnosis: null, attempt: null, evaluated: null, plan: null, planInput: null, charts: [], statuses: ['진행 중', '대기', '대기', '대기']};

function canVisit(step) {return step === 1 || (step === 2 && !!state.body) || (step === 3 && !!state.extracted) || (step === 4 && !!state.evaluated);}
function updateSteps() {
  document.querySelectorAll('[data-step]').forEach(button => {
    const step = Number(button.dataset.step);
    button.disabled = state.busy || !canVisit(step);
    button.classList.toggle('complete', state.statuses[step - 1] === '완료');
    if (step === state.step) button.setAttribute('aria-current', 'step'); else button.removeAttribute('aria-current');
    el(`step-status-${step}`).textContent = state.statuses[step - 1];
  });
}
function goStep(step, internal = false) {
  if ((!internal && state.busy) || !canVisit(step)) return;
  state.step = step;
  for (let index = 1; index <= 4; index++) el(`step-${index}`).hidden = index !== step;
  updateSteps();
  document.querySelectorAll('.pane').forEach(pane => pane.setAttribute('aria-busy', String(state.busy && pane.id === `step-${step}`)));
  el(`heading-${step}`).focus({preventScroll: true});
  el(`step-${step}`).scrollIntoView({block: 'start', behavior: 'instant'});
  if (!state.busy) el('workflow-status').textContent = [`기업과 직무를 입력하거나 공고를 선택하세요.`, '분석 결과를 확인하고 나의 역량 평가로 이어가세요.', '진단 질문에 답변하고 역량별 점수를 확인하세요.', '학습 목표를 확인하고 성장 계획을 생성하세요.'][step - 1];
}
function busy(value, message = '') {
  state.busy = value;
  document.querySelectorAll('fieldset.controls').forEach(fieldset => {fieldset.disabled = value;});
  el('workflow-status').dataset.busy = String(value);
  if (message) el('workflow-status').textContent = message;
  document.querySelectorAll('.pane').forEach(pane => pane.setAttribute('aria-busy', String(value && pane.id === `step-${state.step}`)));
  updateSteps();
}
function status(id, message, kind = '') {el(id).textContent = message; el(id).dataset.state = kind;}
async function post(url, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 120000);
  try {
    const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value}, body: JSON.stringify(body), signal: controller.signal});
    let data;
    try {data = await response.json();} catch {throw new Error('응답을 읽지 못했습니다. 잠시 후 다시 시도해 주세요.');}
    if (!response.ok) {const error = new Error(data.error || '요청에 실패했습니다.'); error.status = response.status; throw error;}
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('처리가 오래 걸리고 있습니다. 잠시 후 다시 시도해 주세요.');
    if (error instanceof TypeError) throw new Error('연결이 끊어졌습니다. 연결을 확인하고 다시 시도해 주세요.');
    throw error;
  } finally {clearTimeout(timer);}
}
function analysisError(error) {
  return error.status === 503 ? '분석 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.' : error.status === 502 ? '분석 결과를 확인하지 못했습니다. 다시 시도하거나 공고 본문을 확인해 주세요.' : error.message;
}
function destroyCharts() {state.charts.forEach(chart => chart.destroy()); state.charts = [];}
function resetPlan() {
  state.plan = null; state.planInput = null; state.statuses[3] = state.evaluated ? '생성 대기' : '대기'; el('roadmap').hidden = true;
  el('generate').textContent = '맞춤 성장 계획 생성'; el('heading-4').textContent = '이제, 나만의 성장 계획을 만들어요';
  el('plan-defaults').textContent = `${el('plan-weeks').value || '—'}주 · 주 ${el('plan-hours').value || '—'}시간`;
  status('plan-status', ''); updateSteps();
}
function resetEvaluation(dropAttempt = true) {
  if (dropAttempt) state.attempt = null;
  state.evaluated = null; state.statuses[2] = state.extracted ? '평가 대기' : '대기';
  el('result').hidden = true; destroyCharts(); resetPlan();
}
function resetAnalysis() {
  state.diagnosis = null; el('evaluate').hidden = true; el('retry-questions').hidden = true; status('question-status', '');
  state.extracted = null; state.statuses[1] = '대기';
  el('requirements').replaceChildren(); el('analysis-summary').replaceChildren();
  el('to-assessment').hidden = true; el('analyze').hidden = true;
  resetEvaluation(); status('analysis-status', '');
}
function resetSearch() {
  if (state.busy) return;
  state.body = ''; state.source = ''; state.title = ''; state.statuses[0] = '진행 중';
  el('candidates').replaceChildren(); resetAnalysis(); status('collection-status', '');
}
document.querySelectorAll('[data-step]').forEach(button => {button.onclick = () => Number(button.dataset.step) === 3 ? openDiagnosis() : goStep(Number(button.dataset.step));});
['company', 'division', 'role'].forEach(id => el(id).addEventListener('input', resetSearch));
['posting', 'source-url', 'job-url'].forEach(id => el(id).addEventListener('input', resetSearch));
el('analysis-back').onclick = () => goStep(1);
el('assessment-back').onclick = () => goStep(2);
el('plan-back').onclick = () => goStep(3);
el('to-assessment').onclick = () => openDiagnosis();

function showPosting(data) {
  state.body = data.body; state.source = data.source_url || ''; state.title = data.title || '직접 입력한 채용공고';
  state.statuses[0] = '완료';
  el('posting').value = state.body; el('source-url').value = state.source;
  el('job-context').textContent = state.title;
  el('provenance').textContent = data.collected_at ? `수집 완료 · ${new Date(data.collected_at).toLocaleString('ko-KR')}${data.truncated ? ' · 공고가 길어 일부만 분석합니다.' : ''}` : '직접 입력한 본문으로 분석합니다.';
  el('posting-preview').textContent = state.body;
  const link = el('source-link'); link.hidden = true; link.removeAttribute('href');
  try {const url = new URL(state.source); if (['http:', 'https:'].includes(url.protocol)) {link.href = url.href; link.hidden = false;}} catch {}
  goStep(2, true);
}
function renderRequirements(data) {
  el('analysis-summary').replaceChildren();
  [[data.summary.total, '요구 역량'], [data.summary.required, '필수 역량']].forEach(([count, label]) => {
    const metric = document.createElement('div'); metric.className = 'metric';
    const number = document.createElement('strong'); number.textContent = count; metric.append(number, document.createTextNode(label)); el('analysis-summary').append(metric);
  });
  el('requirements').replaceChildren();
  data.requirements.forEach(item => {
    const card = document.createElement('article'); card.className = 'requirement';
    const title = document.createElement('h3'); title.textContent = `${item.name} · ${kinds[item.importance]}`;
    const level = document.createElement('p'); level.textContent = item.required_level === null ? '요구 수준을 판단할 근거가 부족합니다. 학습 목표는 나중에 선택할 수 있어요.' : `요구 수준 ${item.required_level} · ${levels[item.required_level]}${item.level_basis === 'inferred' ? ' (AI 해석)' : ' (공고 명시)'}`;
    const details = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = '분석 근거 보기';
    const quote = document.createElement('blockquote'); quote.textContent = item.evidence;
    const reason = document.createElement('p'); reason.textContent = [item.level_reason, item.level_evidence ? `수준 근거: ${item.level_evidence}` : '', item.weight_reason ? `중요도 판단: ${item.weight_reason}` : ''].filter(Boolean).join('\n');
    details.append(summary, quote, reason); card.append(title, level, details); el('requirements').append(card);
  });
}
function renderAssessment() {
  el('skill-inputs').replaceChildren();
  const requirements = new Map(state.diagnosis.requirements.map(item => [item.skill_id, item]));
  state.diagnosis.questions.forEach((question, index) => {
    const item = requirements.get(question.skill_id);
    const card = document.createElement('article'); card.className = 'skill-card'; card.dataset.name = item.name; card.dataset.skillId = question.skill_id;
    const head = document.createElement('div'); head.className = 'skill-head';
    const title = document.createElement('h3'); title.textContent = item.name;
    const hint = document.createElement('small'); hint.textContent = `${kinds[item.importance]} · 요구 수준 ${item.required_level ?? '미확인'}`; head.append(title, hint);
    const prompt = document.createElement('p'); prompt.textContent = question.question;
    const guidance = document.createElement('small'); guidance.textContent = question.answer_guidance;
    const label = document.createElement('label'); label.textContent = '나의 답변'; label.htmlFor = `answer-${index}`;
    const answer = document.createElement('textarea'); answer.id = label.htmlFor; answer.className = 'diagnosis-answer'; answer.rows = 4; answer.maxLength = 3000; answer.placeholder = '어떻게 해결할지, 이유와 검증 방법을 설명해 주세요.';
    const details = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = '이 역량의 평가 기준 보기'; details.append(summary);
    question.rubric.forEach(criterion => {const p = document.createElement('p'); p.textContent = `${criterion.level}점: ${criterion.description}`; details.append(p);});
    card.append(head, prompt, guidance, label, answer, details); el('skill-inputs').append(card);
    answer.oninput = () => {resetEvaluation(); const count = Array.from(document.querySelectorAll('.diagnosis-answer')).filter(input => input.value.trim()).length; status('evaluation-status', `${count} / ${state.diagnosis.total}개 답변 입력 · 비운 답변은 미평가로 남습니다.`);};
  });
}

function requirementPayload() {
  return state.extracted.requirements.map(({name, importance, evidence, required_level, level_basis, level_reason, level_evidence, weight, weight_reason}) => ({name, importance, evidence, required_level, level_basis, level_reason, level_evidence, weight, weight_reason}));
}
async function openDiagnosis() {
  if (state.busy || !state.extracted) return;
  goStep(3);
  if (state.diagnosis && state.diagnosis.ready) return;
  busy(true, '3 / 4 · 직무 역량별 진단 질문과 평가 기준을 만들고 있습니다.');
  state.statuses[2] = '질문 생성 중'; el('retry-questions').hidden = true; el('evaluate').hidden = true;
  try {
    if (!state.diagnosis) state.diagnosis = await post('/api/skillradar/diagnoses/', {job_posting: state.body, source_url: state.source, requirements: requirementPayload(), use_llm: true, company: el('company').value, division: el('division').value, role: el('role').value, job_title: state.title});
    while (!state.diagnosis.ready) {
      const before = state.diagnosis.generated;
      status('question-status', `진단 질문 생성 중 · ${before} / ${state.diagnosis.total}개`);
      const data = await post(`/api/skillradar/diagnoses/${state.diagnosis.id}/questions/`, {});
      if (data.generated <= before) throw new Error('질문을 더 생성하지 못했습니다. 다시 시도해 주세요.');
      state.diagnosis = data;
    }
    renderAssessment(); state.statuses[2] = '응답 대기'; el('evaluate').hidden = false;
    status('question-status', `${state.diagnosis.total}개 역량의 진단 질문을 준비했습니다. 답변을 입력해 주세요.`, 'success');
    el('workflow-status').textContent = '직무 요구 역량에 맞춘 질문에 답하고 진단 결과를 확인하세요.';
  } catch (error) {state.statuses[2] = '질문 재시도'; el('retry-questions').hidden = false; status('question-status', analysisError(error), 'error');}
  finally {busy(false);}
}
el('retry-questions').onclick = () => openDiagnosis();
async function analyzePosting() {
  resetAnalysis(); state.statuses[1] = '분석 중';
  status('analysis-status', '공고에서 필요한 역량과 수준을 분석하고 있습니다…'); busy(true, '2 / 4 · 직무에 필요한 역량을 분석하고 있습니다.');
  try {
    const data = await post('/api/skillradar/analyze/', {job_posting: state.body, source_url: state.source, current_skills: [], use_llm: true});
    if (!data.requirements.length) throw new Error('요구 역량을 찾지 못했습니다. 다른 공고를 선택하거나 본문을 확인해 주세요.');
    state.extracted = data; state.statuses[1] = '완료'; state.statuses[2] = '평가 대기';
    renderRequirements(data); el('to-assessment').hidden = false;
    status('analysis-status', `${data.requirements.length}개 역량을 찾았습니다. 분석 근거를 확인하고 나의 수준을 평가하세요.`, 'success');
    el('workflow-status').textContent = '직무 분석이 완료되었습니다. 나의 역량 평가로 이어가세요.';
  } catch (error) {
    state.statuses[1] = '재시도 필요'; el('analyze').hidden = false;
    status('analysis-status', analysisError(error), 'error'); el('workflow-status').textContent = '직무 분석을 완료하지 못했습니다. 다시 시도할 수 있습니다.';
  }
}
async function collect(payload) {
  if (state.busy) return;
  resetSearch(); state.statuses[0] = '찾는 중'; busy(true, '1 / 4 · 채용공고를 찾고 있습니다.');
  status('collection-status', '선택한 직무의 채용정보를 확인하고 있습니다…');
  try {
    const data = await post('/api/skillradar/collect/', payload);
    el('candidates').replaceChildren();
    if (data.kind === 'candidates') {
      if (!data.candidates.length) throw new Error('채용공고를 찾지 못했습니다.');
      data.candidates.forEach(item => {
        let url; try {url = new URL(item.url);} catch {return;} if (!['http:', 'https:'].includes(url.protocol)) return;
        const card = document.createElement('article'); card.className = 'candidate';
        const text = document.createElement('div'); const title = document.createElement('h3'); title.textContent = item.title || '채용공고';
        const link = document.createElement('a'); link.textContent = url.hostname + ' · 원문 보기'; link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; text.append(title, link);
        const choose = document.createElement('button'); choose.type = 'button'; choose.textContent = '이 공고로 분석'; choose.onclick = () => collect({url: url.href}); card.append(text, choose); el('candidates').append(card);
      });
      state.statuses[0] = '공고 선택'; status('collection-status', `${el('candidates').children.length}개 검색 결과입니다. 기업·직무·마감일을 확인하고 분석할 공고를 선택하세요.`, 'success');
      el('workflow-status').textContent = '분석할 공고를 선택하면 수집과 직무 분석이 이어집니다.';
    } else {
      showPosting(data); status('collection-status', '공고를 수집했습니다.', 'success'); await analyzePosting();
    }
  } catch (error) {
    state.statuses[0] = '직접 입력 가능'; el('manual-options').open = true;
    status('collection-status', '공고를 자동으로 가져오지 못했습니다. URL을 입력하거나 본문을 붙여 넣어 계속할 수 있습니다.', 'error');
    el('workflow-status').textContent = '수집에 실패했습니다. 입력값을 바꿔 재검색하거나 직접 입력하세요.';
  } finally {busy(false);}
}
el('collect-form').onsubmit = event => {event.preventDefault(); collect({company: el('company').value, division: el('division').value, role: el('role').value});};
el('url-form').onsubmit = event => {event.preventDefault(); collect({url: el('job-url').value});};
el('manual-form').onsubmit = async event => {
  event.preventDefault(); if (state.busy) return;
  if (!el('posting').value.trim()) {status('collection-status', '공고 본문을 입력해 주세요.', 'error'); return;}
  resetAnalysis(); showPosting({body: el('posting').value.trim(), source_url: el('source-url').value});
  busy(true); try {await analyzePosting();} finally {busy(false);}
};
el('analyze').onclick = async () => {if (state.busy) return; busy(true); try {await analyzePosting();} finally {busy(false);}};

function renderComparison(data) {
  loadDebugContext();
  el('result').hidden = false; el('summary').textContent = `AI 진단 ${data.summary.total}개 역량 · 미평가 ${data.summary.unassessed}개 · 진단 결과 저장 완료`;
  el('insufficient').textContent = `요구 수준 대비 부족한 역량: ${data.insufficient_skills.join(', ') || '수치로 확인된 부족 역량 없음'}`;
  el('evaluation-reasons').replaceChildren();
  data.requirements.forEach(item => {
    const card = document.createElement('article'); card.className = 'requirement'; const title = document.createElement('h3'); title.textContent = `${item.name} · ${item.score === null ? '미평가' : item.score + ' / 5점'}`;
    const reason = document.createElement('p'); reason.textContent = item.evaluation_reason;
    const evidence = document.createElement('blockquote'); evidence.textContent = item.answer_evidence.length ? '내 답변 근거: ' + item.answer_evidence.join('\n') : '인용할 답변이 없습니다.';
    const weak = document.createElement('p'); weak.textContent = '보완할 점: ' + (item.weak_points.join(', ') || '별도 보완점 없음');
    card.append(title, reason, evidence, weak); el('evaluation-reasons').append(card);
  });
  el('comparison').replaceChildren();
  data.requirements.forEach(item => {const row = document.createElement('tr'); [item.name, kinds[item.importance], `${item.required_level ?? '미확인'} / ${item.current_level ?? '미평가'}`, `${item.gap ?? '산정 불가'} / ${item.priority_rank ? item.priority_rank + '순위' : '목표 이상'}`].forEach(value => {const cell = document.createElement('td'); cell.textContent = value; row.append(cell);}); el('comparison').append(row);});
  el('priorities').textContent = `학습·진단 순서: ${data.learning_priorities.join(' → ') || '현재 평가상 추가 학습 대상이 없습니다.'}`;
  destroyCharts(); el('chart-status').textContent = '';
  if (!window.Chart) {el('chart-status').textContent = '차트를 불러오지 못했습니다. 자세히 보기에서 표로 확인할 수 있습니다.'; return;}
  const items = data.requirements;
  state.charts.push(new Chart(el('radar'), {type: items.length >= 3 ? 'radar' : 'bar', data: {labels: items.map(x => x.name), datasets: [{label: '요구 수준', data: items.map(x => x.required_level), borderColor: '#f5bd75', backgroundColor: '#f5bd7522'}, {label: '진단 점수', data: items.map(x => x.current_level), borderColor: '#76dfc3', backgroundColor: '#76dfc322'}]}, options: {responsive: true, maintainAspectRatio: false, scales: items.length >= 3 ? {r: {min: 0, max: 5, ticks: {stepSize: 1}, pointLabels: {color: '#e8edf5'}}} : {y: {min: 0, max: 5}}}}));
  state.charts.push(new Chart(el('gaps'), {type: 'bar', data: {labels: items.map(x => x.name), datasets: [{label: '역량 격차', data: items.map(x => x.gap), backgroundColor: '#76dfc3'}]}, options: {responsive: true, maintainAspectRatio: false, scales: {y: {min: 0, max: 5, ticks: {stepSize: 1}}}}}));
}
function preparePlan() {
  el('unknown-targets').replaceChildren(); el('known-targets').replaceChildren(); resetPlan();
  state.evaluated.requirements.forEach(item => {
    const label = document.createElement('label'); label.textContent = item.required_level === null ? `${item.name} · 공고의 요구 수준이 없어 학습 목표를 선택해 주세요` : `${item.name} 학습 목표`;
    const select = document.createElement('select'); select.className = 'target-level'; select.dataset.name = item.name; select.dataset.skillId = item.skill_id; select.required = true; select.setAttribute('aria-label', `${item.name} 학습 목표`);
    if (item.required_level === null) select.add(new Option('목표 선택', ''));
    for (let level = 1; level <= 5; level++) select.add(new Option(`${level} · ${levels[level]}`, level));
    select.value = item.required_level ?? ''; select.onchange = resetPlan; label.append(document.createTextNode(' '), select);
    el(item.required_level === null ? 'unknown-targets' : 'known-targets').append(label);
  });
  el('plan-context').textContent = `${state.evaluated.requirements.length}개 역량의 평가와 학습 순서를 반영합니다. 필요하면 학습 시간과 목표를 조정하세요.`;
}
el('evaluation-form').onsubmit = async event => {
  event.preventDefault(); if (state.busy || !state.diagnosis || !state.diagnosis.ready) return;
  const responses = Array.from(el('skill-inputs').children).map(row => ({skill_id: row.dataset.skillId, answer: row.querySelector('textarea').value.trim()}));
  if (!responses.some(item => item.answer)) {status('evaluation-status', '답변을 한 개 이상 입력해 주세요. 모르면 모르겠다고 답해도 됩니다.', 'error'); return;}
  resetEvaluation(false); state.statuses[2] = '답변 평가 중'; busy(true, '3 / 4 · 답변을 평가 기준에 따라 진단하고 있습니다.');
  try {
    if (!state.attempt) state.attempt = await post(`/api/skillradar/diagnoses/${state.diagnosis.id}/attempts/`, {responses});
    while (!state.attempt.completed) {
      const before = state.attempt.evaluated;
      status('evaluation-status', `답변 평가 중 · ${before} / ${state.attempt.total}개 역량 · 완료된 평가는 저장됩니다.`);
      const data = await post(`/api/skillradar/attempts/${state.attempt.id}/evaluate/`, {});
      if (data.evaluated <= before && !data.completed) throw new Error('평가를 이어가지 못했습니다. 다시 시도해 주세요.');
      state.attempt = data;
    }
    const data = state.attempt.result; state.evaluated = data; state.statuses[2] = '완료'; renderComparison(data); preparePlan();
    status('evaluation-status', '진단 점수·부족 역량·평가 근거를 저장했습니다. 성장 계획에 바로 활용할 수 있습니다.', 'success'); el('workflow-status').textContent = '답변 기반 진단이 완료되었습니다. 결과를 반영한 성장 계획을 만들 수 있습니다.';
  } catch (error) {state.statuses[2] = '재시도 필요'; status('evaluation-status', analysisError(error), 'error'); el('workflow-status').textContent = '평가를 완료하지 못했습니다. 입력을 확인하고 다시 시도하세요.';}
  finally {busy(false);}
};
el('plan').onclick = () => goStep(4);
['plan-weeks', 'plan-hours', 'plan-notes'].forEach(id => el(id).addEventListener('input', resetPlan));
function renderPlan(plan) {
  el('debug-plan-context').textContent = plan.debugdna_insights && plan.debugdna_insights.analysis_count ? `DebugDNA ${plan.debugdna_insights.analysis_count}개 코드 쌍의 관찰을 반영했습니다. 학습 순서: ${plan.priorities.map(item => `${item.name}${item.debug_boost ? ' (실수 기록 가산 ' + item.debug_boost + ')' : ''}`).join(' → ')}` : '';
  el('heading-4').textContent = '나의 성장 계획이 준비되었습니다'; el('generate').textContent = '계획 다시 생성';
  el('roadmap').hidden = false; el('roadmap-summary').textContent = plan.weeks.length ? `${plan.weeks.length}주 · 총 ${plan.total_hours}시간 · ${state.planInput.hours_per_week}시간씩 학습합니다.` : '현재 자기평가상 목표 수준을 충족했습니다. 목표를 높이거나 다음 학습을 선택해 보세요.';
  el('deferred').textContent = plan.deferred_skills.length ? `이번 기간에 배정되지 않은 역량: ${plan.deferred_skills.join(', ')}. 기간을 늘리면 함께 계획할 수 있어요.` : '';
  el('schedule').replaceChildren();
  const stages = {diagnosis: '현재 수준 진단', foundation: '기초 다지기', application: '프로젝트 적용', advanced: '설계·개선'};
  plan.weeks.forEach(week => {
    const card = document.createElement('article'); card.className = 'week'; const title = document.createElement('h3'); title.textContent = `${week.week}주차 · ${week.skill} · ${week.hours}시간`;
    const stage = document.createElement('small'); stage.textContent = stages[week.stage] || '맞춤 학습'; card.append(title, stage);
    [['목표', week.objective], ['실습', week.exercise], ['완료 기준', week.completion], ['회고', week.review]].forEach(([label, value]) => {const p = document.createElement('p'); p.textContent = `${label}: ${value}`; card.append(p);}); el('schedule').append(card);
  });
}
el('roadmap-form').onsubmit = async event => {
  event.preventDefault(); if (state.busy || !state.evaluated) return;
  resetPlan(); state.statuses[3] = '생성 중'; busy(true, '4 / 4 · 평가에 맞춘 학습 목표와 실습 과제를 만들고 있습니다.'); status('plan-status', '맞춤 성장 계획을 생성하고 있습니다…');
  const targets = Array.from(document.querySelectorAll('.target-level')).map(select => ({skill_id: select.dataset.skillId, level: Number(select.value)}));
  const input = {attempt_id: state.attempt.id, targets, weeks: Number(el('plan-weeks').value), hours_per_week: Number(el('plan-hours').value), weaknesses: el('plan-notes').value, use_llm: true};
  try {
    const plan = await post('/api/growthplan/from-diagnosis/', input); state.plan = plan; state.planInput = plan.configuration; state.statuses[3] = '완료'; renderPlan(plan);
    status('plan-status', '성장 계획이 완성되었습니다. 주차별 목표와 실습을 확인하세요.', 'success'); el('workflow-status').textContent = '모든 단계를 완료했습니다. GrowthPlan에서 저장하고 학습을 이어갈 수 있습니다.';
  } catch (error) {state.statuses[3] = '재시도 필요'; status('plan-status', analysisError(error), 'error'); el('workflow-status').textContent = '계획을 생성하지 못했습니다. 입력은 유지되며 다시 시도할 수 있습니다.';}
  finally {busy(false);}
};
el('manage-plan').onclick = () => {
  if (!state.plan) return;
  window.location.href = `/growthplan/?roadmap=${encodeURIComponent(state.plan.roadmap_id)}`;
};
async function get(url) {const response = await fetch(url); const data = await response.json(); if (!response.ok) throw new Error(data.error || '기록을 불러오지 못했습니다.'); return data;}
el('load-history').onclick = async () => {
  if (state.busy) return; busy(true, '저장한 진단 기록을 확인하고 있습니다.'); el('diagnosis-history').replaceChildren();
  try {
    const data = await get('/api/skillradar/diagnoses/history/');
    if (!data.attempts.length) {el('diagnosis-history').textContent = '이 브라우저 세션에 저장된 완료 진단이 없습니다.'; return;}
    data.attempts.forEach(attempt => {
      const card = document.createElement('article'); card.className = 'candidate'; const text = document.createElement('p'); text.textContent = `${new Date(attempt.created_at).toLocaleString('ko-KR')} · ${attempt.result.requirements.map(item => item.name).join(', ')}`;
      const button = document.createElement('button'); button.type = 'button'; button.textContent = '진단 결과 열기'; button.onclick = () => loadAttempt(attempt.id); card.append(text, button); el('diagnosis-history').append(card);
    });
  } catch (error) {status('collection-status', error.message, 'error');} finally {busy(false);}
};
async function loadAttempt(id) {
  if (state.busy) return; busy(true, '진단 질문과 평가 결과를 불러오고 있습니다.');
  try {
    const data = await get(`/api/skillradar/attempts/${id}/`);
    state.diagnosis = data.diagnosis; state.attempt = data; state.body = data.diagnosis.job_posting; state.source = data.diagnosis.source_url;
    state.title = data.diagnosis.job_title || '저장된 채용공고'; el('company').value = data.diagnosis.company || ''; el('division').value = data.diagnosis.division || ''; el('role').value = data.diagnosis.role || '';
    state.extracted = data.result; state.evaluated = data.result; state.statuses = ['완료', '완료', '완료', '생성 대기'];
    el('posting').value = state.body; el('source-url').value = state.source; el('posting-preview').textContent = state.body;
    el('job-context').textContent = '저장된 진단의 채용공고'; el('provenance').textContent = state.source || '직접 입력한 공고';
    el('source-link').hidden = true; el('analyze').hidden = true; el('to-assessment').hidden = false; el('evaluate').hidden = false;
    renderRequirements(data.result); renderAssessment();
    const responses = new Map(data.responses.map(item => [item.skill_id, item.answer]));
    Array.from(el('skill-inputs').children).forEach(row => {row.querySelector('textarea').value = responses.get(row.dataset.skillId) || '';});
    preparePlan(); goStep(3, true); renderComparison(data.result);
    status('evaluation-status', '저장된 진단 결과입니다. 답변을 수정하면 새로운 진단으로 평가됩니다.', 'success');
  } catch (error) {status('collection-status', error.message, 'error');} finally {busy(false);}
}
async function loadDebugContext() {try {const data = await get('/api/debugdna/insights/'); el('debug-context').textContent = data.analysis_count ? `DebugDNA ${data.analysis_count}개 코드 쌍 분석 · ${data.weak_skills.map(item => item.name + ' 관찰 ' + item.issue_count + '건').join(', ')}. 성장 계획에서 반복 실수와 보완 과제를 함께 반영합니다.` : '';} catch {el('debug-context').textContent = '';}}
updateSteps();
const restoredAttempt = new URLSearchParams(window.location.search).get('attempt');
if (restoredAttempt) loadAttempt(restoredAttempt);
