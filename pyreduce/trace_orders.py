"""
Find clusters of pixels with signal
And combine them into continous orders
"""

import logging
from itertools import combinations
from functools import cmp_to_key

import matplotlib.pyplot as plt
import numpy as np
from numpy.polynomial.polynomial import Polynomial

from scipy.ndimage import morphology, label
from scipy.ndimage.filters import gaussian_filter1d, median_filter
from scipy.signal import peak_widths, find_peaks

from .util import polyfit1d


def fit(x, y, deg, regularization=0):
    # order = polyfit1d(y, x, deg, regularization)
    order = Polynomial.fit(y, x, deg=deg, domain=[]).coef[::-1]
    return order


def determine_overlap_rating(xi, yi, xj, yj, mean_cluster_thickness, nrow, ncol, deg=2):
    i_left, i_right = yi.min(), yi.max()
    j_left, j_right = yj.min(), yj.max()

    order_i = fit(xi, yi, deg)
    order_j = fit(xj, yj, deg)

    # Get polynomial points inside cluster limits for each
    y_ii = np.polyval(order_i, np.arange(i_left, i_right))
    y_ij = np.polyval(order_i, np.arange(j_left, j_right))
    y_jj = np.polyval(order_j, np.arange(j_left, j_right))
    y_ji = np.polyval(order_j, np.arange(i_left, i_right))

    # difference of polynomials within each cluster limit
    diff_i = np.abs(y_ii - y_ji)
    diff_j = np.abs(y_ij - y_jj)

    ind_i = np.where((diff_i < mean_cluster_thickness) & (y_ji >= 0) & (y_ji < nrow))
    ind_j = np.where((diff_j < mean_cluster_thickness) & (y_ij >= 0) & (y_ij < nrow))

    overlap = len(ind_i[0]) + len(ind_j[0])
    overlap = overlap / ((i_right - i_left) + (j_right - j_left))
    if i_right < j_left:
        overlap *= 1 - (i_right - j_left) / ncol
    elif j_right < i_left:
        overlap *= 1 - (j_right - i_left) / ncol

    overlap_region = [-1, -1]
    if len(ind_i[0]) > 0:
        overlap_region[0] = np.min(ind_i[0]) + i_left
    if len(ind_j[0]) > 0:
        overlap_region[1] = np.max(ind_j[0]) + j_left

    return overlap, overlap_region


def create_merge_array(x, y, mean_cluster_thickness, nrow, ncol, deg, threshold):
    n_clusters = list(x.keys())
    nmax = len(n_clusters) ** 2
    merge = np.zeros((nmax, 5))
    for k, (i, j) in enumerate(combinations(n_clusters, 2)):
        overlap, region = determine_overlap_rating(
            x[i], y[i], x[j], y[j], mean_cluster_thickness, nrow, ncol, deg=deg
        )
        merge[k] = [i, j, overlap, *region]
    merge = merge[merge[:, 2] > threshold]
    merge = merge[np.argsort(merge[:, 2])[::-1]]
    return merge


def update_merge_array(
    merge, x, y, j, mean_cluster_thickness, nrow, ncol, deg, threshold
):
    j = int(j)
    n_clusters = np.array(list(x.keys()))
    update = []
    for i in n_clusters[n_clusters != j]:
        overlap, region = determine_overlap_rating(
            x[i], y[i], x[j], y[j], mean_cluster_thickness, nrow, ncol, deg=deg
        )
        if overlap <= threshold:
            # no , or little overlap
            continue
        update += [[i, j, overlap, *region]]
    if len(update) == 0:
        return merge
    update = np.array(update)
    merge = np.concatenate((merge, update))
    merge = merge[np.argsort(merge[:, 2])[::-1]]
    return merge


def calculate_mean_cluster_thickness(x, y):
    # Calculate mean cluster thickness
    # TODO optimize
    n_clusters = list(x.keys())
    mean_cluster_thickness = 10
    for cluster in n_clusters:
        # individual columns of this cluster
        columns = np.unique(y[cluster])
        delta = 0
        for col in columns:
            # thickness of the cluster in each column
            tmp = x[cluster][y[cluster] == col]
            delta += np.max(tmp) - np.min(tmp)
        mean_cluster_thickness += delta / len(columns)

    mean_cluster_thickness *= 1.5 / len(n_clusters)
    return mean_cluster_thickness


def delete(i, x, y, merge):
    del x[i], y[i]
    merge = merge[(merge[:, 0] != i) & (merge[:, 1] != i)]
    return x, y, merge


