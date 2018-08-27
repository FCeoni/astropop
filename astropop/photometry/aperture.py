# Licensed under a 3-clause BSD style license - see LICENSE.rst

import sep
import numpy as np
from scipy.stats import sigmaclip
from astropy.table import Table

from ..math.array import xy2r, trim_array
from ._utils import _sep_fix_byte_order
from .detection import calc_fwhm
from ..logger import logger
from ..fits_utils import imhdus


def sky_annulus(data, x, y, r_ann, algorithm='mmm', mask=None):
    """Determine the sky value of a single pixel based on a sky annulus.

    Parameters:
    -----------
        - data : np.ndarray
            2D image data for photometry
        - x, y : array_like
            Positions of the sources
        - r_ann : array_like([float, float])
            Annulus radius (intern and extern) to calculate the background value
        - algorithm : 'mmm' or 'sigmaclip' (optional)
            Algorith to calculate the background value. 'mmm' (mean, median,
            mode) should be better for populated fields, while 'sigmaclip'
            (clipped mean) should be better for sparse fields.
            Default: 'mmm'

    Return:
    -------
        - sky : array_like
            The computed value of sky for each (x, y) source.
        - sky_error : array_like
            The error of sky value, computed as the sigma cliped stddev.
    """
    # TODO: this code needs optimization for faster work
    assert(len(x) == len(y))
    assert(len(r_ann) == 2)

    sky = np.zeros_like(x, dtype='f8')
    sky.fill(np.nan)
    sky_error = np.zeros_like(x, dtype='f8')
    sky_error.fill(np.nan)

    box_size = 2*int(np.max(r_ann)+2)  # Ensure the aperture is entirely in box
    r_ann = sorted(r_ann)

    indices = np.indices(data.shape)
    for i in range(len(x)):
        xi, yi = x[i]-0.5, y[i]-0.5  # needed to check pixel centers
        d, ix, iy = trim_array(data, box_size, (xi, yi), indices)
        if mask is not None:
            m = np.ravel(mask[iy, ix])
        r, f = xy2r(ix, iy, d, xi, yi)

        # Filter only values inside the annulus
        # To think: this do not perform subpixel, just check the pixel center
        filt = (r >= r_ann[0]) & (r <= r_ann[1])
        if mask is not None:
            filt = filt & ~m
        f = f[np.where(filt)]
        if len(f) < 1:
            logger.warn('No pixels for sky subtraction found at position {}x{}.'
                        .format(x[i], y[i]))
            sky[i] = 0
            sky_error[i] = 0
        else:
            for fi in range(5):
                f, _, _ = sigmaclip(f, 3, 3)
            mean = np.nanmean(f)
            median = np.nanmedian(f)
            sky_error[i] = np.nanstd(f)
            if algorithm == 'mmm':
                # mimic daophot using sigmaclip
                sky[i] = 3*median - 2*mean  # mmm mode estimator
            elif algorithm == 'sigmaclip':
                sky[i] = mean
            else:
                raise ValueError('Sky algorithm {} not supported.'
                                 .format(algorithm))

    return sky, sky_error


def aperture_photometry(data, x, y, r='auto', r_ann='auto', gain=1.0,
                        readnoise=None, mask=None, sky_algorithm='mmm'):
    """Perform aperture photometry using sep.

    Parameters:
    -----------
        - data : np.ndarray
            2D image data for photometry
        - x, y : array_like
            Positions of the sources
        - r : float or 'auto' (optional)
            Aperture radius. If `auto`, the value will be estimated based in
            the median gaussian FWHM of the sources in the image
            (r=0.6731*GFWHM).
            Default: 'auto'
        - r_ann : array_like([float, float]), None or 'auto' (optional)
            Annulus radii (r_in, r_out) for local background extraction.
            If `auto`, the annulus will be set based on aperture as (4*r, 6*r).
            If None, no local background subtraction will be performed.
            Default: 'auto'
        - gain : float (optional)
            Gain to correctly calculate the error.
        - readnoise : float (optional)
            Readnoise of the image to correctly calculate the error.
        - mask : np.ndarray (optional)
            Mask badpixels and problematic ccd areas.
        - sky_algorithm : 'mmm' or 'sigmaclip'
            Algorith to calculate the background value. 'mmm' (mean, median,
            mode) should be better for populated fields, while 'sigmaclip'
            (clipped median) should be better for sparse fields.
            Default: 'mmm'
    """
    res_ap = Table()

    if isinstance(data, imhdus):
        data = data.data

    data = _sep_fix_byte_order(data)
    x = np.array(x)
    y = np.array(y)

    if gain is None:
        gain = 1.0
    kwargs = {'gain': gain,
              'err': readnoise,
              'subpix': 0}

    res_ap['x'] = x
    res_ap['y'] = y

    if r == 'auto':
        logger.debug('Aperture r set as `auto`. Calculating from FWHM.')
        fwhm = calc_fwhm(data, x, y, box_size=25, model='gaussian')
        r = 0.6371*fwhm
        res_ap.meta['fwhm'] = fwhm
        res_ap.meta['r_auto'] = True
        logger.debug('FWHM:{} r:{}'.format(fwhm, r))

    res_ap['aperture'] = [r]*len(x)

    if r_ann == 'auto':
        logger.debug('Aperture r_ann set as `auto`. Calculating from r.')
        r_in = int(round(4*r, 0))
        r_out = int(max(r_in+10, round(6*r, 0)))  # Ensure a dannulus geq 10
        r_ann = (r_in, r_out)
        logger.debug('r_ann:{}'.format(r_ann))

    # from .daophot.aper import aper
    # if r_ann is None:
    #     mag,magerr,flux,fluxerr,sky,skyerr,badflag,outstr = \
    #             aper(data, x , y, phpadu=1, apr=r, zeropoint=25,
    #                  badpix=[-12000,60000], exact=True)
    # else:
    #     mag,magerr,flux,fluxerr,sky,skyerr,badflag,outstr = \
    #             aper(data, x , y, phpadu=1, apr=r, skyrad=list(r_ann),
    #                  zeropoint=25, badpix=[-12000,60000], exact=True)
    #
    # res_ap['flux'] = flux
    # res_ap['flux_error'] = fluxerr
    # res_ap['flags'] = badflag
    # res_ap['sky'] = sky
    # res_ap['sky_error'] = skyerr
    # res_ap['outstr'] = outstr

    sky = None

    flux, flux_error, flags = sep.sum_circle(data, x, y, r, mask=mask,
                                             **kwargs)
    if r_ann is not None:
        ri, ro = r_ann
        res_ap.meta['r_in'] = ri
        res_ap.meta['r_out'] = ro

        sky, error = sky_annulus(data, x, y, r_ann, algorithm=sky_algorithm,
                                 mask=mask)

        # SEP do not expose aperture area, so we calculate
        nkwargs = kwargs.copy()
        nkwargs['gain'] = 1.0 # ensure gain not change the area
        ones = _sep_fix_byte_order(np.ones(data.shape, dtype='<f8'))
        area, _, _ = sep.sum_circle(ones, x, y, r, mask=mask, **nkwargs)

        # TODO: check these calculations
        # recompute flux, flux_error and flags
        flux -= sky*area
        bkgerr = np.sqrt((error + np.absolute(sky)/gain)*area)
        flux_error = np.hypot(flux_error, bkgerr)

    res_ap['flux'] = flux
    res_ap['flux_error'] = flux_error
    res_ap['flags'] = flags

    if sky is not None:
        res_ap['sky'] = sky

    return res_ap
