from __future__ import absolute_import, division, print_function

import datetime

import numpy as np
from pandas import DataFrame, Series
from datashape import to_numpy

from ..expr import Reduction, Field, Projection, Broadcast, Selection, ndim
from ..expr import Distinct, Sort, Head, Label, ReLabel, Expr, Slice
from ..expr import std, var, count, nunique, Summary
from ..expr import BinOp, UnaryOp, USub, Not, nelements
from ..expr import UTCFromTimestamp, DateTimeTruncate
from ..expr import Transpose, TensorDot

from .core import base, compute
from ..dispatch import dispatch
from into import into
import pandas as pd

__all__ = ['np']


@dispatch(Field, np.ndarray)
def compute_up(c, x, **kwargs):
    if x.dtype.names and c._name in x.dtype.names:
        return x[c._name]
    if not x.dtype.names and x.shape[1] == len(c._child.fields):
        return x[:, c._child.fields.index(c._name)]
    raise NotImplementedError() # pragma: no cover


@dispatch(Projection, np.ndarray)
def compute_up(t, x, **kwargs):
    if x.dtype.names and all(col in x.dtype.names for col in t.fields):
        return x[t.fields]
    if not x.dtype.names and x.shape[1] == len(t._child.fields):
        return x[:, [t._child.fields.index(col) for col in t.fields]]
    raise NotImplementedError() # pragma: no cover


@dispatch(Broadcast, np.ndarray)
def compute_up(t, x, **kwargs):
    d = dict((t._child[c]._expr, x[c]) for c in t._child.fields)
    return compute(t._expr, d)


@dispatch(BinOp, np.ndarray, (np.ndarray, base))
def compute_up(t, lhs, rhs, **kwargs):
    return t.op(lhs, rhs)


@dispatch(BinOp, np.ndarray)
def compute_up(t, data, **kwargs):
    if isinstance(t.lhs, Expr):
        return t.op(data, t.rhs)
    else:
        return t.op(t.lhs, data)


@dispatch(BinOp, base, np.ndarray)
def compute_up(t, lhs, rhs, **kwargs):
    return t.op(lhs, rhs)


@dispatch(UnaryOp, np.ndarray)
def compute_up(t, x, **kwargs):
    return getattr(np, t.symbol)(x)


@dispatch(Not, np.ndarray)
def compute_up(t, x, **kwargs):
    return ~x


@dispatch(USub, np.ndarray)
def compute_up(t, x, **kwargs):
    return -x


@dispatch(count, np.ndarray)
def compute_up(t, x, **kwargs):
    if np.issubdtype(x.dtype, np.float): # scalar dtype
        return pd.notnull(x).sum(keepdims=t.keepdims, axis=t.axis)
    else:
        return np.ones(x.shape).sum(keepdims=t.keepdims, axis=t.axis)


@dispatch(nunique, np.ndarray)
def compute_up(t, x, **kwargs):
    assert t.axis == tuple(range(ndim(t._child)))
    result = len(np.unique(x))
    if t.keepdims:
        result = np.array([result])
    return result


@dispatch(Reduction, np.ndarray)
def compute_up(t, x, **kwargs):
    return getattr(x, t.symbol)(axis=t.axis, keepdims=t.keepdims)


def axify(expr, axis, keepdims=False):
    """ inject axis argument into expression

    Helper function for compute_up(Summary, np.ndarray)

    >>> from blaze import symbol
    >>> s = symbol('s', '10 * 10 * int')
    >>> expr = s.sum()
    >>> axify(expr, axis=0)
    sum(s, axis=(0,))
    """
    return type(expr)(expr._child, axis=axis, keepdims=keepdims)

@dispatch(Summary, np.ndarray)
def compute_up(expr, data, **kwargs):
    shape, dtype = to_numpy(expr.dshape)
    if shape:
        result = np.empty(shape=shape, dtype=dtype)
        for n, v in zip(expr.names, expr.values):
            result[n] = compute(axify(v, expr.axis, expr.keepdims), data)
        return result
    else:
        return tuple(compute(axify(v, expr.axis), data) for v in expr.values)


@dispatch((std, var), np.ndarray)
def compute_up(t, x, **kwargs):
    return getattr(x, t.symbol)(ddof=t.unbiased)


