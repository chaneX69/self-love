"""Check private review records, not image aesthetics or semantic truth."""
import argparse
import json
import math
import re
from pathlib import Path

from PIL import Image
from film_color import sha256
from verify_reference_privacy import require_private_workspace_paths

REQUIRED = (
    'technical', 'content', 'animated-form', 'material-light', 'depth',
    'color-plan', 'color-output', 'halftone', 'hatching', 'screen-mesh',
    'dual-registration', 'permissions', 'privacy',
)
CONDITIONAL = {
    'face-identity': 'people', 'person-contour': 'people',
    'architecture-contour': 'architecture', 'reflection': 'reflections',
}
STATES = {'pass', 'fail', 'unverified', 'not-applicable'}
COMPOSITE_WEIGHTS = {
    'content_and_composition': 25,
    'animated_form_and_people': 20,
    'film_color_and_light': 25,
    'print_and_contour': 20,
    'depth_and_finish': 10,
}
NON_VISUAL_GATES = ('technical', 'permissions', 'privacy')


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def artifact(record, name, image=False):
    item = record.get(name, {})
    require(isinstance(item, dict) and nonempty(item.get('path')), f'{name}: path required')
    path = Path(item['path']).expanduser()
    require(path.is_absolute(), f'{name}: use an absolute private path')
    require_private_workspace_paths(path)
    require(path.is_file(), f'{name}: file missing')
    require(item.get('sha256') == sha256(path), f'{name}: hash changed or missing')
    if image:
        with Image.open(path) as im:
            im.verify()
    return path.resolve()


