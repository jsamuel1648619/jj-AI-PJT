from collections import defaultdict

from skillradar.analysis import normalize
from .models import CodeAnalysis


def session_insights(owner):
    empty = {'analysis_count': 0, 'categories': {}, 'weak_skills': []}
    if not owner:
        return empty
    codes, categories, skills = set(), defaultdict(set), {}
    rows = CodeAnalysis.objects.filter(owner=owner).order_by('-created_at').values('id', 'code_hash', 'findings')
    for row in rows.iterator():
        code = row['code_hash']
        codes.add(code)
        for finding in row['findings']:
            categories[finding['category']].add(code)
            for name in finding['related_skills']:
                key = normalize(name)
                item = skills.setdefault(key, {'name': name, 'codes': set(), 'categories': defaultdict(set), 'practices': [], 'analysis_ids': []})
                item['codes'].add(code)
                item['categories'][finding['category']].add(code)
                if finding['practice'] not in item['practices'] and len(item['practices']) < 3:
                    item['practices'].append(finding['practice'])
                if str(row['id']) not in item['analysis_ids'] and len(item['analysis_ids']) < 5:
                    item['analysis_ids'].append(str(row['id']))
    weak_skills = []
    for item in skills.values():
        counts = {category: len(values) for category, values in item['categories'].items()}
        recurrence = sum(max(0, count - 1) for count in counts.values())
        weak_skills.append({'name': item['name'], 'issue_count': len(item['codes']), 'recurrence_count': recurrence,
                            'priority_boost': min(6, len(item['codes']) + recurrence), 'categories': counts,
                            'repeated_categories': {key: value for key, value in counts.items() if value >= 2},
                            'practices': item['practices'], 'analysis_ids': item['analysis_ids']})
    weak_skills.sort(key=lambda item: (-item['priority_boost'], -item['issue_count'], normalize(item['name'])))
    return {'analysis_count': len(codes), 'categories': {key: len(value) for key, value in sorted(categories.items())}, 'weak_skills': weak_skills}


def learning_skills(owner, explicit=None):
    from skillradar.models import DiagnosisAttempt
    attempt = DiagnosisAttempt.objects.select_related('diagnosis').filter(diagnosis__owner=owner, completed_at__isnull=False).order_by('-completed_at').first() if owner else None
    names = explicit or ([item['name'] for item in attempt.diagnosis.requirements[:9]] if attempt else [])
    unique = {normalize(name): name for name in ['Python', *names]}
    return list(unique.values()), attempt
