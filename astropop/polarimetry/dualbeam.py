# Licensed under a 3-clause BSD style license - see LICENSE.rst

import abc
import numpy as np
from astropy.modeling.fitting import LevMarLSQFitter

from ._dualbeam_utils import HalfWaveModel, QuarterWaveModel

from ..logger import logger


__all__ = ['compute_theta', 'reduced_chi2', 'dualbeam_polarimetry']


_retarders = {'half': {'ncons': 4},
              'quarter': {'ncons': 8}}


def compute_theta(q, u):
    '''Giving q and u, compute theta'''
    # numpy arctan2 already looks for quadrants and is defined in [-pi, pi]
    theta = np.degrees(0.5*np.arctan2(u, q))
    # do not allow negative values
    if theta < 0:
        theta += 180
    return theta


class DualBeamPolarimetryBase(abc.ABC):
    """Base class for polarimetry computation."""
    def __init__(self, retarder):
        self._retarder = retarder


class SLSDualBeamPolarimetry(DualBeamPolarimetryBase):
    pass


class MBR84DualBeamPolarimetry(DualBeamPolarimetryBase):
    pass


def estimate_normalize(o, e, positions, n_consecutive, logger=logger):
    """Estimate the normalization of a given set of data.
    """
    data_o = [[]]*n_consecutive
    data_e = [[]]*n_consecutive

    # First, we separate the data in the positions, relative to consecutive
    for i, oi, ei in zip(positions, o, e):
        index = int(i/n_consecutive)
        data_o[index].append(oi)
        data_e[index].append(ei)

    # check if all positions have a value
    for i in data_o:
        if i == []:
            logger.warn('Could not calculate polarimetry normalization. '
                        'Not all needed positions are available. Using k=1.')
            return 1

    # Now we use as each consecutive value the mean of the values in each index
    for i in range(n_consecutive):
        data_o[i] = np.nanmean(data_o[i])
        data_e[i] = np.nanmean(data_e[i])

    # Now, assuming the k will multiply e
    k = np.sum(data_o)/np.sum(data_e)
    return k


def _polarimetry_sls(z, psi, retarder='half', z_err=None, logger=logger):
    """Calculate the polarimetry directly using z.
    psi in degrees
    """
    result = {}
    if z_err is None:
        result['z'] = {'value': z,
                       'sigma': np.array([np.nan]*len(z))}
    else:
        result['z'] = {'value': z, 'sigma': z_err}

    if retarder == 'half':
        model = HalfWaveModel()
    elif retarder == 'quarter':
        model = QuarterWaveModel()
    else:
        raise ValueError(f'retarder {retarder} not supported.')

    psi = np.radians(psi)

    fitter = LevMarLSQFitter()
    if z_err is None:
        m_fitted = fitter(model, psi, z)
    else:
        m_fitted = fitter(model, psi, z, weights=1/z_err)
    info = fitter.fit_info
    # The errors of parameters are assumed to be the sqrt of the diagonal of
    # the covariance matrix
    for i, j, k in zip(m_fitted.param_names, m_fitted.parameters,
                       np.sqrt(np.diag(info['param_cov']))):
        result[i] = {'value': j, 'sigma': k}

    if z_err is not None:
        result['sigma_theor'] = np.sqrt(np.sum(np.square(z_err))/len(z))
    else:
        result['sigma_theor'] = np.nan

    q, u = result['q']['value'], result['u']['value']
    q_err, u_err = result['q']['sigma'], result['u']['sigma']

    p = np.sqrt(q**2 + u**2)
    p_err = np.sqrt(((q/p)**2)*(q_err**2) + ((u/p)**2)*(u_err**2))
    result['p'] = {'value': p, 'sigma': p_err}

    theta = compute_theta(q, u)
    result['theta'] = {'value': theta, 'sigma': 28.65*p_err/p}

    return result


def _polarimetry_mbr84(z, psi, retarder='half', z_err=None,
                       logger=logger):
    """Implement the polarimetry calculation method described by
    Magalhaes et al 1984 (ads string: 1984PASP...96..383M)
    """
    result = {}
    psi = np.radians(psi)

    if retarder == 'half':
        if len(z) != len(psi):
            raise ValueError('z and psi have different lengths.')
        n = len(z)
        q = (2.0/n) * np.nansum(z*np.cos(4*psi))
        u = (2.0/n) * np.nansum(z*np.sin(4*psi))
        p = np.sqrt(q**2 + u**2)

        a = 2.0/n
        b = np.sqrt(1.0/(n-2))
        err = a*np.nansum(z**2)
        err = err - p**2
        err = b*np.sqrt(err)

        result['p'] = {'value': p, 'sigma': err}
        result['q'] = {'value': q, 'sigma': err}
        result['u'] = {'value': u, 'sigma': err}

        theta = compute_theta(q, u)
        result['theta'] = {'value': theta, 'sigma': 28.65*err/p}
    else:
        raise ValueError(f'Retarder {retarder} not supported')

    return result