def review(record):
    require(isinstance(record, dict) and type(record.get('schema_version')) is int
            and record['schema_version'] in (1, 2), 'Unsupported record schema')
    source = artifact(record, 'source', image=True)
    result = artifact(record, 'result', image=True)
    plan_path = artifact(record, 'plan')
    require(not source.samefile(result), 'Result must not overwrite or alias the source')
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    require(isinstance(plan, dict) and plan.get('source_sha256') == record['source']['sha256'],
            'Plan belongs to another source')
    require(isinstance(plan.get('acceptance_targets'), dict) and plan['acceptance_targets'],
            'Plan must include nonempty acceptance_targets fixed before generation')
    scope = record.get('scope', {})
    require(isinstance(scope, dict), 'Explicit applicability required')
    require(all(type(scope.get(key)) is bool for key in set(CONDITIONAL.values())),
            'Declare people, architecture and reflections as booleans')
    require(nonempty(scope.get('evidence')), 'Describe observed applicability, not assumed absence')
    checks = record.get('checks', {})
    require(isinstance(checks, dict) and set(checks) == set(REQUIRED) | set(CONDITIONAL),
            'Missing or unknown review gates')
    for key, item in checks.items():
        require(isinstance(item, dict) and item.get('status') in STATES, f'{key}: invalid status')
        require(nonempty(item.get('observation')), f'{key}: observation or limitation required')
        applicable = key not in CONDITIONAL or scope[CONDITIONAL[key]]
        require((item['status'] != 'not-applicable') == applicable,
                f'{key}: status contradicts applicability')
        evidence = item.get('evidence', [])
        require(isinstance(evidence, list) and all(nonempty(e) for e in evidence),
                f'{key}: evidence must be a list of nonempty descriptions')
        if item['status'] in {'pass', 'fail'}:
            require(bool(evidence), f'{key}: an assertion is not review evidence')

    attempts = record.get('attempts', [])
    require(isinstance(attempts, list) and bool(attempts), 'Record every generation attempt')
    test_only = False
    for index, attempt in enumerate(attempts, 1):
        require(isinstance(attempt, dict) and type(attempt.get('number')) is int
                and attempt['number'] == index, 'Attempt numbers must be consecutive from 1')
        require(isinstance(attempt.get('result_sha256'), str) and
                re.fullmatch(r'[a-f0-9]{64}', attempt['result_sha256']), 'Attempt output hash required')
        kind = attempt.get('kind')
        require(kind in {'initial', 'correction', 'additional-test'}, 'Unknown attempt kind')
        require((kind == 'initial') == (index == 1), 'Only the first attempt is initial')
        if kind == 'correction':
            require(index == 2 and attempt.get('base_passed') is True and
                    nonempty(attempt.get('reason')), 'Correction requires a valid base and one specific reason')
        if kind == 'additional-test':
            require(nonempty(attempt.get('authorization')) and nonempty(attempt.get('reason')),
                    'Additional tests require explicit current user authorization and reason')
            test_only = True
    require(record['result']['sha256'] in {a['result_sha256'] for a in attempts},
            'Selected result is not in the attempt ledger')

    feedback = record.get('user_feedback', {})
    require(isinstance(feedback, dict) and feedback.get('status') in
            {'not-requested', 'accepted', 'rejected', 'preferred-only'}, 'Invalid user feedback state')
    if feedback['status'] != 'not-requested':
        require(feedback.get('result_sha256') == record['result']['sha256'] and
                nonempty(feedback.get('evidence')), 'User feedback must refer to this exact result')

    failed = [key for key, value in checks.items() if value['status'] == 'fail']
    unknown = [key for key, value in checks.items() if value['status'] == 'unverified']
    declared = 'fail' if failed else 'unverified' if unknown else 'pass'
    accepted = feedback['status'] == 'accepted'
    composite_score = None
    visual_threshold_met = False
    if record['schema_version'] == 2:
        categories = record.get('composite_review')
        require(isinstance(categories, dict) and set(categories) == set(COMPOSITE_WEIGHTS),
                'Composite review must contain every weighted category')
        total = 0.0
        for key, maximum in COMPOSITE_WEIGHTS.items():
            item = categories[key]
            require(isinstance(item, dict), f'{key}: review object required')
            score = item.get('score')
            require(type(score) in (int, float) and math.isfinite(score)
                    and 0 <= score <= maximum, f'{key}: score outside 0-{maximum}')
            require(nonempty(item.get('evidence')), f'{key}: concrete score evidence required')
            total += score
        composite_score = round(total, 2)
        visual_threshold_met = composite_score >= 90
        ready = (visual_threshold_met and accepted and not test_only and
                 all(checks[key]['status'] == 'pass' for key in NON_VISUAL_GATES))
    else:
        # Preserve legacy records; new reviews use schema 2's 90-point composite.
        ready = declared == 'pass' and accepted and not test_only
    for name, path in (('source', source), ('result', result), ('plan', plan_path)):
        require(sha256(path) == record[name]['sha256'], f'{name}: changed during verification')
    return {
        'schema_version': record['schema_version'], 'record_consistent': True,
        'source_sha256': record['source']['sha256'], 'result_sha256': record['result']['sha256'],
        'plan_sha256': record['plan']['sha256'],
        'declared_hard_gates': declared, 'failed_gates': failed, 'unverified_gates': unknown,
        'composite_score': composite_score, 'visual_threshold_met': visual_threshold_met,
        'visual_threshold': 90 if record['schema_version'] == 2 else None,
        'user_feedback': feedback['status'], 'attempt_count': len(attempts), 'test_only': test_only,
        'production_acceptance_record_complete': ready,
        'automatic_visual_verification': False, 'release_authorized': False,
        'boundary': 'Hashes, applicability and declarations checked. Human observations, '
                    'preflight timing, attempt completeness and visual truth are not independently proved. '
                    'This result never certifies the whole skill or authorizes generation or publication.',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--require-accepted', action='store_true')
    args = parser.parse_args(argv)
    require_private_workspace_paths(args.record, args.output)
    require(not args.output.exists() and not args.output.is_symlink(), 'Output must be a new private file')
    record = json.loads(args.record.read_text(encoding='utf-8'))
    report = review(record)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False))
    return 2 if args.require_accepted and not report['production_acceptance_record_complete'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
