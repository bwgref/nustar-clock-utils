import numpy as np
from astropy import log
from astropy.table import Table
from astroquery.heasarc import Heasarc
from scipy.interpolate import LSQUnivariateSpline


NUSTAR_MJDREF = np.longdouble("55197.00076601852")


def fix_byteorder(table):
    import sys

    sys_byteorder = ('>', '<')[sys.byteorder == 'little']
    for col in table.colnames:
        if table[col].dtype.byteorder not in ('=', sys_byteorder):
            table[col] = table[col].byteswap().newbyteorder(sys_byteorder)
    return table


def sec_to_mjd(time, mjdref=NUSTAR_MJDREF, dtype=np.double):
    return np.array(np.asarray(time) / 86400 + mjdref, dtype=dtype)


def splitext_improved(path):
    """
    Examples
    --------
    >>> np.all(splitext_improved("a.tar.gz") ==  ('a', '.tar.gz'))
    True
    >>> np.all(splitext_improved("a.tar") ==  ('a', '.tar'))
    True
    >>> np.all(splitext_improved("a.f/a.tar") ==  ('a.f/a', '.tar'))
    True
    >>> np.all(splitext_improved("a.a.a.f/a.tar.gz") ==  ('a.a.a.f/a', '.tar.gz'))
    True
    """
    import os
    dir, file = os.path.split(path)

    if len(file.split('.')) > 2:
        froot, ext = file.split('.')[0],'.' + '.'.join(file.split('.')[-2:])
    else:
        froot, ext = os.path.splitext(file)

    return os.path.join(dir, froot), ext


def get_wcs_from_col(hdu, col):
    from astropy.io.fits.column import KEYWORD_TO_ATTRIBUTE

    column = hdu.data.columns[col]
    res = type('wcsinfo', (), {})()
    res.form = getattr(column, KEYWORD_TO_ATTRIBUTE["TFORM"])
    res.crval = getattr(column, KEYWORD_TO_ATTRIBUTE["TCRVL"])
    res.crpix = getattr(column, KEYWORD_TO_ATTRIBUTE["TCRPX"])
    res.cdelt = getattr(column, KEYWORD_TO_ATTRIBUTE["TCDLT"])
    res.ctype = getattr(column, KEYWORD_TO_ATTRIBUTE["TCTYP"])
    res.cunit = getattr(column, KEYWORD_TO_ATTRIBUTE["TCUNI"])
    return res


def get_wcs_from_bintable(hdu, xcol, ycol):
    """Get WCS information from the columns (e.g. X and Y)."""
    from astropy import wcs
    xwcs = get_wcs_from_col(hdu, xcol)
    ywcs = get_wcs_from_col(hdu, ycol)

    w = wcs.WCS(naxis=2)

    w.wcs.crpix = [xwcs.crpix, ywcs.crpix]
    w.wcs.cdelt = np.array([xwcs.cdelt, ywcs.cdelt])
    w.wcs.crval = [xwcs.crval, ywcs.crval]
    w.wcs.ctype = [xwcs.ctype, ywcs.ctype]

    return w


def filter_with_region(evfile, regionfile, debug_plot=True,
                       outfile=None):
    """Filter event file by specifying a fk5 region."""
    from regions import read_ds9
    from astropy.io import fits
    import astropy.units as u
    from astropy.coordinates import SkyCoord

    label = regionfile.replace('.reg', '')
    root, ext = splitext_improved(evfile)
    if outfile is None:
        outfile = root + f'_{label}' + ext

    if outfile == evfile:
        raise ValueError("Invalid output file")

    log.info(f"Opening file {evfile}")
    with fits.open(evfile) as hdul:
        wcs = get_wcs_from_bintable(hdul['EVENTS'], 'X', 'Y')
        data = hdul['EVENTS'].data
        coords = SkyCoord.from_pixel(data['X'], data['Y'], wcs, mode='wcs')

        log.info(f"Reading region {regionfile}")
        region = read_ds9(regionfile)
        mask = region[0].contains(coords, wcs)
        masked = coords[mask]
        coordsx, coordsy = coords.to_pixel(wcs)
        x, y = masked.to_pixel(wcs)
        hdul['EVENTS'].data = data[mask]
        hdul.writeto(outfile, overwrite=True)
        log.info(f"Saving to file {outfile}")

    if debug_plot:
        import matplotlib.pyplot as plt
        center = region[0].center

        ddec = 0.1
        dra = 0.1 / np.cos(center.dec)
        figurename = f"{root}.png"
        log.info(f"Plotting data in {figurename}")
        fig = plt.figure(figurename, figsize=(10, 10))
        plt.style.use('dark_background')
        noise_ra = np.random.normal(coords.ra.value, 1/60/60) * u.deg
        noise_dec = np.random.normal(coords.dec.value, 1/60/60) * u.deg
        log.info(f"Randomizing scatter points by 1'' for beauty")
        plt.subplot(projection=wcs)
        plt.scatter(noise_ra, noise_dec, s=1, alpha=0.05)
        noise_ra = np.random.normal(masked.ra.value, 1/60/60) * u.deg
        noise_dec = np.random.normal(masked.dec.value, 1/60/60) * u.deg
        plt.scatter(noise_ra, noise_dec, s=1, alpha=0.05)
        plt.xlim([(center.ra - dra * u.deg).value, (center.ra + dra * u.deg).value])
        plt.ylim([(center.dec - ddec * u.deg).value, (center.dec + ddec * u.deg).value])
        plt.xlabel("RA")
        plt.ylabel("Dec")
        plt.grid()
        plt.savefig(figurename)
        plt.close(fig)


