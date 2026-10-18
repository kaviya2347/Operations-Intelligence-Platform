"""Erlang C queueing maths (vectorised).

Used in two places:
  * the source simulator, to produce waits and abandons that respond to staffing
  * the forecast-to-staffing plan, to convert forecast volume into required agents

Notation: a = offered load in Erlangs (arrivals per second x AHT), N = agents.
"""
from __future__ import annotations

import numpy as np


def erlang_c(n_agents, load):
    """Probability that an arriving contact waits (M/M/N). Returns 1.0 where N <= a."""
    n = np.atleast_1d(np.asarray(n_agents, dtype=float))
    a = np.atleast_1d(np.asarray(load, dtype=float))
    n, a = np.broadcast_arrays(n, a)
    n_int = np.maximum(np.round(n).astype(int), 0)
    max_n = int(n_int.max()) if n_int.size else 0
    b = np.ones_like(a)                       # Erlang B via the stable recursion
    out_b = np.where(n_int == 0, 1.0, np.nan)
    for k in range(1, max_n + 1):
        b = a * b / (k + a * b)
        out_b = np.where(n_int == k, b, out_b)
    with np.errstate(divide="ignore", invalid="ignore"):
        c = n * out_b / (n - a * (1 - out_b))
    c = np.where((n <= a) | (n_int == 0), 1.0, c)
    return np.clip(c, 0.0, 1.0)


def service_level(n_agents, load, aht_sec, threshold_sec):
    """Share of contacts answered within threshold under Erlang C."""
    n = np.asarray(n_agents, dtype=float)
    a = np.asarray(load, dtype=float)
    c = erlang_c(n, a)
    with np.errstate(over="ignore", invalid="ignore"):
        sl = 1.0 - c * np.exp(-(n - a) * threshold_sec / np.asarray(aht_sec, dtype=float))
    return np.where(n <= a, 0.0, np.clip(sl, 0.0, 1.0))


def asa(n_agents, load, aht_sec):
    """Average speed of answer in seconds."""
    n = np.asarray(n_agents, dtype=float)
    a = np.asarray(load, dtype=float)
    c = erlang_c(n, a)
    with np.errstate(divide="ignore", invalid="ignore"):
        w = c * np.asarray(aht_sec, dtype=float) / (n - a)
    return np.where(n <= a, np.inf, w)


def required_agents(volume, aht_sec, threshold_sec, target, interval_sec=1800, max_extra=60):
    """Smallest N meeting the service level target for each interval (0 where volume is 0)."""
    vol = np.atleast_1d(np.asarray(volume, dtype=float))
    aht = np.broadcast_to(np.asarray(aht_sec, dtype=float), vol.shape)
    load = vol * aht / interval_sec
    n = np.floor(load) + 1
    need = np.zeros_like(load)
    done = vol <= 0
    for _ in range(max_extra):
        sl = service_level(n, load, aht, threshold_sec)
        ok = (sl >= target) & ~done
        need = np.where(ok, n, need)
        done = done | ok
        if done.all():
            break
        n = np.where(done, n, n + 1)
    need = np.where(done, need, n)
    return np.where(vol <= 0, 0, need).astype(int)
