import pytest
from datetime import datetime, timezone
from orbital_math import build_satellite

# ISS TLE — epoch 2026-06-21
ISS_TLE1 = "1 25544U 98067A   26172.76913116  .00009060  00000+0  17028-3 0  9997"
ISS_TLE2 = "2 25544  51.6326 277.4139 0004499 214.6152 145.4544 15.49357580572463"

# CSS (Tianhe) — different inclination (41.5°), epoch 2026-06-20
CSS_TLE1 = "1 48274U 21035A   26171.43213816  .00020661  00000+0  24268-3 0  9990"
CSS_TLE2 = "2 48274  41.4693 302.2526 0007384 105.8714 254.2939 15.60937952293670"

# FREGAT DEB — eccentric orbit (e=0.09), used as a contrasting orbit
FREGAT_TLE1 = "1 49271U 11037PF  26170.86525566  .00006273  00000+0  10826-1 0  9999"
FREGAT_TLE2 = "2 49271  51.6355 353.8561 0900592 288.1563  62.3334 12.42115278225383"

REFERENCE_TIME = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def iss_sat():
    return build_satellite(ISS_TLE1, ISS_TLE2)


@pytest.fixture
def css_sat():
    return build_satellite(CSS_TLE1, CSS_TLE2)


@pytest.fixture
def fregat_sat():
    return build_satellite(FREGAT_TLE1, FREGAT_TLE2)


@pytest.fixture
def ref_time():
    return REFERENCE_TIME
