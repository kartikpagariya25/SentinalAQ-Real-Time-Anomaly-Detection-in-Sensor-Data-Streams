import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "streaming"))
import scoring


def _feed(state, states, neighbor_map, sid, t_ns, readings, nan=False):
    values = {c: readings.get(c, 0.0) for c in scoring.FEATURE_COLS}
    return scoring.score_row(sid, t_ns, values, nan, state, states, neighbor_map)


def test_flatline_detected_after_window():
    states = {"A": scoring.StationState()}
    neighbor_map = {"A": []}
    t = 0
    flags = []
    for i in range(6):
        flag, label, fired, z = _feed(
            states["A"], states, neighbor_map, "A", t,
            {"pm25": 50.0, "pm10": 80.0, "no2": 20.0, "co": 1.0, "temperature": 25.0, "humidity": 40.0},
        )
        flags.append((flag, fired))
        t += 5 * 60 * 1_000_000_000  # 5 minutes in ns
    assert flags[-1][0] == 1
    assert "flatline" in flags[-1][1]


def test_missing_row_is_skipped():
    states = {"A": scoring.StationState()}
    neighbor_map = {"A": []}
    flag, label, fired, z = _feed(
        states["A"], states, neighbor_map, "A", 0,
        {"pm25": 50.0}, nan=True,
    )
    assert flag == 0
    assert fired == []


def test_zscore_flags_sudden_spike():
    # Baseline alternates 49.0/51.0 (not a constant) so the rolling variance
    # is nonzero - zscore()'s own var<=0 guard means an exactly-constant
    # baseline would make it impossible to ever flag anything, no matter
    # how large the spike is.
    states = {"A": scoring.StationState()}
    neighbor_map = {"A": []}
    t = 0
    for i in range(20):
        pm25 = 49.0 if i % 2 == 0 else 51.0
        reading = {"pm25": pm25, "pm10": 80.0, "no2": 20.0, "co": 1.0, "temperature": 25.0, "humidity": 40.0}
        _feed(states["A"], states, neighbor_map, "A", t, reading)
        t += 5 * 60 * 1_000_000_000
    spike = {"pm25": 500.0, "pm10": 80.0, "no2": 20.0, "co": 1.0, "temperature": 25.0, "humidity": 40.0}
    flag, label, fired, z = _feed(states["A"], states, neighbor_map, "A", t, spike)
    assert flag == 1
    assert "zscore" in fired
