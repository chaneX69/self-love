"""Archive regression tests use synthetic pixels, never movie truth labels."""
import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import trace_review_batch as tracer
import verify_texture_archive as verifier
from test_review_batch import fixture


class TextureArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root/'data'
        self.data.mkdir()
        self.frame, self.review = fixture()
        self.image = Image.new('RGB', (8, 8), (0, 180, 180))
        self.frame['pixel_sha256'] = tracer.pixel_hash(self.image)
        with patch.object(tracer, 'load_reference', return_value=(self.image,'synthetic',None)):
            result, self.masks = tracer.process_frame(self.review,self.frame,self.data,False)
        self.review.update(source_sha256=self.frame['sha256'],
                           source_pixel_sha256=self.frame['pixel_sha256'],dimensions=[8,8],
                           accepted_candidate_ids=['test-offset'])
        classes = {}
        for cls, values in result['classes'].items():
            region = values['accepted_candidate_region_union_pixels']
            core = values['accepted_candidate_core_union_pixels']
            band = values['accepted_candidate_band_only_union_pixels']
            classes[cls] = dict(visual_status=self.review['classes'][cls]['status'],
                accepted_candidate_region_union_pixels=region, accepted_candidate_core_union_pixels=core,
                accepted_candidate_band_only_union_pixels=band, untraced_inside_accepted_region_pixels=region-core-band,
                outside_accepted_region_pixels=64-region, candidate_core_share_of_analysis_roi=core/64,
                candidate_region_coverage_of_analysis_roi=region/64,
                candidate_core_share_of_accepted_regions=core/region if region else None,
                candidate_trace_share_of_accepted_regions=(core+band)/region if region else None,
                semantic_share_of_analysis_roi=None, full_frame_semantic_share=None)
        self.count = dict(result, classes=classes)
        self.evidence = [dict(scene=1,file=name,sha256='0'*64,bytes=10)
                         for name in self.review['evidence_viewed']]
        self.summary = dict(category_review_complete=True,full_frame_semantic_occupancy_complete=False,
            full_frames_pixel_annotated=0,source_count=1,native_frame_category_reviews=1,
            candidate_ink_counts_are_ground_truth=False,status_not_observed_means_zero_pixels=False,
            accepted_candidate_regions=1,accepted_candidate_frames=1,total_analysis_roi_pixels=64,
            region_overlay_reviews={'accepted_candidate':1},
            class_statuses={c:{self.review['classes'][c]['status']:1} for c in tracer.CLASSES},
            accepted_candidate_core_pixels_by_class={c:classes[c]['accepted_candidate_core_union_pixels'] for c in tracer.CLASSES})

    def save(self):
        (self.data/'film-library.json').write_text(json.dumps({'frames':[self.frame]}))
        for name, values in [('reviews',[self.review]),('counts',[self.count])]:
            (self.data/f'semantic-texture-{name}.jsonl').write_text('\n'.join(map(json.dumps,values))+'\n')
        (self.data/'semantic-view-evidence.jsonl').write_text('\n'.join(map(json.dumps,self.evidence))+'\n')
        (self.data/'semantic-texture-summary.json').write_text(json.dumps(self.summary))
        (self.data/'semantic-texture-candidates.jsonl.gz').write_bytes(
            gzip.compress(('\n'.join(map(json.dumps,self.masks))+'\n').encode(),mtime=0))

    def test_valid_archive_and_recomputation(self):
        self.save()
        self.assertEqual(verifier.verify(self.root)['accepted_local_masks'],1)
        with patch.object(verifier,'archive_index',return_value={}), patch.object(verifier,'load_reference',
                return_value=(self.image,'synthetic',None)):
            self.assertEqual(verifier.verify(self.root,True)['original_sources_checked'],1)

    def test_rejected_mask_not_usable(self):
        self.masks[0]['overlay_review']['status'] = 'rejected_candidate'
        self.save()
        with self.assertRaisesRegex(ValueError,'Rejected trace'):
            verifier.verify(self.root)

    def test_missing_view_receipt_fails(self):
        self.evidence.pop()
        self.save()
        with self.assertRaisesRegex(ValueError,'view receipt mismatch'):
            verifier.verify(self.root)

    def test_whole_frame_false_precision_fails(self):
        self.count['classes']['halftone']['full_frame_semantic_share'] = 0
        self.save()
        with self.assertRaisesRegex(ValueError,'must remain null'):
            verifier.verify(self.root)

    def test_corrupt_rle_fails(self):
        self.masks[0]['mask_rle'][0][1] -= 1
        self.save()
        with self.assertRaisesRegex(ValueError,'run lengths'):
            verifier.verify(self.root)

    def test_stale_annotation_fails(self):
        self.masks = copy.deepcopy(self.masks)
        self.masks[0]['low'] += 1
        self.save()
        with self.assertRaisesRegex(ValueError,'stale annotation'):
            verifier.verify(self.root)

    def test_stale_summary_fails(self):
        self.summary['class_statuses']['hatching'] = {'present':1}
        self.save()
        with self.assertRaisesRegex(ValueError,'summary visual statuses'):
            verifier.verify(self.root)

    def test_changed_source_fails(self):
        self.save()
        with patch.object(verifier,'archive_index',return_value={}), patch.object(verifier,'load_reference',
                return_value=(Image.new('RGB',(8,8),'red'),'synthetic',None)):
            with self.assertRaisesRegex(ValueError,'source pixels changed'):
                verifier.verify(self.root,True)


if __name__ == '__main__':
    unittest.main()