def get_obsid_list_from_heasarc(cache_file='heasarc.hdf5'):
    try:
        heasarc = Heasarc()
        all_nustar_obs = heasarc.query_object(
            '*', 'numaster', resultmax=10000,
            fields='OBSID,TIME,END_TIME,NAME,OBSERVATION_MODE,OBS_TYPE')
    except Exception:
        return Table({
            'TIME': [0], 'TIME_END': [0], 'MET': [0], 'NAME': [""],
            'OBSERVATION_MODE': [""], 'OBS_TYPE': [""], 'OBSID': [""]})

    all_nustar_obs = all_nustar_obs[all_nustar_obs["TIME"] > 0]
    for field in 'OBSID,NAME,OBSERVATION_MODE,OBS_TYPE'.split(','):
        all_nustar_obs[field] = [om.strip() for om in all_nustar_obs[field]]

    # all_nustar_obs = all_nustar_obs[all_nustar_obs["OBSERVATION_MODE"] == 'SCIENCE']
    all_nustar_obs['MET'] = np.array(all_nustar_obs['TIME'] - NUSTAR_MJDREF) * 86400

    return all_nustar_obs


def rolling_window(a, window):
    """Create a simple rolling window, for use with statistical functions.

    https://rigtorp.se/2011/01/01/rolling-statistics-numpy.html

    Examples
    --------
    >>> a = np.arange(5)
    >>> rw = rolling_window(a, 2)
    >>> np.allclose(rw, [[0, 1], [1,2], [2, 3], [3, 4]])
    True
    >>> rw = rolling_window(a, 3)
    >>> np.allclose(rw, [[0, 1, 2], [1, 2, 3], [2, 3, 4]])
    True
    """
    shape = a.shape[:-1] + (a.shape[-1] - window + 1, window)
    strides = a.strides + (a.strides[-1],)
    return np.lib.stride_tricks.as_strided(a, shape=shape, strides=strides)


def rolling_stat(stat_fun, a, window, pad='center', **kwargs):
    """
    Examples
    --------
    >>> a = np.arange(6)
    >>> r_sum = rolling_stat(np.sum, a, 3, pad='center', axis=-1)
    >>> np.allclose(r_sum, [3.,  3.,  6.,  9., 12., 12.])
    True
    >>> r_sum = rolling_stat(np.sum, a, 3, pad='left', axis=-1)
    >>> np.allclose(r_sum, [3.,  3.,  3.,  6.,  9., 12.])
    True
    >>> r_sum = rolling_stat(np.sum, a, 3, pad='right', axis=-1)
    >>> np.allclose(r_sum, [3.,  6.,  9., 12., 12., 12.])
    True
    >>> r_sum = rolling_stat(np.sum, a, 3, pad='incredible', axis=-1)
    Traceback (most recent call last):
       ...
    ValueError: `pad` can only be 'center', 'left' or 'right', got 'incredible'

    """
    a = np.asarray(a)
    rstat = stat_fun(rolling_window(a, window), **kwargs)
    a_len = a.shape[0]
    w_len = rstat.shape[0]

    total_pad = a_len - w_len
    if pad == 'center':
        l_pad = total_pad // 2
        r_pad = total_pad - l_pad
    elif pad == 'left':
        l_pad = total_pad
        r_pad = 0
    elif pad == 'right':
        r_pad = total_pad
        l_pad = 0
    else:
        raise ValueError(f"`pad` can only be 'center', 'left' or 'right', "
                         f"got '{pad}'")

    r_pad_arr = l_pad_arr = []
    if r_pad > 0:
        r_pad_arr = np.zeros(r_pad) + rstat[-1]
    if l_pad > 0:
        l_pad_arr = np.zeros(l_pad) + rstat[0]
    return np.concatenate((l_pad_arr, rstat, r_pad_arr))


