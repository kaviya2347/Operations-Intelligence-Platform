"""One definition per metric: the reporting cube, the fact table and the dashboard formula must agree."""
import pytest

from oip import db
from oip.warehouse.metrics import METRICS


def one(sql):
    return db.read_sql(sql).iloc[0, 0]


@pytest.mark.parametrize("queue", ["Q01", "Q04", "Q07"])
def test_service_level_cube_equals_fact(queue):
    fact = one(f"""SELECT 1.0 * SUM(within_sl) / SUM(sl_eligible) FROM fact_interaction
                   WHERE queue_id = '{queue}' AND date_key BETWEEN 20260501 AND 20260531""")
    cube = one(f"""SELECT 1.0 * SUM(sl_num) / SUM(sl_den) FROM rpt_interval_cube
                   WHERE queue_id = '{queue}' AND date_key BETWEEN 20260501 AND 20260531""")
    assert fact == pytest.approx(cube, abs=1e-9)


def test_aht_cube_equals_fact():
    fact = one("SELECT SUM(handle_sec) / SUM(handled) FROM fact_interaction WHERE handled = 1 AND queue_id = 'Q01'")
    cube = one("SELECT SUM(handle_sec) / SUM(handled) FROM rpt_interval_cube WHERE queue_id = 'Q01'")
    assert fact == pytest.approx(cube, rel=1e-5)     # cube stores interval sums rounded to whole seconds


def test_offered_and_abandoned_totals_match():
    f = db.read_sql("SELECT COUNT(*) AS offered, SUM(abandoned) AS abandoned FROM fact_interaction").iloc[0]
    c = db.read_sql("SELECT SUM(offered) AS offered, SUM(abandoned) AS abandoned FROM rpt_interval_cube").iloc[0]
    assert int(f.offered) == int(c.offered) and int(f.abandoned) == int(c.abandoned)


def test_short_abandons_excluded_from_service_level_denominator():
    r = db.read_sql("""SELECT SUM(sl_eligible) AS den, COUNT(*) AS rt, SUM(short_abandon) AS sa
                       FROM fact_interaction WHERE realtime = 1""").iloc[0]
    assert int(r.den) == int(r.rt) - int(r.sa)


def test_every_ratio_metric_is_ratio_of_sums():
    for m in METRICS:
        assert m.num, m.id
        if m.den:
            assert all(sign in (1, -1) for _, sign in m.den)


def test_fcr_excludes_immature_window():
    late = one("SELECT SUM(fcr_eligible) FROM fact_interaction WHERE date_key > 20260524")
    assert late == 0