def reduced_chi2(psi, z, z_err, q, u, v=None, retarder='half', logger=logger):
    """Compute the reduced chi-square for a given model."""
    if retarder == 'quarter' and v is None:
        raise ValueError('missing value `v` of circular polarimetry.')

    if retarder == 'half':
        model = HalfWaveModel(q=q, u=u)
        npar = 2
    elif retarder == 'quarter':
        model = QuarterWaveModel(q=q, u=u, v=v)
        npar = 3

    z_m = model(psi)
    nu = len(z_m) - npar

    return np.sum(np.square((z-z_m)/z_err))/nu


def dualbeam_polarimetry(o, e, psi, retarder='half', o_err=None, e_err=None,
                         normalize=True, positions=None, min_snr=None,
                         filter_negative=True, mode='sum', global_k=None,
                         logger=logger):
    """Calculate the polarimetry."""

    if retarder in _retarders.keys():
        ncons = _retarders[retarder]['ncons']
    else:
        raise ValueError(f'retarder {retarder} not supported.')

    o = np.array(o)
    e = np.array(e)

    # clean problematic sources (bad sky subtraction, low snr)
    if filter_negative:
        filt = (o < 0) | (e < 0)
        w = np.where(~filt)
        o[w] = np.nan
        e[w] = np.nan

    if normalize and positions is not None:
        if global_k is not None:
            k = global_k
        else:
            k = estimate_normalize(o, e, positions, ncons)
        z = (o-(e*k))/(o+(e*k))
    else:
        z = (o-e)/(o+e)

    if o_err is None or e_err is None:
        z_erro = None
    else:
        # Assuming individual z errors from propagation
        o_err = np.array(o_err)
        e_err = np.array(e_err)
        oi = 2*o/((o+e)**2)
        ei = -2*e/((o+e)**2)
        z_erro = np.sqrt((oi**2)*(o_err**2) + ((ei**2)*(e_err**2)))

    flux = np.sum(o)+np.sum(e)
    flux_err = np.sqrt(np.sum(o_err)**2 + np.sum(e_err)**2)

    def _return_empty():
        if retarder == 'half':
            keys = ['q', 'u']
        elif retarder == 'quarter':
            keys = ['q', 'u', 'v']
        dic = {}
        for i in keys + ['p', 'theta']:
            dic[i] = {'value': np.nan, 'sigma': np.nan}
        dic['z'] = {'value': z, 'sigma': z_erro}
        dic['sigma_theor'] = np.nan
        dic['flux'] = {'value': flux,
                       'sigma': flux_err}

        return dic

    if min_snr is not None and o_err is not None and e_err is not None:
        snr = flux/flux_err
        if snr < min_snr:
            logger.debug(f'Star with SNR={snr} eliminated.')
            return _return_empty()

    try:
        if mode == 'sum':
            result = _polarimetry_mbr84(z, psi, retarder=retarder,
                                        z_err=z_erro)
        elif mode == 'fit':
            result = _polarimetry_sls(z, psi, retarder=retarder,
                                      z_err=z_erro)
        elif mode == 'both':
            res_sum = _polarimetry_mbr84(z, psi, retarder=retarder,
                                         z_err=z_erro)
            res_fit = _polarimetry_sls(z, psi, retarder=retarder,
                                       z_err=z_erro)
            result = {}
            for key in res_sum.keys():
                result[f"sls_{key}"] = res_fit[key]
                result[f"mbr84_{key}"] = res_sum[key]
                result[key] = res_fit[key]
        else:
            return _return_empty()
    except Exception:
        return _return_empty()

    result['flux'] = {'value': flux,
                      'sigma': flux_err}
    result['z'] = {'value': z, 'sigma': z_erro}
    result['k'] = k or 1.0
    v = result.get('v', {'value': None})
    result['reduced_chi2'] = reduced_chi2(psi, z, z_erro,
                                          result['q']['value'],
                                          result['u']['value'],
                                          v=v['value'],
                                          retarder=retarder)
    return result
