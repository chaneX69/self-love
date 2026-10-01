import gzip
import json
import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, PngImagePlugin
from film_color import sha256
from texture_features import pixel_hash
from verify_reference_privacy import require_private_workspace_paths, verify


class ReferencePrivacyTests(unittest.TestCase):
    def fixture(self, root):
        (root/'data').mkdir()
        (root/'assets/references').mkdir(parents=True)
        (root/'SKILL.md').write_text('Synthetic test fixture, not a visual style reference.\n')
        asset = root/'assets/references/001.webp'
        im = Image.new('RGB', (40, 30), (15, 30, 45))
        im.save(asset, lossless=True)
        frame = {'scene': 1, 'original': 'evidence://sha256/'+'0'*64,
                 'sha256': '0'*64, 'dimensions': [40, 30], 'pixel_sha256': pixel_hash(im),
                 'reference_asset': asset.relative_to(root).as_posix(),
                 'reference_file_sha256': sha256(asset)}
        (root/'data/film-library.json').write_text(json.dumps({'frames': [frame]}))
        (root/'data/representatives.json').write_text(json.dumps({'selected': [1], 'count': 1}))
        return asset

    def test_complete_movie_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            result = verify(root)
            self.assertEqual(result['status'], 'passed', result)
            self.assertEqual(result['movie_references_verified'], 1)

    def test_explicit_git_checkout_still_checks_untracked_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root/'.git').mkdir()
            (root/'.git/HEAD').write_text('ref: refs/heads/main\n')
            self.assertEqual(verify(root)['status'],'failed')
            result = subprocess.CompletedProcess([],0,stdout=str(root)+'\n',stderr='')
            with patch('verify_reference_privacy.subprocess.run',return_value=result):
                self.assertEqual(verify(root,git_checkout=True)['status'],'passed')
                Image.new('RGB',(8,8)).save(root/'untracked.png')
                self.assertIn('image-not-in-film-manifest',
                              {i['reason'] for i in verify(root,git_checkout=True)['issues']})

    def test_git_checkout_root_cannot_be_forged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root/'.git').mkdir()
            result = subprocess.CompletedProcess([],0,stdout=str(root.parent)+'\n',stderr='')
            with patch('verify_reference_privacy.subprocess.run',return_value=result):
                with self.assertRaisesRegex(ValueError,'root mismatch'):
                    verify(root,git_checkout=True)

    def test_crop_edition_cannot_include_full_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root/'data/distribution.json').write_text(json.dumps({'edition':'crop-only'}))
            reasons = {i['reason'] for i in verify(root)['issues']}
            self.assertIn('full-frame-in-crop-only-edition',reasons)
            self.assertIn('invalid-palette-crop-manifest',reasons)

    def test_unknown_image_even_with_text_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            Image.new('RGB', (8, 8)).save(root/'notes.txt', format='PNG')
            self.assertIn('image-not-in-film-manifest', {i['reason'] for i in verify(root)['issues']})

    def test_modified_and_missing_movie_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asset = self.fixture(root)
            Image.new('RGB', (40, 30), (5, 6, 7)).save(asset, lossless=True)
            self.assertIn('film-pixel-or-hash-mismatch', {i['reason'] for i in verify(root)['issues']})
            asset.unlink()
            self.assertIn('missing-film-reference', {i['reason'] for i in verify(root)['issues']})

    def test_link_and_runtime_cache_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asset = self.fixture(root)
            alias = root/'alias.webp'
            alias.symlink_to(asset)
            self.assertEqual(verify(root)['issues'][0]['reason'], 'symbolic-link')
            alias.unlink()
            (root/'runtime.pyc').write_bytes(b'cache')
            self.assertIn('private-or-runtime-artifact', {i['reason'] for i in verify(root)['issues']})

    def test_text_and_gzip_private_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            private = '/' + 'Users' + '/synthetic-person/photo.png'
            (root/'notes.md').write_text(private)
            self.assertIn('machine-user-path', {i['reason'] for i in verify(root)['issues']})
            (root/'notes.md').unlink()
            with gzip.open(root/'data/semantic-texture-candidates.jsonl.gz', 'wt') as stream:
                stream.write(json.dumps({'private': private})+'\n')
            self.assertIn('machine-user-path', {i['reason'] for i in verify(root)['issues']})

    def test_inline_encoded_media_and_unknown_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root/'example.html').write_text('data'+'%3Aimage/png;base64,AA==')
            (root/'payload.zip').write_bytes(b'archive')
            reasons = {i['reason'] for i in verify(root)['issues']}
            self.assertIn('embedded-media', reasons)
            self.assertIn('unregistered-file-type', reasons)

    def test_media_metadata_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asset = self.fixture(root)
            meta = PngImagePlugin.PngInfo()
            meta.add_text('Description', 'Private fixture description')
            Image.new('RGB', (40, 30)).save(asset, format='PNG', pnginfo=meta)
            self.assertIn('unreviewed-image-metadata', {i['reason'] for i in verify(root)['issues']})

    def test_external_paths_and_symlink_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base/'skill'
            root.mkdir()
            self.fixture(root)
            require_private_workspace_paths(base/'private/result.json', root=root)
            with self.assertRaisesRegex(ValueError, 'outside skill'):
                require_private_workspace_paths(root/'result.json', root=root)
            (base/'alias').symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'outside skill'):
                require_private_workspace_paths(base/'alias/result.json', root=root)
            (root/'escape').symlink_to(base, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'outside skill'):
                require_private_workspace_paths(root/'escape/result.json', root=root)

    def test_another_skill_copy_is_not_a_private_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'backup'
            root.mkdir()
            (root/'SKILL.md').write_text('Fixture skill')
            with self.assertRaisesRegex(ValueError, 'outside skill'):
                require_private_workspace_paths(root/'result.html', root=Path(tmp)/'active')

    def test_matcher_rejects_skill_output_before_reading_photo(self):
        from match_photo_palette import main
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'SKILL.md').write_text('Fixture skill')
            with patch('match_photo_palette.run') as run:
                with self.assertRaisesRegex(ValueError, 'outside skill'):
                    main(['--plan', str(root.parent/'missing-plan.json'),
                          '--output', str(root/'result.json')])
                run.assert_not_called()
            self.assertFalse((root/'result.json').exists())
            self.assertFalse((root/'result.html').exists())

    def test_matcher_rejects_a_source_inside_skill(self):
        from match_photo_palette import run
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'SKILL.md').write_text('Fixture skill')
            with self.assertRaisesRegex(ValueError, 'outside skill'):
                run({'source': str(root/'source.jpg')}, {}, 'unused')


if __name__ == '__main__':
    unittest.main(verbosity=2)
