"""Read explicit acquisition-time evidence from an M2K configuration file."""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class M2KTimeEvidenceError(ValueError):
    """Raised when an M2K config has absent, invalid, or conflicting time data."""


_MAX_CONFIG_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class M2KAcquisitionStartEvidence:
    anchor_datetime: datetime
    source_type: str = "M2K_CONFIG_DATE_ACQUIS"
    source_ref: str = "M2kConfig.xml#M2kData/@dateAcquis"
    source_sha256: str = ""
    timezone_known: bool = False


def read_m2k_acquisition_start(path: str | Path) -> M2KAcquisitionStartEvidence:
    """Read ``dateAcquis`` without inferring timezone or other M2K semantics.

    Multiple occurrences are accepted only when they contain the same exact
    value. This prevents silently choosing between conflicting metadata fields.
    """
    config_path = Path(path)
    try:
        raw_bytes = config_path.read_bytes()
        if len(raw_bytes) > _MAX_CONFIG_BYTES:
            raise M2KTimeEvidenceError("M2K config exceeds 10 MiB size limit")
        root = ET.fromstring(raw_bytes)
    except (ET.ParseError, OSError) as exc:
        raise M2KTimeEvidenceError(f"cannot read M2K config: {config_path.name}") from exc
    digest = hashlib.sha256(raw_bytes).hexdigest()

    values = [
        element.attrib["dateAcquis"].strip()
        for element in root.iter()
        if "dateAcquis" in element.attrib
    ]
    if not values:
        raise M2KTimeEvidenceError("M2K config has no dateAcquis field")
    if len(set(values)) != 1:
        raise M2KTimeEvidenceError("M2K config contains conflicting dateAcquis values")
    try:
        acquisition_start = datetime.strptime(values[0], "%d-%m-%Y %H:%M:%S")
    except ValueError as exc:
        raise M2KTimeEvidenceError("M2K dateAcquis must use DD-MM-YYYY HH:MM:SS") from exc

    return M2KAcquisitionStartEvidence(
        anchor_datetime=acquisition_start,
        source_sha256=digest,
    )
