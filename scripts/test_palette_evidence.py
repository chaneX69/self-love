"""Native-crop regression tests use synthetic pixels, not private photos."""
import copy
import functools
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image
from skimage.color import rgb2lab

import match_photo_palette as matcher
import palette_evidence as evidence
from film_color import sha256
from texture_features import pixel_hash


class PaletteEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'data').mkdir()
        (self.root/'assets/palette-crops').mkdir(parents=True)
        im = Image.new('RGB',(16,16),(100,100,100))
        self.frame = dict(scene=1,original='evidence://sha256/'+'a'*64,sha256='a'*64,
                          pixel_sha256=pixel_hash(im),dimensions=[16,16],active=True,
                          review=dict(materials=['paint'],lighting='warm-day',gates=[]),
                          palette=[dict(id='001-01',xy=[6,7],rgb=[100,100,100],
                                        lab=rgb2lab(np.array([[100,100,100]])/255)[0].tolist(),
                                        hex='#646464',tone='midtone',count=256,share=1.0)])
        atlas = im.crop((4,4,12,12))
        self.path = self.root/'assets/palette-crops/001.webp'
        atlas.save(self.path,lossless=True)
        self.row = dict(scene=1,source_sha256=self.frame['sha256'],
                        source_pixel_sha256=self.frame['pixel_sha256'],
                        asset='assets/palette-crops/001.webp',dimensions=[8,8],
                        file_sha256=sha256(self.path),pixel_sha256=pixel_hash(atlas),
                        patches=[dict(swatch_id='001-01',rect=[4,4,8,8],tile=[0,0,8,8],
                                      pixel_sha256=pixel_hash(atlas))])
        self.swatch = dict(swatch_id='001-01',xy=[6,7])
        self.save()

    def save(self):
        (self.root/'data/palette-crops.json').write_text(json.dumps(dict(schema_version=1,
            full_frame_reconstruction=False,count=1,frames=[self.row])))

    def test_original_pixel_and_coordinates_without_original(self):
        index = evidence.palette_index(self.root)
        info = evidence.evidence_info(self.frame,self.swatch,index,root=self.root,registry={})
        self.assertEqual(info['evidence_scope'],'native-crop')
        self.assertEqual(info['atlas_sample_xy'],[2,3])
        self.assertEqual(evidence.palette_pixel(self.frame,self.swatch,index,root=self.root,registry={}),
                         (100,100,100))

    def test_tampered_pixels_and_file_blocked(self):
        self.row['pixel_sha256'] = 'b'*64
        with self.assertRaisesRegex(ValueError,'pixels changed'):
            evidence.load_atlas(self.frame,self.row,self.root)
        self.row['file_sha256'] = 'b'*64
        with self.assertRaisesRegex(ValueError,'file hash'):
            evidence.load_atlas(self.frame,self.row,self.root)

    def test_missing_evidence_not_approved(self):
        self.path.unlink()
        info = evidence.evidence_info(self.frame,self.swatch,{1:self.row},root=self.root,registry={})
        self.assertFalse(info['evidence_available'])
        with self.assertRaises(FileNotFoundError):
            evidence.palette_pixel(self.frame,self.swatch,{},root=self.root,registry={})

    def test_provenance_path_and_geometry_blocked(self):
        for updates in ({'source_sha256':'b'*64},{'source_pixel_sha256':'b'*64},
                        {'asset':'../outside.webp'},{'dimensions':[1,1]}):
            with self.assertRaises(ValueError):
                evidence.validate_palette_row(self.frame,dict(self.row,**updates))
        for rect in ([0,0,2,2],[-1,0,8,8],[4,4,20,20],[4.0,4,8,8]):
            row = copy.deepcopy(self.row)
            row['patches'][0]['rect'] = rect
            with self.assertRaises(ValueError):
                evidence.validate_palette_row(self.frame,row)

    def test_missing_duplicate_and_overlapping_patches_blocked(self):
        for patches in ([],self.row['patches']*2):
            with self.assertRaises(ValueError):
                evidence.validate_palette_row(self.frame,dict(self.row,patches=patches))
        frame = copy.deepcopy(self.frame)
        frame['palette'].append(dict(frame['palette'][0],id='001-02'))
        row = copy.deepcopy(self.row)
        row['patches'].append(dict(row['patches'][0],swatch_id='001-02'))
        with self.assertRaisesRegex(ValueError,'Overlapping'):
            evidence.validate_palette_row(frame,row)

    def test_symlink_blocked(self):
        outside = self.root/'outside.webp'
        self.path.rename(outside)
        self.path.symlink_to(outside)
        with self.assertRaises(ValueError):
            evidence.load_atlas(self.frame,self.row,self.root)

    def test_explicit_crop_context_required_for_matcher(self):
        photo = self.root/'synthetic-input.png'
        Image.new('RGB',(40,40),(100,100,100)).save(photo)
        plan = dict(source=str(photo),regions=[dict(id='wall',rect=[0,0,1,1],colors=1,
                    material='paint',lighting='warm-day',source_evidence='Synthetic pixels')])
        options = dict(root=self.root)
        with patch.object(matcher,'archive_index',return_value={}), \
             patch.object(matcher,'palette_index',return_value={1:self.row}), \
             patch.object(matcher,'evidence_info',functools.partial(evidence.evidence_info,**options)), \
             patch.object(matcher,'palette_pixel',functools.partial(evidence.palette_pixel,**options)):
            pending = matcher.run(plan,{'frames':[self.frame]},'catalog-test')
            query = pending['queries'][0]
            decision = dict(swatch_id='001-01',verified_material='paint',verified_lighting='warm-day',
                            verified_tone=query['source_anchor']['tone'],
                            pixel_review_evidence='Synthetic uniform paint',coherence_review='Identity color')
            approvals = dict(source_sha256=sha256(photo),catalog_sha256='catalog-test',
                             decisions={query['query_id']:decision})
            with self.assertRaisesRegex(ValueError,'context'):
                matcher.run(plan,{'frames':[self.frame]},'catalog-test',approvals)
            decision['crop_context_sufficient'] = True
            result = matcher.run(plan,{'frames':[self.frame]},'catalog-test',approvals)
            self.assertEqual(result['status'],'color-mapping-reviewed')
            self.assertFalse(result['photo_modified'])


if __name__ == '__main__':
    unittest.main()
