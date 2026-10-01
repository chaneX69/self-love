"""Build full-library evidence, palettes and plotted histograms without retouching."""
import argparse
from collections import Counter
import csv
import html
import json
from pathlib import Path
import shutil
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from film_color import color_distribution, palette, sample, save_json, sha256, srgb_image
from reference_sources import archive_index, load_reference, source_path


def plot_font(size):
    for family in ['DejaVuSansMono.ttf', '/System/Library/Fonts/Menlo.ttc']:
        try:
            return ImageFont.truetype(family, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def reviews(path):
    result = {}
    for r in csv.DictReader(Path(path).open(), delimiter='|'):
        for span in r['ids'].split(','):
            a, b = int(span.split('-')[0]), int(span.split('-')[-1])
            for number in range(a, b+1):
                if number in result:
                    raise ValueError(f'Duplicate review {number}')
                result[number] = {'scene_type': r['scene'], 'lighting': r['lighting'],
                                  'materials': r['materials'].split(','),
                                  'gates': [] if r['gates']=='none' else r['gates'].split(','),
                                  'observation': r['observation'],
                                  'review_scale': 'contact-sheet scene review; original-frame notes linked',
                                  'texture_boundary': 'Qualitative visual evidence only; frequency/roughness not measured',
                                  'material_boundary': 'Frame-level visible material candidates, not per-pixel labels'}
    return result


def plots(frame, output):
    font = plot_font(17)
    im = Image.new('RGB', (1100, 420), '#f7f8fa')
    d = ImageDraw.Draw(im)
    d.text((24, 12), f"FRAME {frame['scene']:03d} / sampled sRGB / pixel counts, independent vertical scales", font=font, fill='#142329')
    series = [('CIELAB L* (0-100)', frame['L_histogram_100'], '#263e49')]
    series += [(f'{c} encoded sRGB (0-255)', frame['RGB_histograms_256'][i], col)
               for i,(c,col) in enumerate(zip('RGB',['#c84243','#338251','#4169b4']))]
    for k,(title,counts,color) in enumerate(series):
        x, y = 25+(k%2)*545, 58+(k//2)*177
        peak = max(counts) or 1
        d.text((x,y), title+f' max={peak}', font=font, fill='#142329')
        d.line((x,y+132,x+505,y+132), fill='#9aa4ab')
        for j,v in enumerate(counts):
            left = x+j*505/len(counts)
            right = x+(j+1)*505/len(counts)
            d.rectangle((left,y+132-v/peak*103,max(left,right-1),y+132), fill=color)
        d.text((x,y+137),'0',font=font,fill='#49565d')
        d.text((x+465,y+137),'100' if k==0 else '255',font=font,fill='#49565d')
    im.save(output/'histograms'/f"{frame['scene']:03d}.png")
    card = Image.new('RGB',(1100,258),'#f7f8fa')
    d = ImageDraw.Draw(card)
    d.text((16,8),f"FRAME {frame['scene']:03d} / 32 measured representative pixels / cluster area, not object area",font=font,fill='#142329')
    small = plot_font(11)
    for i,s in enumerate(frame['palette']):
        x,y=12+(i%16)*68,37+(i//16)*110
        d.rectangle((x,y,x+64,y+51),fill=s['hex'])
        d.text((x,y+56),s['hex'],font=small,fill='#142329')
        d.text((x,y+73),f"{s['share']*100:.1f}%",font=small,fill='#142329')
        d.text((x,y+88),f"L{s['lab'][0]:.1f}",font=small,fill='#142329')
    card.save(output/'palettes'/f"{frame['scene']:03d}.png")


def relation_plot(frame, output):
    font = plot_font(15)
    im = Image.new('RGB', (1100, 425), '#f7f8fa')
    d = ImageDraw.Draw(im)
    data = frame['color_distribution']
    counts = np.asarray(data['hue_by_tone_counts'])
    d.text((16, 12), f"FRAME {frame['scene']:03d} / hue x L* / percent of ALL retained samples", font=font, fill='#142329')
    d.text((690, 12), '3x3 original-position grid / L* P50', font=font, fill='#142329')
    for i, label in enumerate(data['hue_labels']):
        y = 71+i*25
        d.text((16, y), label, font=font, fill='#142329')
        for j in range(5):
            share = counts[i, j]/frame['sampled_pixels']
            x = 154+j*102
            v = int(246-165*np.sqrt(share/(counts.max()/frame['sampled_pixels'] or 1)))
            d.rectangle((x, y, x+97, y+23), fill=(v, min(255,v+15), min(255,v+25)))
            d.text((x+9, y+1), f'{share*100:.2f}%', font=font, fill='#081922')
    for j in range(5):
        d.text((157+j*102, 45), f'L{j*20}-{(j+1)*20}', font=font, fill='#142329')
    for cell in data['spatial_grid_3x3']:
        x, y = 700+cell['column']*123, 78+cell['row']*99
        med = cell['L5_L50_L95'][1] if cell['L5_L50_L95'] else 0
        v = int(60+med*1.8)
        d.rectangle((x, y, x+113, y+84), fill=(v,v,v), outline='#728189')
        d.text((x+15,y+28), f'{med:.1f}', font=font, fill='white' if med<40 else '#111111')
    d.text((696,389), 'Grid is position, not a material mask', font=font, fill='#142329')
    (output/'relations').mkdir(exist_ok=True)
    im.save(output/'relations'/f"{frame['scene']:03d}.png")


def build(args):
    inputs=json.loads(Path(args.inventory).read_text())
    old=inputs['frames'] if isinstance(inputs,dict) else inputs
    registry=archive_index()
    protected={p for row in old if (p:=source_path(row,required=False,registry=registry))}
    if Path(args.catalog).resolve() in protected:
        raise ValueError('Catalog output may not overwrite a source screenshot')
    if len({row['scene'] for row in old})!=len(old):
        raise ValueError('Duplicate frame IDs')
    rv=reviews(args.reviews)
    if set(rv)!={r['scene'] for r in old}:
        raise ValueError('Reviews and inventory must cover exactly the same frame IDs')
    out=Path(args.output)
    for sub in ['histograms','palettes','previews']:
        (out/sub).mkdir(parents=True,exist_ok=True)
    frames=[]
    for row in sorted(old,key=lambda x:x['scene']):
        n=row['scene']
        im,status,path=load_reference(row,registry=registry)
        file_hash=sha256(path)
        if list(im.size)!=row['dimensions']:
            raise ValueError(f'Source dimensions mismatch {n}')
        exclusions=list(row.get('analysis_exclusions',[]))
        if not exclusions:
            # Preserve machine-readable exclusions recovered from the earlier audit.
            for text in row.get('excluded_regions',[]):
                if ': [' in text:
                    try:
                        rect=json.loads(text.rsplit(': ',1)[1])
                        if len(rect)==4:
                            exclusions.append({'label':text.rsplit(': ',1)[0],'rect':rect})
                    except (ValueError,TypeError):
                        pass
        if not row.get('analysis_exclusions') and n in [532,668]:
            exclusions.append({'label':'central panel gutter','rect':[.495,0,.511,1]})
        if not row.get('analysis_exclusions') and n==569:
            for a,b in [(.163,.181),(.326,.347),(.49,.511),(.652,.678),(.817,.839)]:
                exclusions.append({'label':'panel gutter','rect':[a,0,b,1]})
        if not row.get('analysis_exclusions') and n==261:
            for a,b in [(.322,.338),(.648,.665)]:
                exclusions.append({'label':'panel gutter','rect':[a,0,b,1]})
        rgb,xy=sample(im,exclusions=exclusions)
        swatches,lab=palette(rgb,xy)
        for i,s in enumerate(swatches):
            s['id']=f'{n:03d}-S{i+1:02d}'
            assert list(im.getpixel(tuple(s['xy'])))==s['rgb']
        lhist=np.histogram(np.clip(lab[:,0],0,100),bins=np.linspace(0,100,101))[0].tolist()
        rhist=[np.bincount(rgb[:,i],minlength=256).tolist() for i in range(3)]
        percentiles=dict(zip(['P1','P5','P25','P50','P75','P95','P99'],np.percentile(lab[:,0],[1,5,25,50,75,95,99]).round(5).tolist()))
        details=[]
        if row.get('observation'):
            details.append({'text':row['observation'],'source':str(Path(args.inventory))})
        details.extend(row.get('prior_visual_notes',[]))
        notes=row.get('evidence_notes',[])
        details.extend(notes)
        frame={'scene':n,'original':row['original'],'sha256':row['sha256'],'dimensions':row['dimensions'],
               'active':row['active'],'world':row['world'],'review':rv[n],'evidence_notes':details,
               'color_management':status,'analysis_region':[.01,.02,.98,.94],
               'analysis_exclusions':exclusions,'sample_step':4,'sampled_pixels':len(rgb),
               'L_percentiles':percentiles,'L_histogram_100':lhist,'RGB_histograms_256':rhist,
               'tone_band_counts':np.histogram(np.clip(lab[:,0],0,100),bins=[0,20,40,60,80,100])[0].tolist(),
               'palette':swatches,'chart':f'histograms/{n:03d}.png','palette_card':f'palettes/{n:03d}.png',
               'preview':f'previews/{n:03d}.jpg',
               'color_distribution':color_distribution(lab,xy,im.size), 'relation_chart':f'relations/{n:03d}.png'}
        assert sum(lhist)==len(rgb) and all(sum(h)==len(rgb) for h in rhist)
        assert sum(s['count'] for s in swatches)==len(rgb)
        thumb=im.copy()
        thumb.thumbnail((960,480))
        thumb.save(out/frame['preview'],quality=88)
        plots(frame,out)
        relation_plot(frame,out)
        for key in ['reference_asset','reference_file_sha256','pixel_sha256','classification','texture_summary',
                    'source_filename','text_record','storage','semantic_texture_review']:
            if key in row:
                frame[key]=row[key]
        if row.get('texture_summary'):
            frame['review']['texture_boundary']=row['review']['texture_boundary']
        assert sha256(path)==file_hash
        frames.append(frame)
        if len(frames)%50==0:
            print(f'Computed and source-verified {len(frames)}/{len(old)}',flush=True)
    doc={k:v for k,v in inputs.items() if k!='frames'} if isinstance(inputs,dict) else {}
    doc.update({'schema_version':max(1,doc.get('schema_version',1)),'reference_only':True,
         'method':'sampled-sRGB-median-cut-real-pixel-Lab-D65-2deg',
         'source_count':len(frames),'active_count':sum(f['active'] for f in frames),'frames':frames})
    if 'representative_count' in doc:
        doc['representative_count']=sum(bool(f.get('reference_asset')) for f in frames)
    save_json(args.catalog,doc)
    report_doc={**doc,'frames':[{**f,'resolved_reference':source_path(f,registry=registry).as_uri()} for f in frames]}
    save_json(out/'frames.json',report_doc)
    shutil.copy2(args.reviews,out/'frame-reviews.tsv')
    with (out/'frames.csv').open('w') as f:
        writer=csv.writer(f)
        writer.writerow(['frame','active','world','scene','lighting','materials','gates','observation','L5','L50','L95','swatches','sha256'])
        for r in frames:
            v=r['review']
            writer.writerow([r['scene'],r['active'],r['world'],v['scene_type'],v['lighting'],','.join(v['materials']),','.join(v['gates']),v['observation'],r['L_percentiles']['P5'],r['L_percentiles']['P50'],r['L_percentiles']['P95'],len(r['palette']),r['sha256']])
    source=Path(__file__).with_name('film_library_report.html').read_text()
    payload=json.dumps(report_doc,ensure_ascii=False).replace('</','<\\/')
    (out/'index.html').write_text(source.replace('__LIBRARY_DATA__',payload))
    save_json(out/'coverage.json',{'frames':len(frames),'active':doc['active_count'],
        'archive':sum(not f['active'] for f in frames),'conditional':sum(f['active'] and bool(f['review']['gates']) for f in frames),
        'normal':sum(f['active'] and not f['review']['gates'] for f in frames),
        'palettes':len(frames),'swatches':sum(len(f['palette']) for f in frames),'histogram_charts':len(frames),
        'hue_lightness_joint_tables':len(frames),'spatial_3x3_tables':len(frames),'relation_charts':len(frames),
        'scene_reviews':len(rv),'histogram_totals_verified':True,'swatch_pixel_identity_verified':True,
        'all_source_hashes_verified_before_and_after':True,
        'material_segmentation':'not claimed; target pixel review is mandatory before generation',
        'microscopic_texture_measurements':'not claimed',
        'scene_counts':dict(Counter(f['review']['scene_type'] for f in frames))})
    print(json.dumps({'complete':len(frames),'catalog':args.catalog,'report':str(out/'index.html')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for key in ['inventory','reviews','catalog','output']:
        parser.add_argument('--'+key,required=True)
    build(parser.parse_args())
