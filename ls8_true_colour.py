import os
import os.path
import click

from glob import glob

from wagl.acquisition import acquisitions

from calc_sat_solar import unpack, write_sat_solar
from calc_sat_solar import get_band_scale_offset, get_data
from calc_sat_solar import normalize_data
from calc_sat_solar import generate_rtc_raster

from Simple_Pan_Sharpen import Simple_Pan_Sharpen as pan
from Landsat8_atmospheric_correction import Landsat_ATCOR
import ContEnh

import numpy as np

from PIL import Image


MAX_REF = 12000
# Adjust the contrast and sharpeness
c_enh=2.3
#This specifies the midpoint of the contrast enhancement
#I have pulled out and hacked the PIL contrast enhancement so I 
#can set this to be independant of the actual image. Previously this
#is set as a mean value for each image.
c_mid=191
s_enh=1.5

def gamma(ary, brightness):
    return ((ary / 255.0) ** (1.0 / brightness)) * 255.0

def png_band(band, brightness):
    return gamma(np.clip(band.astype(float) / float(MAX_REF) * 255.0, 0, 255), brightness)


def atcor(rtc_data, radiance):
    Lp_0 = rtc_data['Lp_0']
    Eg_0 = rtc_data['Eg_0']
    T_up = rtc_data['T_up']
    S = rtc_data['S']
    print('Doing atcor')
    A = (np.pi*((radiance/10.0)-(Lp_0)))/((Eg_0)*T_up)
    return np.around(((A)/(1+(A*S)))*10000.0, decimals=0)

@click.command()
@click.option('--level1', type=click.Path(exists=True), required=True,
              help='location of level1 tar file')
@click.option('--outdir', type=click.Path(), required=True,
              help='output directory')
@click.option('--extent', type=(float, float, float, float), default=(None, None, None, None),
              help='extent to subset in UL-lat UL-lon LR-lat LR-lon format')
@click.option('--sharpen', is_flag=True, default=False,
              help='whether to pan sharpen')
@click.option('--ac', default=False)
@click.option('--brightness', type=float, default=2.0, help='overall brightness factor')
@click.option('--cleanup', is_flag=True, default=False,
              help='whether to clean up working directory')
def main(level1, outdir, extent, sharpen, ac, brightness, cleanup):
    VISIBLE_BANDS = ['B2', 'B3', 'B4']
    PAN_BAND = 'B8'
   
    acqs = acquisitions(level1)
    assert len(acqs.granules) == 1, 'cannot handle multi-granule datasets'
    granule = acqs.granules[0]
    acqs = {group: acqs.get_acquisitions(group=group, granule=granule, only_supported_bands=False)
            for group in acqs.groups}

    extracted = os.path.join(outdir, 'extracted')

    if not os.path.exists(os.path.join(extracted, '{}_{}'.format(granule, 'SOLAR-ZENITH.TIF'))):
        print('extracting... ', end='')
        os.makedirs(extracted, exist_ok=True)

        unpack(level1, extracted)
        write_sat_solar(granule, acqs['RES-GROUP-1'][0], extracted)
        print('done!')
    else:
        print('found extracted files')

    scale_offset_dict = get_band_scale_offset(glob(os.path.join(extracted, '*MTL.txt'))[0])
    data = get_data(extracted, extent, sharpen)

    rtc_data = generate_rtc_raster(data['SATELLITE-VIEW']['data'], data['SOLAR-ZENITH']['data'],
                                   data['SATELLITE-AZIMUTH']['data'], data['SOLAR-AZIMUTH']['data'])

    radiance = normalize_data(data, scale_offset_dict)

    if sharpen:
        bands_to_process = VISIBLE_BANDS + [PAN_BAND]
    else:
        bands_to_process = VISIBLE_BANDS

    if ac:
        rho = {key: atcor(rtc_data[key], radiance[key])
               for key in bands_to_process}
    else:
        rho = {key: radiance[key] for key in bands_to_process}

    if sharpen:
        sharpened = pan(*[rho[band] for band in bands_to_process])
    else:
        sharpened = {'blue': rho['B2'], 'green': rho['B3'], 'red': rho['B4']}

    png_bands = {band: png_band(sharpened[band], brightness) for band in ['blue', 'green', 'red']}


    jr = Image.fromarray(png_bands['red'].astype(np.uint8))
    jg = Image.fromarray(png_bands['green'].astype(np.uint8))
    jb = Image.fromarray(png_bands['blue'].astype(np.uint8))


    imrgb = Image.merge('RGB', (jr, jg, jb ))
    contrast=ContEnh.Contrast(imrgb,c_mid)
    imrgb_en=contrast.enhce(c_enh)
    #imrgb_en.save(out_image_name)
    imrgb_en.save(os.path.join(extracted, 'true_color.png'))


if __name__ == '__main__':
    main()