def rolling_std(a, window, pad='center'):
    """Rolling standard deviation.

    Examples
    >>> a = [0, 1, 1, 3]
    >>> np.allclose(rolling_std(a, 2), [0.5, 0, 1, 1])
    True
    """
    return rolling_stat(np.std, a, window, pad, axis=-1)


def spline_through_data(x, y, k=2, grace_intv=1000., smoothing_factor=0.0001):
    """Pass a spline through the data

    Examples
    --------
    >>> x = np.arange(1000)
    >>> y = np.random.normal(x * 0.1, 0.01)
    >>> fun = spline_through_data(x, y, grace_intv=10.)
    >>> np.std(y - fun(x)) < 0.01
    True
    """
    lo_lim, hi_lim = x[0], x[-1]

    control_points = \
        np.linspace(lo_lim + 2 * grace_intv, hi_lim - 2 * grace_intv,
                    x.size // 5)

    detrend_fun = LSQUnivariateSpline(
        x, y, t=control_points, k=k,
        bbox=[lo_lim - grace_intv, hi_lim + grace_intv])

    detrend_fun.set_smoothing_factor(smoothing_factor)

    return detrend_fun


def aggregate(table, max_number=1000):
    """
    Examples
    --------
    >>> table = Table({'a': [1, 2], 'b': [5, 6]})
    >>> newt = aggregate(table)
    >>> len(newt)
    2
    >>> np.all(newt['a'] == table['a'])
    True
    >>> np.all(newt['b'] == table['b'])
    True
    >>> newt = aggregate(table, max_number=1)
    >>> len(newt)
    1
    >>> np.all(newt['a'] == 1.5)
    True
    >>> newt = aggregate(table.to_pandas(), max_number=1)
    >>> np.all(newt['b'] == 5.5)
    True
    """
    N = len(table)
    if N < max_number:
        return table
    rebin_factor = int(np.ceil(len(table) / max_number))
    table['__binning__'] = np.arange(N) // rebin_factor

    if isinstance(table, Table):
        binned = table.group_by('__binning__').groups.aggregate(np.mean)
        return binned

    return table.groupby('__binning__').mean()


def aggregate_all_tables(table_list, max_number=1000):
    """
    Examples
    --------
    >>> table = Table({'a': [1, 2], 'b': [5, 6]})
    >>> newt = aggregate_all_tables([table])[0]
    >>> len(newt)
    2
    >>> np.all(newt['a'] == table['a'])
    True
    >>> np.all(newt['b'] == table['b'])
    True
    """
    return [aggregate(table) for table in table_list]


def cross_two_gtis(gti0, gti1):
    """Extract the common intervals from two GTI lists *EXACTLY*.

    Parameters
    ----------
    gti0 : iterable of the form ``[[gti0_0, gti0_1], [gti1_0, gti1_1], ...]``
    gti1 : iterable of the form ``[[gti0_0, gti0_1], [gti1_0, gti1_1], ...]``
        The two lists of GTIs to be crossed.

    Returns
    -------
    gtis : ``[[gti0_0, gti0_1], [gti1_0, gti1_1], ...]``
        The newly created GTIs

    See Also
    --------
    cross_gtis : From multiple GTI lists, extract common intervals *EXACTLY*

    Examples
    --------
    >>> gti1 = np.array([[1, 2]])
    >>> gti2 = np.array([[1, 2]])
    >>> newgti = cross_two_gtis(gti1, gti2)
    >>> np.all(newgti == [[1, 2]])
    True
    >>> gti1 = np.array([[1, 4]])
    >>> gti2 = np.array([[1, 2], [2, 4]])
    >>> newgti = cross_two_gtis(gti1, gti2)
    >>> np.all(newgti == [[1, 2], [2, 4]])
    True
    """
    import copy

    gti0 = copy.deepcopy(gti0)
    gti1 = copy.deepcopy(gti1)

    final_gti = []

    while len(gti0) > 0 and len(gti1) > 0:
        gti_start = np.max((gti0[0, 0], gti1[0, 0]))

        gti0 = gti0[gti0[:, 1] > gti_start]
        gti1 = gti1[gti1[:, 1] > gti_start]

        gti_end = np.min((gti0[0, 1], gti1[0, 1]))

        final_gti.append([gti_start, gti_end])

        gti0 = gti0[gti0[:, 1] > gti_end]
        gti1 = gti1[gti1[:, 1] > gti_end]

    return np.array(final_gti)
