"""Unit tests for candidate bookkeeping; no synthetic test certifies semantics."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image
import trace_review_batch as subject


def fixture():
    frame = {'scene': 1, 'dimensions': [8, 8], 'sha256': 'synthetic-test-only',
             'analysis_region': [0, 0, 1, 1], 'analysis_exclusions': []}
    annotation = {'id': 'test-offset', 'class': 'color_misregistration',
                  'rect': [0, 0, 6, 6], 'mode': 'chroma-range', 'sigma': 0,
                  'low': 20, 'high': 40, 'visual_review': 'Synthetic test fixture.',
                  'restriction': 'Not movie evidence.',
                  'overlay_review': {'status': 'accepted_candidate', 'basis': 'Synthetic only.'}}
    review = {'scene': 1, 'reviewer': 'unit-test',
              'evidence_viewed': ['001-overview.jpg', '001-native-0.png'],
              'native_full_frame_reviewed': True,
              'full_frame_pixel_annotation_complete': False,
              'classes': {cls: {'status': 'present' if cls == 'color_misregistration'
                               else 'not_observed', 'basis': 'Synthetic test fixture.'}
                          for cls in subject.CLASSES}, 'regions': [annotation]}
    return frame, review


class ReviewBatchTests(unittest.TestCase):
    def process(self, frame, review, image=None):
        if image is None:
            image = Image.new('RGB', (8, 8), (0, 180, 180))
        with patch.object(subject, 'load_reference', return_value=(image, 'synthetic', None)):
            return subject.process_frame(review, frame, Path('.'), False)

    def test_positive_class_requires_evidence(self):
        frame, review = fixture()
        review['regions'] = []
        with self.assertRaisesRegex(ValueError, 'without native evidence'):
            subject.check_review(review, frame)

    def test_incomplete_native_view_declaration_fails(self):
        frame, review = fixture()
        review['evidence_viewed'].pop()
        with self.assertRaisesRegex(ValueError, 'incomplete declared'):
            subject.check_review(review, frame)

    def test_candidate_format_cannot_claim_ground_truth(self):
        frame, review = fixture()
        review['full_frame_pixel_annotation_complete'] = True
        with self.assertRaisesRegex(ValueError, 'cannot certify'):
            subject.check_review(review, frame)

    def test_region_overlaps_are_union_not_sum(self):
        frame, review = fixture()
        second = copy.deepcopy(review['regions'][0])
        second.update(id='second-offset', rect=[2, 2, 6, 6])
        review['regions'].append(second)
        result, _ = self.process(frame, review)
        counts = result['classes']['color_misregistration']
        self.assertEqual(counts['core_candidate_union_pixels'], 56)
        self.assertEqual(counts['accepted_candidate_core_union_pixels'], 56)
        self.assertIsNone(counts['full_frame_semantic_share'])

    def test_rejected_ambiguous_unreviewed_not_accepted(self):
        for status in ['rejected_candidate', 'ambiguous_candidate', 'not_yet_reviewed']:
            frame, review = fixture()
            review['regions'][0]['overlay_review']['status'] = status
            result, _ = self.process(frame, review)
            counts = result['classes']['color_misregistration']
            self.assertEqual(counts['core_candidate_union_pixels'], 36)
            self.assertEqual(counts['accepted_candidate_core_union_pixels'], 0)

    def test_exclusion_clips_masks_and_denominator(self):
        frame, review = fixture()
        frame['analysis_exclusions'] = [{'rect': [.25, .25, .5, .5]}]
        result, traces = self.process(frame, review)
        self.assertEqual(result['analysis_roi_pixels'], 60)
        self.assertEqual(traces[0]['excluded_region_pixels'], 4)
        self.assertEqual(traces[0]['core_candidate_pixels'], 32)
        mask = subject.rle_decode(traces[0]['mask_rle'], (6, 6))
        self.assertTrue((mask[2:4, 2:4] == 0).all())

    def test_no_candidate_signal_does_not_mean_semantic_absence(self):
        frame, review = fixture()
        result, traces = self.process(frame, review, Image.new('RGB', (8, 8), (128, 128, 128)))
        self.assertEqual(traces[0]['core_candidate_pixels'], 0)
        self.assertEqual(traces[0]['untraced_region_pixels'], 36)
        counts = result['classes']['color_misregistration']
        self.assertIsNone(counts['semantic_share_of_analysis_roi'])
        self.assertIsNone(counts['full_frame_semantic_share'])
        self.assertEqual(counts['review_status'], 'present')

    def test_native_rect_and_review_status_validation(self):
        frame, review = fixture()
        review['regions'][0]['rect'] = [7, 0, 2, 2]
        with self.assertRaisesRegex(ValueError, 'outside original'):
            subject.check_review(review, frame)
        frame, review = fixture()
        review['regions'][0]['overlay_review']['status'] = 'ground_truth'
        with self.assertRaisesRegex(ValueError, 'invalid overlay'):
            subject.check_review(review, frame)

    def test_candidate_file_is_deterministic_and_source_bound(self):
        frame, review = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/film-library.json').write_text(json.dumps({'frames': [frame]}))
            reviews = root / 'reviews.json'
            reviews.write_text(json.dumps([review]))
            jsonl = root / 'reviews.jsonl'
            jsonl.write_text(json.dumps(review)+'\n')
            with patch.object(subject, 'ROOT', root), patch.object(subject, 'load_reference',
                    return_value=(Image.new('RGB', (8, 8), (0, 180, 180)), 'synthetic', None)):
                subject.run(reviews, root / 'first', False)
                subject.run(reviews, root / 'second', False)
                subject.run(jsonl, root / 'jsonl', False, [1])
                with self.assertRaisesRegex(ValueError, 'has no review'):
                    subject.run(jsonl, root / 'missing', False, [2])
            self.assertEqual((root / 'first/candidate-traces.jsonl.gz').read_bytes(),
                             (root / 'second/candidate-traces.jsonl.gz').read_bytes())
            self.assertEqual((root / 'first/candidate-traces.jsonl.gz').read_bytes(),
                             (root / 'jsonl/candidate-traces.jsonl.gz').read_bytes())
            count = json.loads((root / 'first/counts.json').read_text())['frames'][0]
            self.assertEqual(count['source_sha256'], frame['sha256'])
            self.assertFalse(count['full_frame_pixel_annotation_complete'])


if __name__ == '__main__':
    unittest.main()
