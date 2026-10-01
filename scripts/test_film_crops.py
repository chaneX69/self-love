import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from film_color import sha256
from film_crops import crop_manifest, load_crop
from texture_features import pixel_hash
import test_reference_privacy
from verify_reference_privacy import verify


class FilmCropTests(unittest.TestCase):
    def fixture(self, root):
        test_reference_privacy.ReferencePrivacyTests().fixture(root)
        frame = json.loads((root/'data/film-library.json').read_text())['frames'][0]
        im = Image.open(root/frame['reference_asset']).convert('RGB').crop((2, 3, 12, 13))
        asset = root/'assets/crops/001-test-region.webp'
        asset.parent.mkdir(parents=True)
        im.save(asset, lossless=True)
        record = {'id': '001-test-region', 'scene': 1, 'class': 'screen_mesh', 'rect': [2, 3, 10, 10],
                  'source_sha256': frame['sha256'], 'source_pixel_sha256': frame['pixel_sha256'],
                  'crop_pixel_sha256': pixel_hash(im), 'overlay_review': {'status': 'accepted_candidate'}}
        with gzip.open(root/'data/semantic-texture-candidates.jsonl.gz', 'wt') as stream:
            stream.write(json.dumps(record)+'\n')
        row = {k:v for k,v in record.items() if k != 'overlay_review'}
        row.update(asset=asset.relative_to(root).as_posix(), dimensions=[10,10], file_sha256=sha256(asset))
        doc = {'schema_version': 1, 'full_frame_replacement': False, 'count': 1, 'crops': [row]}
        self.write(root, doc)
        return frame, asset, doc

    def write(self, root, doc):
        (root/'data/film-crops.json').write_text(json.dumps(doc))

    def test_traced_crop_passes_without_external_original(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            frame, _, doc = self.fixture(root)
            rows = crop_manifest(root, [frame])
            self.assertEqual(len(rows), 1)
            with load_crop(root, doc['crops'][0]) as im:
                self.assertEqual(im.size, (10,10))
            result = verify(root)
            self.assertEqual(result['status'], 'passed', result)
            self.assertEqual(result['movie_crops_verified'], 1)

    def test_forged_provenance_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            frame, _, original = self.fixture(root)
            for field, value in [('rect', [1,1,10,10]), ('class', 'hatching'),
                                 ('source_sha256', 'f'*64), ('crop_pixel_sha256', 'f'*64)]:
                doc = copy.deepcopy(original)
                doc['crops'][0][field] = value
                self.write(root, doc)
                with self.assertRaises(ValueError):
                    crop_manifest(root, [frame])

    def test_unsafe_path_duplicate_and_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            frame, _, original = self.fixture(root)
            for update in ({'asset': '../outside.webp'}, {'dimensions': [20,20]}):
                doc = copy.deepcopy(original)
                doc['crops'][0].update(update)
                self.write(root, doc)
                with self.assertRaises(ValueError):
                    crop_manifest(root, [frame])
            for rows in ([], original['crops']*2):
                doc = {**original, 'crops': rows}
                self.write(root, doc)
                with self.assertRaises(ValueError):
                    crop_manifest(root, [frame])

    def test_crop_tampering_and_missing_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, asset, doc = self.fixture(root)
            Image.new('RGB',(10,10),(1,2,3)).save(asset,lossless=True)
            with self.assertRaisesRegex(ValueError, 'file hash'):
                load_crop(root, doc['crops'][0])
            asset.unlink()
            self.assertIn('missing-film-crop', {r['reason'] for r in verify(root)['issues']})

    def test_no_false_full_frame_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            frame, _, doc = self.fixture(root)
            doc['full_frame_replacement'] = True
            self.write(root, doc)
            with self.assertRaises(ValueError):
                crop_manifest(root, [frame])

    def test_unregistered_movie_like_image_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            Image.new('RGB',(10,10)).save(root/'assets/crops/002-other.webp', lossless=True)
            self.assertIn('image-not-in-film-manifest', {r['reason'] for r in verify(root)['issues']})


if __name__ == '__main__':
    unittest.main()
