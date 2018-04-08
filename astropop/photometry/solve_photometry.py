# Licensed under a 3-clause BSD style license - see LICENSE.rst
import numpy as np

__all__ = ['solve_photometry_montecarlo', 'solve_photometry_median',
           'solve_photometry_average']


def _scale_operator(measure_scale, out_scale):
    '''Put references and measures in the same scale and return the correct
    opertators.'''
    diff = None  # find the out/measure ratio (- for mag)
    corr = None  # correct the measure by diff (+ for mag)
    trans_flux = None  # transform the measure to out scale
    # error_func = None  # error of the final calculation
    if out_scale == 'mag':
        diff = np.subtract
        corr = np.add
        if measure_scale == 'linear':
            def trans_flux(x): -2.5*np.log10(x) + 25
            # def error_func(x, x_e): 1.086*((x_e + np.sqrt(x))/x)
        elif measure_scale == 'log':
            def trans_flux(x): -2.5*x + 25
        elif measure_scale == 'mag':
            def trans_flux(x): x
    elif out_scale == 'log':
        diff = np.subtract
        corr = np.add
        if measure_scale == 'linear':
            def trans_flux(x): np.log10(x)
        elif measure_scale == 'log':
            def trans_flux(x): x
        elif measure_scale == 'mag':
            def trans_flux(x): x/(-2.5) + 10
    elif out_scale == 'linear':
        diff = np.divide
        corr = np.multiply
        if measure_scale == 'linear':
            def trans_flux(x): x
        elif measure_scale == 'log':
            def trans_flux(x): 10**x
        elif measure_scale == 'mag':
            def trans_flux(x): 10**(-0.4*x + 10)

    return trans_flux, diff, corr


def solve_photometry_median(fluxes, flux_error, references, limits=(5, 18),
                            flux_scale='linear', ref_scale='mag'):
    """Solve the photometry by the median comparison of field stars."""
    trans_func, diff_func, corr_func = _scale_operator(flux_scale, ref_scale)
    mags = trans_func(fluxes)

    a, b = limits
    a, b = a, b if a < b else b, a
    args = np.where(np.logical_and(references >= a, references <= b))

    diff = diff_func(references, mags)
    dif = np.nanmedian(diff[args])
    err = np.nanstd(diff[args])

    # now we assume just the statistical error
    error = err
    return corr_func(mags, dif), error


def solve_photometry_average(fluxes, flux_error, references, limits=(5, 18),
                             flux_scale='linear', ref_scale='mag'):
    trans_func, diff_func, corr_func = _scale_operator(flux_scale, ref_scale)
    mags = trans_func(fluxes)

    a, b = limits
    a, b = a, b if a < b else b, a
    args = np.where(np.logical_and(references >= a, references <= b))

    diff = diff_func(references, mags)
    dif = np.nanaverage(diff[args], weights=np.divide(1, flux_error[args]))
    err = np.nanstd(diff[args])

    error = err
    return corr_func(mags, dif), error


def _montecarlo_loop(args):
    mags = args[0]
    references = args[1]
    n_stars = args[2]
    diff_func = args[3]
    corr_func = args[4]

    iter_mags = np.zeros(len(mags))
    iter_mags[:] = np.nan

    choices = np.random.choice(len(mags), n_stars)
    iter_mags = np.nanmedian(diff_func(references[choices], mags[choices]))
    return corr_func(mags, iter_mags)


def solve_photometry_montecarlo(fluxes, flux_error, ref_mags, limits=(5, 18),
                                n_iter=100, n_stars=0.2,
                                flux_scale='linear', ref_scale='mag'):
    trans_func, diff_func, corr_func = _scale_operator(flux_scale, ref_scale)
    mags = trans_func(fluxes)

    if float(n_stars).is_integer():
        n_stars = n_stars
    else:
        n_stars = max(1, int(n_stars*len(fluxes)))

    nrefs = np.array(ref_mags)
    lim = sorted(limits)
    filt = np.where(np.logical_or(nrefs < lim[0], nrefs > lim[1]))
    nrefs[filt] = np.nan

    args = (mags, nrefs, n_stars, diff_func, corr_func)
    iter_mags = [_montecarlo_loop(args) for i in range(n_iter)]

    result = np.nanmedian(iter_mags, axis=0)
    errors = np.nanstd(iter_mags, axis=0)
    return result, errors
