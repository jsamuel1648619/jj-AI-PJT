"""Shared ordering for assessment and roadmap generation."""


def learning_priority(importance, weight, current, target):
    gap = None if current is None or target is None else max(0, target - current)
    score = None if gap is None else gap * weight
    group = {'required': 0, 'unspecified': 1, 'preferred': 2}[importance]
    return (group, -(score or 0), -weight), gap, score
