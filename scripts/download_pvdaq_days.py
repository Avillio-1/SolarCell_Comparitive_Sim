"""Download NREL PVDAQ day files from the public OEDI data lake.

The raw 1-minute day files for the RTC validation sites are ~60 MB per site-half-year,
so they are not committed; this script re-fetches them deterministically from the
public, NREL-maintained bucket instead. Example (PVDAQ 1403, 2016 January-June):

    python scripts/download_pvdaq_days.py --system-id 1403 --year 2016 --months 1-6 \
        --output data/external/pvdaq_system_1403_2016_h1_raw
"""

from __future__ import annotations

import argparse
import concurrent.futures
import re
from pathlib import Path
from xml.etree import ElementTree

import httpx

BUCKET_URL = "https://oedi-data-lake.s3.amazonaws.com/"
S3_NAMESPACE = "{http://s3.amazonaws.com/doc/2006-03-01/}"
DOWNLOAD_ATTEMPTS = 3


def list_keys(client: httpx.Client, prefix: str) -> list[str]:
    """List every object key under a prefix, following S3 pagination."""

    keys: list[str] = []
    token: str | None = None
    while True:
        params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token is not None:
            params["continuation-token"] = token
        response = client.get(BUCKET_URL, params=params)
        response.raise_for_status()
        root = ElementTree.fromstring(response.text)
        keys.extend(element.text or "" for element in root.iter(f"{S3_NAMESPACE}Key"))
        truncated = root.find(f"{S3_NAMESPACE}IsTruncated")
        if truncated is None or truncated.text != "true":
            return keys
        token_element = root.find(f"{S3_NAMESPACE}NextContinuationToken")
        token = token_element.text if token_element is not None else None
        if token is None:
            return keys


def download_one(client: httpx.Client, key: str, destination: Path) -> str:
    if destination.exists() and destination.stat().st_size > 0:
        return "cached"
    last_error: Exception | None = None
    for _ in range(DOWNLOAD_ATTEMPTS):
        try:
            response = client.get(BUCKET_URL + key)
            response.raise_for_status()
            destination.write_bytes(response.content)
            return "downloaded"
        except httpx.HTTPError as error:
            last_error = error
    raise RuntimeError(f"failed to download {key} after {DOWNLOAD_ATTEMPTS} attempts: {last_error}")


def parse_months(text: str) -> list[int]:
    months: set[int] = set()
    for part in text.split(","):
        match = re.fullmatch(r"(\d+)-(\d+)", part.strip())
        if match:
            months.update(range(int(match.group(1)), int(match.group(2)) + 1))
        else:
            months.add(int(part))
    if not months or min(months) < 1 or max(months) > 12:
        raise argparse.ArgumentTypeError(f"invalid month selection: {text}")
    return sorted(months)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system-id", type=int, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--months", type=parse_months, default=list(range(1, 13)))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=12)
    arguments = parser.parse_args()

    prefix = f"pvdaq/csv/pvdata/system_id={arguments.system_id}/year={arguments.year}/"
    with httpx.Client(timeout=60) as client:
        wanted: list[tuple[str, Path]] = []
        for key in list_keys(client, prefix):
            match = re.search(r"month=(\d+)/day=\d+/([^/]+\.csv)$", key)
            if match is None or int(match.group(1)) not in arguments.months:
                continue
            directory = arguments.output / f"month={int(match.group(1)):02d}"
            directory.mkdir(parents=True, exist_ok=True)
            wanted.append((key, directory / match.group(2)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=arguments.workers) as pool:
            results = list(pool.map(lambda pair: download_one(client, *pair), wanted))
    print(
        f"system {arguments.system_id} year {arguments.year}: {len(wanted)} day files "
        f"({results.count('downloaded')} downloaded, {results.count('cached')} already present)"
    )


if __name__ == "__main__":
    main()