@dispatch(Distinct, np.ndarray)
def compute_up(t, x, **kwargs):
    return np.unique(x)


@dispatch(Sort, np.ndarray)
def compute_up(t, x, **kwargs):
    if (t.key in x.dtype.names or
        isinstance(t.key, list) and all(k in x.dtype.names for k in t.key)):
        result = np.sort(x, order=t.key)
    elif t.key:
        raise NotImplementedError("Sort key %s not supported" % str(t.key))
    else:
        result = np.sort(x)

    if not t.ascending:
        result = result[::-1]

    return result


@dispatch(Head, np.ndarray)
def compute_up(t, x, **kwargs):
    return x[:t.n]

@dispatch(Label, np.ndarray)
def compute_up(t, x, **kwargs):
    return np.array(x, dtype=[(t.label, x.dtype.type)])


@dispatch(ReLabel, np.ndarray)
def compute_up(t, x, **kwargs):
    types = [x.dtype[i] for i in range(len(x.dtype))]
    return np.array(x, dtype=list(zip(t.fields, types)))


@dispatch(Selection, np.ndarray)
def compute_up(sel, x, **kwargs):
    return x[compute(sel.predicate, {sel._child: x})]

@dispatch(UTCFromTimestamp, np.ndarray)
def compute_up(expr, data, **kwargs):
    return (data * 1e6).astype('M8[us]')

@dispatch(Slice, np.ndarray)
def compute_up(expr, x, **kwargs):
    return x[expr.index]


@dispatch(Expr, np.ndarray)
def compute_up(t, x, **kwargs):
    ds = t._child.dshape
    if x.ndim > 1 or isinstance(x, np.recarray) or x.dtype.fields is not None:
        return compute_up(t, into(DataFrame, x, dshape=ds), **kwargs)
    else:
        return compute_up(t, into(Series, x, dshape=ds), **kwargs)


@dispatch(nelements, np.ndarray)
def compute_up(expr, data, **kwargs):
    axis = expr.axis
    if expr.keepdims:
        shape = tuple(data.shape[i] if i not in axis else 1
                                    for i in range(ndim(expr._child)))
    else:
        shape = tuple(data.shape[i] for i in range(ndim(expr._child))
                      if i not in axis)
    value = np.prod([data.shape[i] for i in axis])
    result = np.empty(shape)
    result.fill(value)
    result = result.astype('int64')

    return result



# Note the use of 'week': 'M8[D]' here.

# We truncate week offsets "manually" in the compute_up implementation by first
# converting to days then multiplying our measure by 7 this simplifies our code
# by only requiring us to calculate the week offset relative to the day of week.

precision_map = {'year': 'M8[Y]',
                 'month': 'M8[M]',
                 'week': 'M8[D]',
                 'day': 'M8[D]',
                 'hour': 'M8[h]',
                 'minute': 'M8[m]',
                 'second': 'M8[s]',
                 'millisecond': 'M8[ms]',
                 'microsecond': 'M8[us]',
                 'nanosecond': 'M8[ns]'}


# these offsets are integers in units of their representation

epoch = datetime.datetime(1970, 1, 1)
offsets = {
    'week': epoch.isoweekday(),
    'day': epoch.toordinal() # number of days since *Python's* epoch (01/01/01)
}


@dispatch(DateTimeTruncate, (np.ndarray, np.datetime64))
def compute_up(expr, data, **kwargs):
    np_dtype = precision_map[expr.unit]
    offset = offsets.get(expr.unit, 0)
    measure = expr.measure * 7 if expr.unit == 'week' else expr.measure
    result = (((data.astype(np_dtype)
                    .view('int64')
                    + offset)
                    // measure
                    * measure
                    - offset)
                    .astype(np_dtype))
    return result


@dispatch(np.ndarray)
def chunks(x, chunksize=1024):
    start = 0
    n = len(x)
    while start < n:
        yield x[start:start + chunksize]
        start += chunksize


@dispatch(Transpose, np.ndarray)
def compute_up(expr, x, **kwargs):
    return np.transpose(x, axes=expr.axes)


@dispatch(TensorDot, np.ndarray, np.ndarray)
def compute_up(expr, lhs, rhs, **kwargs):
    return np.tensordot(lhs, rhs, axes=[expr._left_axes, expr._right_axes])
