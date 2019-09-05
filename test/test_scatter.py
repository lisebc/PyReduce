import pytest
import numpy as np

from pyreduce.estimate_background_scatter import estimate_background_scatter


def test_scatter(flat, orders, settings):
    img, _ = flat
    orders, column_range = orders
    settings = settings["scatter"]

    if img is None:
        pytest.skip("Need flat")

    scatter = estimate_background_scatter(
        img, orders, column_range=column_range, **settings
    )

    degree = settings["scatter_degree"]
    if np.isscalar(degree):
        degree = [degree, degree]

    assert isinstance(scatter, np.ndarray)
    assert scatter.ndim == 2
    assert scatter.shape[0] == degree[0] + 1
    assert scatter.shape[1] == degree[1] + 1


def test_simple():
    img = np.full((100, 100), 10.0)
    orders = np.array([[0, 25], [0, 50], [0, 75]])

    scatter = estimate_background_scatter(img, orders, scatter_degree=0, plot=False)

    assert isinstance(scatter, np.ndarray)
    assert scatter.ndim == 2
    assert scatter.shape[0] == 1
    assert scatter.shape[1] == 1

    assert np.allclose(scatter[0, 0], 10.0)


def test_scatter_degree():
    img = np.full((100, 100), 10.0)
    orders = np.full((2, 2), 1.0)

    estimate_background_scatter(img, orders, scatter_degree=0)

    with pytest.raises(ValueError):
        estimate_background_scatter(img, orders, scatter_degree=-1)

    estimate_background_scatter(img, orders, scatter_degree=(2, 2))

    with pytest.raises(AssertionError):
        estimate_background_scatter(img, orders, scatter_degree=(1,))

    with pytest.raises(AssertionError):
        estimate_background_scatter(img, orders, scatter_degree=(3, 2, 1))

    with pytest.raises(ValueError):
        estimate_background_scatter(img, orders, scatter_degree=(2, -1))