def combine(i, j, x, y, merge, mct, nrow, ncol, deg, threshold):
    # Merge pixels
    y[j] = np.concatenate((y[j], y[i]))
    x[j] = np.concatenate((x[j], x[i]))
    # Delete obsolete data
    x, y, merge = delete(i, x, y, merge)
    merge = merge[(merge[:, 0] != j) & (merge[:, 1] != j)]
    # Update merge array
    merge = update_merge_array(merge, x, y, j, mct, nrow, ncol, deg, threshold)
    return x, y, merge


def merge_clusters(
    img,
    x,
    y,
    n_clusters,
    manual=True,
    deg=2,
    auto_merge_threshold=0.9,
    merge_min_threshold=0.1,
):
    """Merge clusters that belong together

    Parameters
    ----------
    img : array[nrow, ncol]
        the image the order trace is based on
    orders : dict(int, array(float))
        coefficients of polynomial fits to clusters
    x : dict(int, array(int))
        x coordinates of cluster points
    y : dict(int, array(int))
        y coordinates of cluster points
    n_clusters : array(int)
        cluster numbers
    threshold : int, optional
        overlap threshold for merging clusters (the default is 100)
    manual : bool, optional
        if True ask before merging orders

    Returns
    -------
    x : dict(int: array)
        x coordinates of clusters, key=cluster id
    y : dict(int: array)
        y coordinates of clusters, key=cluster id
    n_clusters : int
        number of identified clusters
    """

    nrow, ncol = img.shape
    mct = calculate_mean_cluster_thickness(x, y)

    merge = create_merge_array(x, y, mct, nrow, ncol, deg, merge_min_threshold)

    if manual:
        plt.ion()

    k = 0
    while k < len(merge):
        i, j, overlap, _, _ = merge[k]
        i, j = int(i), int(j)

        if overlap >= auto_merge_threshold:
            answer = "y"
        elif manual:
            plot_order(i, j, x, y, img, deg, title=f"Probability: {overlap}")
            while True:
                if manual:
                    answer = input("Merge? [y/n]")
                if answer in "ynrg":
                    break
        else:
            answer = "y"

        if answer == "y":
            # just merge automatically
            logging.info("Merging orders %i and %i", i, j)
            x, y, merge = combine(
                i, j, x, y, merge, mct, nrow, ncol, deg, merge_min_threshold
            )
        elif answer == "n":
            k += 1
        elif answer == "r":
            x, y, merge = delete(i, x, y, merge)
        elif answer == "g":
            x, y, merge = delete(j, x, y, merge)

    if manual:
        plt.close()
        plt.ioff()

    n_clusters = list(x.keys())
    return x, y, n_clusters


def fit_polynomials_to_clusters(x, y, clusters, degree, regularization=0):
    """Fits a polynomial of degree opower to points x, y in cluster clusters

    Parameters
    ----------
    x : dict(int: array)
        x coordinates seperated by cluster
    y : dict(int: array)
        y coordinates seperated by cluster
    clusters : list(int)
        cluster labels, equivalent to x.keys() or y.keys()
    degree : int
        degree of polynomial fit
    Returns
    -------
    orders : dict(int, array[degree+1])
        coefficients of polynomial fit for each cluster
    """

    orders = {c: fit(x[c], y[c], degree, regularization) for c in clusters}
    return orders


def plot_orders(im, x, y, clusters, orders, order_range):
    """ Plot orders and image """

    cluster_img = np.zeros(im.shape, dtype=im.dtype)
    for c in clusters:
        cluster_img[x[c], y[c]] = c
    cluster_img = np.ma.masked_array(cluster_img, mask=cluster_img == 0)

    plt.subplot(121)
    bot, top = np.percentile(im, (1, 99))
    plt.imshow(im, origin="lower", vmin=bot, vmax=top)
    plt.title("Input Image + Order polynomials")
    plt.xlabel("x [pixel]")
    plt.ylabel("y [pixel]")
    plt.ylim([0, im.shape[0]])

    if orders is not None:
        for i, order in enumerate(orders):
            x = np.arange(*order_range[i], 1)
            y = np.polyval(order, x)
            plt.plot(x, y)

    plt.subplot(122)
    plt.imshow(cluster_img, cmap=plt.get_cmap("tab20"), origin="upper")
    plt.title("Detected Clusters + Order Polynomials")
    plt.xlabel("x [pixel]")
    plt.ylabel("y [pixel]")

    if orders is not None:
        for i, order in enumerate(orders):
            x = np.arange(*order_range[i], 1)
            y = np.polyval(order, x)
            plt.plot(x, y)

    plt.ylim([0, im.shape[0]])
    plt.show()


