"""Run a small live inference check against the configured local Ollama server."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from growthplan.planning import PlanInput, build_plan
from skillradar.analysis import RadarInput, analyze_radar


def main():
    posting = '필수 역량\nPython으로 API를 독립적으로 개발하고 문제를 해결할 수 있어야 합니다.\nDjango 프로젝트 활용 경험이 필요합니다.\n우대 사항\nDocker 기초 실습 경험을 우대합니다.'
    assessment = analyze_radar(RadarInput(job_posting=posting, current_skills=[{'name': 'Python', 'level': 1, 'evidence': '기초 실습'}]))
    if not assessment['requirements']:
        raise AssertionError('No requirements extracted')
    python = next(item for item in assessment['requirements'] if item['name'] == 'Python')
    if python['level_basis'] != 'inferred' or python['gap'] != max(0, python['required_level'] - 1):
        raise AssertionError('Canonical name, inferred level, or gap mismatch')
    print('Live Qwen extraction validated:', len(assessment['requirements']), 'requirements', flush=True)
    for item in assessment['requirements']:
        print(item['name'], 'required_level=', item['required_level'], 'basis=', item['level_basis'], 'weight=', item['weight'], 'gap=', item['gap'], flush=True)
    item = next((x for x in assessment['requirements'] if x['current_level'] is not None), assessment['requirements'][0])
    skill = {key: item[key] for key in ('name', 'current_level', 'required_level', 'level_basis', 'importance', 'weight')}
    skill['target_level'] = item['required_level'] or 3
    skill['experience'] = item['current_evidence']
    plan = build_plan(PlanInput(skills=[skill], weeks=1, hours_per_week=3, use_llm=True, weaknesses='경계값 처리 연습'))
    if len(plan['weeks']) != 1 or plan['total_hours'] != 3 or plan['source'] != 'qwen':
        raise AssertionError('Invalid live roadmap')
    print('Live Qwen roadmap validated: 1 week / 3 hours', flush=True)


if __name__ == '__main__':
    main()
