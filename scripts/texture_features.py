"""Regional texture-form measurements, explicitly not semantic print masks."""
import hashlib
import numpy as np

CLASSES = ['low-contrast', 'directional-structure', 'periodic-structure', 'mixed-detail']
METHOD = {
    'id': 'regional-texture-forms-v1', 'tile_size_pixels': 128,
    'input': 'ICC-managed full-resolution sRGB; no resize, sharpening, or denoising',
    'luma': '0.2126 R-prime + 0.7152 G-prime + 0.0722 B-prime, range 0..255; not linear luminance',
    'fft': 'Mean-removed Hann-window rFFT; 0.02..0.45 cycles/pixel; top-8 energy concentration',
    'coherence': 'Global tile gradient structure tensor, central differences',
    'thresholds': {'std_low':3.0, 'directional_coherence':0.65, 'periodic_peak_share':0.22},
    'assignment_order': CLASSES,
    'denominator': 'Valid original-image pixels inside non-overlapping tiles with >=90% valid ROI; edge padding not counted',
    'proportion_unit': 'Area of classified tile footprints; NOT ink-pixel coverage or material area',
    'sensitivity': 'Threshold multipliers 0.8, 1.0, 1.2; min/max range is not a statistical confidence interval',
    'semantic_boundary': 'Directional forms may be hatching, hair, brick, fabric, or geometry. Periodic forms may be dots, screen mesh, windows, or aliasing. No automatic halftone/hatching/mesh/misregistration percentage claim.',
    'semantic_occupancy': {'halftone':None, 'hatching':None, 'screen_mesh':None, 'color_misregistration':None},
    'semantic_status': 'unmeasured; needs original-pixel semantic annotation before unique-evidence purge',
    'columns': ['x','y','width','height','valid_pixels','class_index','std','coherence','fft_peak_share','dominant_cycles_per_pixel','gradient_angle_degrees'],
}


def pixel_hash(im):
    prefix = f'RGB:{im.width}x{im.height}:'.encode('ascii')
    return hashlib.sha256(prefix + im.convert('RGB').tobytes()).hexdigest()


def classify(std, coherence, peak, factor=1.0):
    return np.where(std < 3*factor, 0,
                    np.where(coherence >= min(.99,.65*factor), 1,
                             np.where(peak >= .22*factor, 2, 3)))


def measure(im, rect, exclusions=()):
    array = np.asarray(im).astype(np.float32)
    h,w = array.shape[:2]
    gray = array @ np.array([.2126,.7152,.0722], dtype=np.float32)
    yy,xx = np.mgrid[:h,:w]
    a,b,c,d = rect
    valid = (xx>=a*w)&(xx<c*w)&(yy>=b*h)&(yy<d*h)
    for exclusion in exclusions:
        a,b,c,d = exclusion['rect']
        valid &= ~((xx>=a*w)&(xx<c*w)&(yy>=b*h)&(yy<d*h))
    size=128
    tiles, bounds, areas = [], [], []
    left,top = int(np.ceil(rect[0]*w)),int(np.ceil(rect[1]*h))
    right,bottom = int(np.ceil(rect[2]*w)),int(np.ceil(rect[3]*h))
    for y in range(top,bottom,size):
        for x in range(left,right,size):
            width,height=min(size,right-x),min(size,bottom-y)
            mask=valid[y:y+height,x:x+width]
            area=int(mask.sum())
            if area < .9*width*height or min(width,height)<16:
                continue
            tile=gray[y:y+height,x:x+width].copy()
            tile[~mask]=tile[mask].mean()
            tiles.append(np.pad(tile,((0,size-height),(0,size-width)),mode='reflect'))
            bounds.append([x,y,width,height])
            areas.append(area)
    tiles=np.stack(tiles)
    areas=np.array(areas)
    std=tiles.std(axis=(1,2))
    dx=(tiles[:,1:-1,2:]-tiles[:,1:-1,:-2])/2
    dy=(tiles[:,2:,1:-1]-tiles[:,:-2,1:-1])/2
    jxx=(dx*dx).mean(axis=(1,2)); jyy=(dy*dy).mean(axis=(1,2)); jxy=(dx*dy).mean(axis=(1,2))
    coherence=np.sqrt((jxx-jyy)**2+4*jxy**2)/(jxx+jyy+1e-12)
    angle=(np.degrees(.5*np.arctan2(2*jxy,jxx-jyy))+180)%180
    window=np.outer(np.hanning(size),np.hanning(size))
    fft=np.abs(np.fft.rfft2((tiles-tiles.mean(axis=(1,2),keepdims=True))*window))**2
    fy,fx=np.meshgrid(np.fft.fftfreq(size),np.fft.rfftfreq(size),indexing='ij')
    radius=np.hypot(fx,fy)
    band=(radius>=.02)&(radius<=.45)
    power=fft[:,band]
    peak=np.partition(power,-8,axis=1)[:,-8:].sum(axis=1)/(power.sum(axis=1)+1e-12)
    frequency=radius[band][power.argmax(axis=1)]
    labels=classify(std,coherence,peak)
    denominator=int(areas.sum())
    variants=[]
    for factor in [.8,1,1.2]:
        ls=classify(std,coherence,peak,factor)
        variants.append(np.bincount(ls,weights=areas,minlength=4)/denominator)
    variants=np.array(variants)
    counts=np.bincount(labels,weights=areas,minlength=4).astype(int)
    tile_rows=[]
    for i,bound in enumerate(bounds):
        tile_rows.append(bound+[int(areas[i]),int(labels[i]),round(float(std[i]),4),
            round(float(coherence[i]),6),round(float(peak[i]),6),round(float(frequency[i]),6),round(float(angle[i]),3)])
    return {'method':METHOD['id'],'valid_roi_pixels':int(valid.sum()),'measured_footprint_pixels':denominator,
            'unmeasured_roi_pixels':int(valid.sum())-denominator,
            'coverage':round(denominator/int(valid.sum()),8),'tile_count':len(tiles),
            'forms':{name:{'footprint_pixels':int(counts[i]),'share':round(float(counts[i]/denominator),8),
                    'threshold_sensitivity_min_max':variants[:,i][[variants[:,i].argmin(),variants[:,i].argmax()]].round(8).tolist()}
                     for i,name in enumerate(CLASSES)},
            'semantic_occupancy':METHOD['semantic_occupancy'].copy(),
            'semantic_status':METHOD['semantic_status'],'tiles':tile_rows}