def plot_order(i, j, x, y, img, deg, title=""):
    """ Plot a single order """
    _, ncol = img.shape

    order_i = fit(x[i], y[i], deg)
    order_j = fit(x[j], y[j], deg)

    xp = np.arange(ncol)
    yi = np.polyval(order_i, xp)
    yj = np.polyval(order_j, xp)

    plt.clf()
    plt.title(title)
    plt.imshow(img)
    plt.plot(xp, yi, "r")
    plt.plot(xp, yj, "g")
    plt.plot(y[i], x[i], "r.")
    plt.plot(y[j], x[j], "g.")

    xmin = min(np.min(x[i]), np.min(x[j])) - 50
    xmax = max(np.max(x[i]), np.max(x[j])) + 50

    ymin = min(np.min(y[i]), np.min(y[j])) - 50
    ymax = max(np.max(y[i]), np.max(y[j])) + 50

    plt.xlim([ymin, ymax])
    plt.ylim([xmin, xmax])

    plt.show()


def mark_orders(
    im,
    min_cluster=500,
    filter_size=120,
    noise=8,
    opower=4,
    border_width=5,
    degree_before_merge=2,
    regularization=0,
    closing_shape=(5, 5),
    opening_shape=(2, 2),
    plot=False,
    manual=True,
    auto_merge_threshold=0.9,
    merge_min_threshold=0.1,
    sigma=2,
):
    """ Identify and trace orders

    Parameters
    ----------
    im : array[nrow, ncol]
        order definition image
    min_cluster : int, optional
        minimum cluster size in pixels (default: 500)
    filter_size : int, optional
        size of the running filter (default: 120)
    noise : float, optional
        noise to filter out (default: 8)
    opower : int, optional
        polynomial degree of the order fit (default: 4)
    border_width : int, optional
        number of pixels at the bottom and top borders of the image to ignore for order tracing (default: 5)
    plot : bool, optional
        wether to plot the final order fits (default: False)
    manual : bool, optional
        wether to manually select clusters to merge (strongly recommended) (default: True)

    Returns
    -------
    orders : array[nord, opower+1]
        order tracing coefficients (in numpy order, i.e. largest exponent first)
    """

    # Convert to signed integer, to avoid underflow problems
    im = np.asarray(im)
    im = im.astype(int)

    if filter_size is None:
        col = im[:, im.shape[0] // 2]
        col = median_filter(col, 5)
        threshold = np.percentile(col, 90)
        npeaks = find_peaks(col, height=threshold)[0].size
        filter_size = im.shape[0] // npeaks
        logging.info("Median filter size, estimated: %i", filter_size)
    elif filter_size <= 0:
        raise ValueError(f"Expected filter size > 0, but got {filter_size}")

    if border_width is None:
        # find width of orders, based on central column
        col = im[:, im.shape[0] // 2]
        col = median_filter(col, 5)
        idx = np.argmax(col)
        width = peak_widths(col, [idx])[0][0]
        border_width = int(np.ceil(width))
        logging.info("Image border width, estimated: %i", border_width)
    elif border_width < 0:
        raise ValueError(f"Expected border width > 0, but got {border_width}")

    if min_cluster is None:
        min_cluster = im.shape[1] // 4
        logging.info("Minimum cluster size, estimated: %i", min_cluster)
    elif not np.isscalar(min_cluster):
        raise TypeError(f"Expected scalar minimum cluster size, but got {min_cluster}")

    # blur image along columns, and use the median + blurred + noise as threshold
    blurred = gaussian_filter1d(im, filter_size, axis=0)

    if noise is None:
        tmp = np.abs(blurred.flatten())
        noise = np.percentile(tmp, 5)
        logging.info("Background noise, estimated: %f", noise)
    elif not np.isscalar(noise):
        raise TypeError(f"Expected scalar noise level, but got {noise}")

    threshold = np.ma.median(blurred - im, axis=0)
    mask = im > blurred + noise + np.abs(threshold)
    # remove borders
    if border_width != 0:
        mask[:border_width, :] = mask[-border_width:, :] = False
    # remove masked areas with no clusters
    mask = np.ma.filled(mask, fill_value=False)
    # close gaps inbetween clusters
    struct = np.full(closing_shape, 1)
    mask = morphology.binary_closing(mask, struct, border_value=1)
    # remove small lonely clusters
    struct = np.full(opening_shape, 1)
    # struct = morphology.generate_binary_structure(2, 1)
    mask = morphology.binary_opening(mask, struct)

    # label clusters
    clusters, _ = label(mask)

    # remove small clusters
    sizes = np.bincount(clusters.ravel())
    mask_sizes = sizes > min_cluster
    mask_sizes[0] = True  # This is the background, which we don't need to remove
    for i in np.arange(len(sizes))[~mask_sizes]:
        clusters[clusters == i] = 0

    # # Reorganize x, y, clusters into a more convenient "pythonic" format
    # # x, y become dictionaries, with an entry for each order
    # # n is just a list of all orders (ignore cluster == 0)
    n = np.unique(clusters)
    n = n[n != 0]
    x = {i: np.where(clusters == c)[0] for i, c in enumerate(n)}
    y = {i: np.where(clusters == c)[1] for i, c in enumerate(n)}

    def best_fit_degree(x, y):
        L1 = np.sum((np.polyval(np.polyfit(y, x, 1), y) - x) ** 2)
        L2 = np.sum((np.polyval(np.polyfit(y, x, 2), y) - x) ** 2)

        # aic1 = 2 + 2 * np.log(L1) + 4 / (x.size - 2)
        # aic2 = 4 + 2 * np.log(L2) + 12 / (x.size - 3)

        if L1 < L2:
            return 1
        else:
            return 2

    if sigma > 0:
        degree = {i: best_fit_degree(x[i], y[i]) for i in x.keys()}
        bias = {i: np.polyfit(y[i], x[i], deg=degree[i])[-1] for i in x.keys()}
        n = list(x.keys())
        yt = np.concatenate([y[i] for i in n])
        xt = np.concatenate([x[i] - bias[i] for i in n])
        coef = np.polyfit(yt, xt, deg=degree_before_merge)

        res = np.polyval(coef, yt)
        cutoff = sigma * (res - xt).std()

        # DEBUG plot
        # uy = np.unique(yt)
        # mask = np.abs(res - xt) > cutoff
        # plt.plot(yt, xt, ".")
        # plt.plot(yt[mask], xt[mask], "r.")
        # plt.plot(uy, np.polyval(coef, uy))
        # plt.show()
        #

        m = {
            i: np.abs(np.polyval(coef, y[i]) - (x[i] - bias[i])) < cutoff for i in x.keys()
        }

        k = max(x.keys()) + 1
        for i in range(1, k):
            new_img = np.zeros(im.shape, dtype=int)
            new_img[x[i][~m[i]], y[i][~m[i]]] = 1
            clusters, _ = label(new_img)

            x[i] = x[i][m[i]]
            y[i] = y[i][m[i]]
            if len(x[i]) == 0:
                del x[i], y[i]

            nnew = np.max(clusters)
            if nnew != 0:
                xidx, yidx = np.indices(im.shape)
                for j in range(1, nnew + 1):
                    xn = xidx[clusters == j]
                    yn = yidx[clusters == j]
                    if xn.size >= min_cluster:
                        x[k] = xn
                        y[k] = yn
                        k += 1
                # plt.imshow(clusters, origin="lower")
                # plt.show()

    if plot:
        plt.title("Identified clusters")
        plt.xlabel("x [pixel]")
        plt.ylabel("y [pixel]")
        clusters = np.ma.zeros(im.shape, dtype=int)
        for i in x.keys():
            clusters[x[i], y[i]] = i
        clusters[clusters == 0] = np.ma.masked

        plt.imshow(clusters, origin="lower", cmap="prism")
        plt.show()

    # Merge clusters, if there are even any possible mergers left
    x, y, n = merge_clusters(
        im,
        x,
        y,
        n,
        manual=manual,
        deg=degree_before_merge,
        auto_merge_threshold=auto_merge_threshold,
        merge_min_threshold=merge_min_threshold,
    )

    orders = fit_polynomials_to_clusters(x, y, n, opower)

    # sort orders from bottom to top, using relative position

    def compare(i, j):
        _, xi, i_left, i_right = i
        _, xj, j_left, j_right = j

        if i_right < j_left or j_right < i_left:
            return xi.mean() - xj.mean()

        left = max(i_left, j_left)
        right = min(i_right, j_right)

        return xi[left:right].mean() - xj[left:right].mean()

    xp = np.arange(im.shape[1])
    keys = [(c, np.polyval(orders[c], xp), y[c].min(), y[c].max()) for c in x.keys()]
    keys = sorted(keys, key=cmp_to_key(compare))
    key = [k[0] for k in keys]

    n = np.arange(len(n), dtype=int)
    x = {c: x[key[c]] for c in n}
    y = {c: y[key[c]] for c in n}
    orders = np.array([orders[key[c]] for c in n])

    column_range = np.array([[np.min(y[i]), np.max(y[i]) + 1] for i in n])

    if plot:
        plot_orders(im, x, y, n, orders, column_range)

    return orders, column_range
