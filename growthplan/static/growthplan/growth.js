const el=id=>document.getElementById(id);const key='growthplan-saved-v1';let active=null;let sequence=0;
const progressStore = window.DevDNAProgress;
let completionBusy = false, activationVersion = 0, automaticLoad = true, progressRevision = 0;
function addGoal(skill={}){
 if(el('goals').children.length>=30)return;
 const row=document.createElement('div');row.className='goal';const id=++sequence;
 const name=document.createElement('input');name.className='name';name.required=true;name.maxLength=80;name.placeholder='역량 이름';name.value=skill.name||'';name.setAttribute('aria-label',`역량 ${id} 이름`);
 function select(className,label,options,value){const control=document.createElement('select');control.className=className;control.setAttribute('aria-label',`역량 ${id} ${label}`);options.forEach(([value,text])=>control.add(new Option(text,value)));control.value=String(value);return control}
 const current=select('current','현재 수준',[['','미평가'],...[0,1,2,3,4,5].map(n=>[n,`현재 ${n}`])],skill.current_level??'');
 const target=select('target','목표 수준',[['','목표 선택'],...[1,2,3,4,5].map(n=>[n,`목표 ${n}`])],Object.hasOwn(skill,'target_level')?(skill.target_level??''):3);target.required=true;
 const importance=select('importance','중요도',[['required','필수'],['unspecified','구분 없음'],['preferred','우대']],skill.importance||'unspecified');
 const remove=document.createElement('button');remove.type='button';remove.className='secondary';remove.textContent='삭제';remove.setAttribute('aria-label',`역량 ${id} 삭제`);remove.onclick=()=>row.remove();row.append(name,current,target,importance,remove);
 const weight=select('weight','학습 중요도',[1,2,3,4,5].map(n=>[n,`중요도 ${n}`]),skill.weight??3);row.insertBefore(weight,remove);
 row.dataset.requiredLevel=skill.required_level??'';row.dataset.levelBasis=skill.level_basis||'unknown';row.dataset.experience=skill.experience||'';
 const detail=document.createElement('small');detail.style.gridColumn='1 / -1';detail.textContent=`공고 요구 수준: ${skill.required_level??'알 수 없음'} (${({explicit:'공고 명시',inferred:'AI 해석',unknown:'판단 불가'})[skill.level_basis||'unknown']})${skill.experience?' · 내 경험: '+skill.experience:''}`;row.append(detail);
 name.oninput=()=>{row.dataset.requiredLevel='';row.dataset.levelBasis='unknown';detail.textContent='역량 이름 변경: 공고 요구 수준 연결을 해제했습니다.'};el('goals').append(row);
}
function populate(input){el('goals').replaceChildren();input.skills.forEach(addGoal);el('weeks').value=input.weeks;el('hours').value=input.hours_per_week;el('weaknesses').value=input.weaknesses;el('mode').value=input.use_llm?'qwen':'template'}
el('add').onclick=()=>addGoal();addGoal();
el('example').onclick=()=>populate({skills:[{name:'Python',current_level:1,target_level:3,importance:'required'},{name:'Django',current_level:null,target_level:3,importance:'required'},{name:'Docker',current_level:0,target_level:2,importance:'preferred'}],weeks:4,hours_per_week:5,weaknesses:'경계값 처리 누락. 실패 사례를 먼저 정리하는 연습이 필요함.',use_llm:false});
function completedWeeks(plan) {return (plan.tasks || []).filter(task => task.completed).map(task => task.week);}
function updateProgress() {
  const saved = active.plan.roadmap_id && active.plan.progress;
  const total = saved ? saved.total : active.plan.weeks.length;
  const count = saved ? saved.completed : active.completed.length;
  el('progress').max = total || 1; el('progress').value = count;
  el('progress-text').textContent = total ? `${count} / ${total}주 완료 (${saved ? saved.percent : Math.round(count / total * 100)}%)` : '진행할 과제가 없습니다.';
}
function render() {
  const {plan} = active;
  if (plan.roadmap_id) active.completed = completedWeeks(plan);
  el('result').hidden = false; el('storage-status').textContent = '';
  el('summary').textContent = `${plan.source === 'qwen' ? 'Qwen 맞춤 계획' : '기본 계획'} · ${plan.weeks.length}주 · 총 ${plan.total_hours}시간`;
  el('priority').textContent = '학습 우선순위: ' + (plan.priorities.map(x => `${x.name} (격차 ${x.gap ?? '미평가'}, 점수 ${x.priority_score ?? '산정 불가'}${x.debug_boost ? ', DebugDNA 가산 ' + x.debug_boost : ''})`).join(' → ') || '추가 학습 대상 없음');
  el('deferred').textContent = plan.deferred_skills.length ? '기간 내 미배정 역량: ' + plan.deferred_skills.join(', ') : '';
  el('met').textContent = plan.met_skills.length ? '현재 평가상 목표 이상: ' + plan.met_skills.join(', ') : '';
  el('schedule').replaceChildren();
  const tasks = new Map((plan.tasks || []).map(task => [task.week, task]));
  plan.weeks.forEach(week => {
    const task = tasks.get(week.week);
    const card = document.createElement('article'); card.className = 'week';
    const title = document.createElement('h3'); title.textContent = `${week.week}주차 · ${week.skill} · ${week.hours}시간`; card.append(title);
    [['목표', week.objective], ['실습', week.exercise], ['완료 기준', week.completion], ['회고', week.review]].forEach(([label, value]) => {const p = document.createElement('p'); p.textContent = `${label}: ${value}`; card.append(p);});
    const label = document.createElement('label'), check = document.createElement('input');
    check.type = 'checkbox'; check.checked = task ? task.completed : active.completed.includes(week.week); check.disabled = !task || completionBusy;
    if (task) check.dataset.taskId = task.id;
    card.classList.toggle('done', check.checked);
    check.onchange = () => completeTask(task, check.checked, check);
    label.append(check, document.createTextNode(' 이 주차 실습 과제 완료 · 체크 해제로 취소')); card.append(label); el('schedule').append(card);
  });
  updateProgress();
  el('storage-status').textContent = plan.roadmap_id ? '과제 완료·취소는 자동 저장되며 대시보드에 반영됩니다.' : '이전 기기 보관 초안입니다. 계획을 다시 생성하면 과제 완료를 관리할 수 있습니다.';
}
async function completeTask(task, completed, control) {
  if (!task || completionBusy || !active) {control.checked = !!(task && task.completed); return;}
  const roadmapId = active.plan.roadmap_id;
  progressRevision++;
  let failed = false;
  completionBusy = true; el('submit').disabled = true;
  document.querySelectorAll('.week input').forEach(check => {check.disabled = true;});
  el('storage-status').textContent = completed ? '과제 완료를 저장하고 있습니다…' : '완료 취소를 저장하고 있습니다…';
  try {
    const data = await progressStore.complete(task.id, completed);
    if (active && active.plan.roadmap_id === roadmapId) {
      active.plan.tasks = active.plan.tasks.map(row => row.id === data.task.id ? data.task : row);
      active.plan.progress = data.progress; render();
      el('storage-status').textContent = completed ? '과제를 완료했습니다. 대시보드에도 반영했습니다.' : '완료를 취소했습니다. 대시보드에도 반영했습니다.';
    }
  } catch (error) {
    failed = true;
    control.checked = task.completed; el('storage-status').textContent = error.message + ' · 완료 상태를 다시 확인해 주세요.';
  } finally {
    completionBusy = false; el('submit').disabled = false;
    document.querySelectorAll('.week input').forEach(check => {check.disabled = !check.dataset.taskId;});
    if (failed) await refreshProgress();
  }
}
async function refreshProgress() {
  if (!active || !active.plan.roadmap_id || completionBusy) return;
  const id = active.plan.roadmap_id, version = activationVersion, revision = ++progressRevision;
  try {
    const data = await progressStore.roadmap(id);
    if (!active || active.plan.roadmap_id !== id || version !== activationVersion || revision !== progressRevision || completionBusy) return;
    if (JSON.stringify(data.tasks) !== JSON.stringify(active.plan.tasks)) {active.plan.tasks = data.tasks; active.plan.progress = data.progress; render();}
  } catch (error) {el('storage-status').textContent = '진행 상태 갱신 실패: ' + error.message;}
}
async function openRoadmap(id) {
  const version = ++activationVersion;
  el('status').textContent = '저장된 학습 계획과 완료 기록을 불러오고 있습니다…';
  try {
    const data = await progressStore.roadmap(id);
    if (version !== activationVersion) return;
    active = {version: 1, input: data.configuration, plan: data, completed: completedWeeks(data)};
    populate(active.input); render();
    if (el('stored-plans')) el('stored-plans').value = id;
    const url = new URL(window.location.href); url.searchParams.set('roadmap', id); history.replaceState(null, '', url);
    el('status').textContent = '저장된 학습 계획입니다. 완료·취소는 다른 화면에서도 확인할 수 있습니다.';
  } catch (error) {el('status').textContent = error.message;}
}
async function listPlans() {
  try {
    const data = await progressStore.json('/api/growthplan/roadmaps/');
    el('stored-plans').replaceChildren();
    if (!data.roadmaps.length) el('stored-plans').add(new Option('저장된 계획 없음', ''));
    data.roadmaps.forEach(plan => el('stored-plans').add(new Option(`${new Date(plan.created_at).toLocaleString('ko-KR')} · ${plan.weeks}주`, plan.id)));
    if (active && active.plan.roadmap_id) {
      if (!data.roadmaps.some(plan => plan.id === active.plan.roadmap_id)) el('stored-plans').add(new Option('현재 학습 계획', active.plan.roadmap_id));
      el('stored-plans').value = active.plan.roadmap_id;
    }
    if (automaticLoad && !active && activationVersion === 0 && data.roadmaps.length) openRoadmap(data.roadmaps[0].id);
  } catch (error) {el('status').textContent = error.message;}
}
el('open-plan').onclick = () => {if (el('stored-plans').value) openRoadmap(el('stored-plans').value);};
el('plan-form').onsubmit = async event => {
  event.preventDefault(); if (completionBusy) return;
  el('submit').disabled = true; el('example').disabled = true; el('result').hidden = true; el('status').textContent = '성장 계획을 만들고 있습니다…';
  const input = {skills: Array.from(el('goals').children).map(row => ({name: row.querySelector('.name').value, current_level: row.querySelector('.current').value === '' ? null : Number(row.querySelector('.current').value), target_level: Number(row.querySelector('.target').value), importance: row.querySelector('.importance').value, weight: Number(row.querySelector('.weight').value), required_level: row.dataset.requiredLevel === '' ? null : Number(row.dataset.requiredLevel), level_basis: row.dataset.levelBasis, experience: row.dataset.experience})), weeks: Number(el('weeks').value), hours_per_week: Number(el('hours').value), weaknesses: el('weaknesses').value, use_llm: el('mode').value === 'qwen'};
  try {
    const response = await fetch('/api/growthplan/generate/', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value}, body: JSON.stringify(input)});
    const plan = await response.json(); if (!response.ok) throw new Error(plan.error || '계획 생성에 실패했습니다.');
    activationVersion++; active = {version: 1, input: plan.configuration, plan, completed: completedWeeks(plan)}; render();
    const url = new URL(window.location.href); url.searchParams.set('roadmap', plan.roadmap_id); history.replaceState(null, '', url);
    progressStore.publish(plan.roadmap_id); listPlans(); el('status').textContent = '계획과 학습 과제를 저장했습니다.';
  } catch (error) {el('status').textContent = error.message;}
  finally {el('submit').disabled = false; el('example').disabled = false;}
};
el('save').onclick = () => {if (!active) return; try {localStorage.setItem(key, JSON.stringify(active)); el('storage-status').textContent = '이 기기에 백업을 보관했습니다. 과제 완료 상태는 저장된 서버 기록을 우선합니다.';} catch {el('storage-status').textContent = '기기 보관을 사용할 수 없습니다. Markdown 다운로드로 보관하세요.';}};
function validSaved(value) {
  return value && value.version === 1 && value.input && Array.isArray(value.input.skills) && value.input.skills.length > 0 && value.input.skills.length <= 30 && value.input.skills.every(s => s && typeof s.name === 'string') && value.plan && Array.isArray(value.plan.weeks) && value.plan.weeks.length <= 12 && value.plan.weeks.every((w,i) => w && w.week === i+1 && ['skill','objective','exercise','completion','review'].every(k => typeof w[k] === 'string')) && ['priorities','deferred_skills','met_skills'].every(k => Array.isArray(value.plan[k])) && Array.isArray(value.completed);
}
el('load').onclick = () => {try {const saved = JSON.parse(localStorage.getItem(key) || 'null'); if (!saved) {el('status').textContent = '기기 보관 백업이 없습니다.'; return;} if (!validSaved(saved)) throw new Error(); if (saved.plan.roadmap_id) {openRoadmap(saved.plan.roadmap_id); return;} activationVersion++; active = saved; populate(active.input); render();} catch {el('status').textContent = '기기 보관 백업을 읽을 수 없습니다.';}};
el('delete').onclick = () => {try {localStorage.removeItem(key); el('storage-status').textContent = '기기 백업을 삭제했습니다. 저장된 계획과 완료 상태는 유지됩니다.';} catch {el('storage-status').textContent = '기기 저장소를 사용할 수 없습니다.';}};
el('export').onclick = () => {if (!active) return; const text = ['# GrowthPlan', `총 ${active.plan.total_hours}시간`, ...active.plan.weeks.map(w => `## ${w.week}주차: ${w.skill} (${w.hours}시간)\n- [${active.completed.includes(w.week) ? 'x' : ' '}] 완료\n목표: ${w.objective}\n실습: ${w.exercise}\n완료 기준: ${w.completion}\n회고: ${w.review}`)].join('\n\n'); const url = URL.createObjectURL(new Blob([text], {type: 'text/markdown;charset=utf-8'})); const link = document.createElement('a'); link.href = url; link.download = 'growthplan.md'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);};
const selectedPlan = new URLSearchParams(window.location.search).get('roadmap');
if (selectedPlan) {automaticLoad = false; openRoadmap(selectedPlan);}
else {
  try {
    const generated = JSON.parse(sessionStorage.getItem('growthplan-generated') || 'null');
    if (generated) {if (!validSaved(generated)) throw new Error(); automaticLoad = false; sessionStorage.removeItem('growthplan-generated'); if (generated.plan.roadmap_id) openRoadmap(generated.plan.roadmap_id); else {active = generated; populate(active.input); render();}}
    else {
      const incoming = JSON.parse(sessionStorage.getItem('growthplan-handoff') || 'null');
      if (incoming) {const skills = Array.isArray(incoming) ? incoming : incoming.skills; if (!Array.isArray(skills) || !skills.length || skills.length > 30 || !skills.every(skill => skill && typeof skill.name === 'string')) throw new Error(); automaticLoad = false; el('goals').replaceChildren(); skills.forEach(addGoal); sessionStorage.removeItem('growthplan-handoff');}
    }
  } catch {el('status').textContent = '전달한 초안을 읽지 못했습니다. 저장된 계획을 선택하거나 새로 생성하세요.';}
}
listPlans();
progressStore.subscribe(event => {if (active && active.plan.roadmap_id === event.roadmap_id) refreshProgress(); listPlans();});
setInterval(() => {if (!document.hidden) refreshProgress();}, 5000);
window.addEventListener('focus', () => refreshProgress());
document.addEventListener('visibilitychange', () => {if (!document.hidden) refreshProgress();});
