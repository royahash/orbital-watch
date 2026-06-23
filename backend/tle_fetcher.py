"""
tle_fetcher.py
--------------
Fetches Two-Line Element (TLE) sets from CelesTrak's public API.

We fetch in TLE text format (3-line: name, line1, line2) and also pull
JSON metadata for orbital parameters like inclination and eccentricity.
"""

import httpx
import re
from typing import List, Dict

GP_JSON_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=json"
GP_TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle"

GROUPS = {
    "starlink": "starlink",
    "gps":      "gps-ops",
    "iss":      "stations",
}


def _parse_tle_text(text: str) -> List[Dict]:
    """Parse 3-line TLE format into list of dicts with OBJECT_NAME, TLE_LINE1, TLE_LINE2."""
    lines = [l for l in text.strip().splitlines() if l.strip()]
    results = []
    i = 0
    while i + 2 < len(lines):
        name_line = lines[i].strip()
        line1 = lines[i + 1].strip()
        line2 = lines[i + 2].strip()

        if not line1.startswith("1 ") or not line2.startswith("2 "):
            i += 1
            continue

        norad_id = line1[2:7].strip()

        results.append({
            "OBJECT_NAME": name_line,
            "TLE_LINE1": line1,
            "TLE_LINE2": line2,
            "NORAD_CAT_ID": norad_id,
        })
        i += 3

    return results


def _merge_json_metadata(tle_list: List[Dict], json_data: List[Dict]) -> List[Dict]:
    """Merge orbital parameters from JSON response into TLE records."""
    json_by_id = {}
    for item in json_data:
        nid = str(item.get("NORAD_CAT_ID", ""))
        if nid:
            json_by_id[nid] = item

    for record in tle_list:
        nid = str(record.get("NORAD_CAT_ID", ""))
        meta = json_by_id.get(nid, {})
        record["EPOCH"] = meta.get("EPOCH")
        record["INCLINATION"] = meta.get("INCLINATION")
        record["ECCENTRICITY"] = meta.get("ECCENTRICITY")
        record["MEAN_MOTION"] = meta.get("MEAN_MOTION")

    return tle_list


async def fetch_tle_group(group: str = "starlink") -> List[Dict]:
    """
    Fetches satellite data for a named group from CelesTrak.

    Returns a list of dicts, each containing:
      - OBJECT_NAME: human-readable name
      - TLE_LINE1, TLE_LINE2: the two TLE lines for sgp4
      - NORAD_CAT_ID, EPOCH, INCLINATION, ECCENTRICITY, MEAN_MOTION
    """
    group_key = GROUPS.get(group, group)
    tle_url = GP_TLE_URL.format(group=group_key)
    json_url = GP_JSON_URL.format(group=group_key)

    async with httpx.AsyncClient(timeout=30.0) as client:
        tle_resp, json_resp = await client.get(tle_url), await client.get(json_url)
        tle_resp.raise_for_status()

        tle_list = _parse_tle_text(tle_resp.text)

        try:
            json_resp.raise_for_status()
            json_data = json_resp.json()
            if isinstance(json_data, list):
                tle_list = _merge_json_metadata(tle_list, json_data)
        except Exception:
            pass

        return tle_list
