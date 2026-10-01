import copy
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from PIL import Image
from film_color import sha256
from check_acceptance_record import COMPOSITE_WEIGHTS, CONDITIONAL, REQUIRED, main, review


class AcceptanceRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source, result, plan = [self.root/name for name in ('source.png', 'result.png', 'plan.json')]
        Image.new('RGB', (32, 24), (10, 20, 30)).save(source)
        Image.new('RGB', (32, 24), (40, 50, 60)).save(result)
        plan.write_text(json.dumps({'source_sha256': sha256(source),
                                   'acceptance_targets': {'synthetic': 'not a real image review'}}))
        self.record = {
            'schema_version': 1,
            **{name: {'path': str(path), 'sha256': sha256(path)}
               for name, path in [('source', source), ('result', result), ('plan', plan)]},
            'scope': {'people': True, 'architecture': False, 'reflections': False,
                      'evidence': 'Synthetic applicability fixture, not semantic evidence'},
            'checks': {key: {'status': 'pass', 'observation': 'Synthetic assertion',
                             'evidence': ['Synthetic review record only']}
                       for key in (*REQUIRED, *CONDITIONAL)},
            'attempts': [{'number': 1, 'kind': 'initial', 'result_sha256': sha256(result)}],
            'user_feedback': {'status': 'not-requested'},
        }
        for key in ('architecture-contour', 'reflection'):
            self.record['checks'][key]['status'] = 'not-applicable'

    def feedback(self, status):
        self.record['user_feedback'] = {'status': status, 'evidence': 'Synthetic feedback',
                                       'result_sha256': self.record['result']['sha256']}

    def use_composite(self):
        self.record['schema_version'] = 2
        self.record['composite_review'] = {
            key: {'score': weight, 'evidence': 'Synthetic category evidence only'}
            for key, weight in COMPOSITE_WEIGHTS.items()
        }

    def test_ninety_percent_composite_allows_one_visual_gap(self):
        self.use_composite()
        self.feedback('accepted')
        self.record['checks']['color-output']['status'] = 'fail'
        self.record['composite_review']['film_color_and_light']['score'] = 15
        result = review(self.record)
        self.assertEqual(result['composite_score'], 90)
        self.assertTrue(result['visual_threshold_met'])
        self.assertTrue(result['production_acceptance_record_complete'])

    def test_below_ninety_or_nonvisual_failure_blocks_composite_acceptance(self):
        self.use_composite()
        self.feedback('accepted')
        self.record['composite_review']['film_color_and_light']['score'] = 14.9
        result = review(self.record)
        self.assertFalse(result['visual_threshold_met'])
        self.assertFalse(result['production_acceptance_record_complete'])
        self.record['composite_review']['film_color_and_light']['score'] = 25
        self.record['checks']['privacy']['status'] = 'fail'
        self.assertFalse(review(self.record)['production_acceptance_record_complete'])

    def test_composite_requires_bounded_scores_and_evidence(self):
        self.use_composite()
        self.record['composite_review']['print_and_contour']['score'] = 21
        with self.assertRaisesRegex(ValueError, 'outside'):
            review(self.record)
        self.record['composite_review']['print_and_contour']['score'] = 20
        self.record['composite_review']['print_and_contour']['evidence'] = ''
        with self.assertRaisesRegex(ValueError, 'evidence'):
            review(self.record)

    def test_all_declared_pass_is_not_user_or_visual_acceptance(self):
        result = review(self.record)
        self.assertEqual(result['declared_hard_gates'], 'pass')
        self.assertFalse(result['production_acceptance_record_complete'])
        self.assertFalse(result['automatic_visual_verification'])
        self.assertFalse(result['release_authorized'])

    def test_user_acceptance_cannot_erase_failure(self):
        self.feedback('accepted')
        self.record['checks']['person-contour']['status'] = 'fail'
        result = review(self.record)
        self.assertEqual(result['user_feedback'], 'accepted')
        self.assertEqual(result['failed_gates'], ['person-contour'])
        self.assertFalse(result['production_acceptance_record_complete'])

    def test_rejection_and_relative_preference_are_not_pending_or_accepted(self):
        for status in ('rejected', 'preferred-only'):
            self.feedback(status)
            result = review(self.record)
            self.assertEqual(result['user_feedback'], status)
            self.assertFalse(result['production_acceptance_record_complete'])

    def test_accepted_record_is_not_release_authorization(self):
        self.feedback('accepted')
        result = review(self.record)
        self.assertTrue(result['production_acceptance_record_complete'])
        self.assertFalse(result['release_authorized'])

    def test_unmeasured_color_is_not_zero_or_pass(self):
        self.feedback('accepted')
        self.record['checks']['color-output']['status'] = 'unverified'
        result = review(self.record)
        self.assertEqual(result['unverified_gates'], ['color-output'])
        self.assertFalse(result['production_acceptance_record_complete'])

    def test_required_gates_cannot_disappear_or_be_not_applicable(self):
        for key in ('person-contour', 'color-plan', 'privacy', 'screen-mesh'):
            record = copy.deepcopy(self.record)
            record['checks'].pop(key)
            with self.assertRaises(ValueError):
                review(record)
            record = copy.deepcopy(self.record)
            record['checks'][key]['status'] = 'not-applicable'
            with self.assertRaises(ValueError):
                review(record)

    def test_empty_evidence_and_unknown_scope_are_rejected(self):
        self.record['checks']['content']['evidence'] = []
        with self.assertRaisesRegex(ValueError, 'evidence'):
            review(self.record)
        self.record['checks']['content']['evidence'] = ['Synthetic']
        self.record['scope']['people'] = 'false'
        with self.assertRaisesRegex(ValueError, 'booleans'):
            review(self.record)

    def test_changed_source_result_or_plan_cannot_reuse_review(self):
        for name in ('source', 'result', 'plan'):
            record = copy.deepcopy(self.record)
            record[name]['sha256'] = '0'*64
            with self.assertRaisesRegex(ValueError, 'hash'):
                review(record)

    def test_feedback_from_another_result_is_rejected(self):
        self.feedback('accepted')
        self.record['user_feedback']['result_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'exact result'):
            review(self.record)

    def test_plan_requires_source_binding_and_frozen_targets(self):
        plan = Path(self.record['plan']['path'])
        for data in ({'source_sha256': '0'*64, 'acceptance_targets': {'test': True}},
                     {'source_sha256': self.record['source']['sha256']}, []):
            plan.write_text(json.dumps(data))
            self.record['plan']['sha256'] = sha256(plan)
            with self.assertRaises(ValueError):
                review(self.record)

    def test_record_schema_cannot_be_a_boolean_or_non_object(self):
        for value in ([], None, {**self.record, 'schema_version': True}):
            with self.assertRaisesRegex(ValueError, 'schema'):
                review(value)

    def test_correction_requires_valid_base_and_does_not_reset_budget(self):
        attempt = {'number': 2, 'kind': 'correction', 'base_passed': True,
                   'reason': 'Synthetic local issue', 'result_sha256': '1'*64}
        self.record['attempts'].append(attempt)
        self.assertEqual(review(self.record)['attempt_count'], 2)
        attempt['base_passed'] = False
        with self.assertRaisesRegex(ValueError, 'valid base'):
            review(self.record)
        attempt['base_passed'] = True
        self.record['attempts'].append({**attempt, 'number': 3})
        with self.assertRaisesRegex(ValueError, 'Correction'):
            review(self.record)

    def test_authorized_extra_attempt_remains_test_only(self):
        self.feedback('accepted')
        self.record['attempts'].append({'number': 2, 'kind': 'additional-test',
                                       'reason': 'Synthetic experiment', 'result_sha256': '1'*64})
        with self.assertRaisesRegex(ValueError, 'authorization'):
            review(self.record)
        self.record['attempts'][1]['authorization'] = 'Synthetic explicit test authorization'
        result = review(self.record)
        self.assertTrue(result['test_only'])
        self.assertFalse(result['production_acceptance_record_complete'])

    def test_selected_older_result_stays_selected(self):
        self.record['attempts'].append({'number': 2, 'kind': 'correction', 'base_passed': True,
                                       'reason': 'Synthetic local issue', 'result_sha256': '1'*64})
        self.assertEqual(review(self.record)['result_sha256'], self.record['result']['sha256'])
        self.record['attempts'][0]['result_sha256'] = '2'*64
        with self.assertRaisesRegex(ValueError, 'ledger'):
            review(self.record)

    def test_source_alias_and_skill_output_are_rejected(self):
        record = copy.deepcopy(self.record)
        record['result'] = record['source']
        with self.assertRaisesRegex(ValueError, 'alias'):
            review(record)
        skill = self.root/'skill'
        skill.mkdir()
        (skill/'SKILL.md').write_text('Synthetic fixture')
        with self.assertRaisesRegex(ValueError, 'outside skill'):
            main(['--record', str(self.root/'missing.json'), '--output', str(skill/'report.json')])

    def test_cli_exit_status_and_no_overwrite(self):
        record = self.root/'record.json'
        record.write_text(json.dumps(self.record))
        output = self.root/'report.json'
        with redirect_stdout(StringIO()):
            status = main(['--record', str(record), '--output', str(output), '--require-accepted'])
        self.assertEqual(status, 2)
        self.assertTrue(json.loads(output.read_text())['record_consistent'])
        with self.assertRaisesRegex(ValueError, 'new private file'):
            main(['--record', str(record), '--output', str(output)])


if __name__ == '__main__':
    unittest.main()
