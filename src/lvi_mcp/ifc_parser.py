"""IfcOpenShell wrappers — load IFC from path or base64 blob."""

from __future__ import annotations

import base64
import os
import tempfile
from typing import Any

import ifcopenshell
import ifcopenshell.util.element as ifc_util

# MEP/HVAC IFC types relevant for LVI classification
DEFAULT_MEP_TYPES: list[str] = [
    "IfcAirTerminal",
    "IfcAirTerminalBox",
    "IfcAirToAirHeatRecovery",
    "IfcBoiler",
    "IfcBurner",
    "IfcChiller",
    "IfcCoil",
    "IfcCompressor",
    "IfcCondenser",
    "IfcCooledBeam",
    "IfcCoolingTower",
    "IfcDamper",
    "IfcDuctFitting",
    "IfcDuctSegment",
    "IfcDuctSilencer",
    "IfcElectricGenerator",
    "IfcElectricMotor",
    "IfcEvaporativeCooler",
    "IfcEvaporator",
    "IfcFan",
    "IfcFilter",
    "IfcFireSuppression",
    "IfcFlowController",
    "IfcFlowFitting",
    "IfcFlowInstrument",
    "IfcFlowMeter",
    "IfcFlowMovingDevice",
    "IfcFlowSegment",
    "IfcFlowStorageDevice",
    "IfcFlowTerminal",
    "IfcFlowTreatmentDevice",
    "IfcHeatExchanger",
    "IfcHumidifier",
    "IfcInterceptor",
    "IfcJunctionBox",
    "IfcLamp",
    "IfcLightFixture",
    "IfcMedicalDevice",
    "IfcMotorConnection",
    "IfcPipeFitting",
    "IfcPipeSegment",
    "IfcPump",
    "IfcSanitaryTerminal",
    "IfcSolarDevice",
    "IfcSpaceHeater",
    "IfcStackTerminal",
    "IfcTank",
    "IfcTubeBundle",
    "IfcUnitaryControlElement",
    "IfcUnitaryEquipment",
    "IfcValve",
    "IfcVibrationIsolator",
    "IfcWasteTerminal",
]


# ---------------------------------------------------------------------------
# IFC file cache — avoids re-parsing the same file across tool calls
# ---------------------------------------------------------------------------

class _IfcCache:
    """Simple cache keyed on (absolute_path, mtime).

    Holds at most ``max_entries`` files.  Entries are evicted LRU-style when
    the limit is reached.  Base64-loaded files are never cached (no stable key).
    """

    def __init__(self, max_entries: int = 4) -> None:
        self._max = max_entries
        # key → (mtime, ifcopenshell.file)
        self._store: dict[str, tuple[float, ifcopenshell.file]] = {}
        # insertion / access order (most-recent at end)
        self._order: list[str] = []

    def get(self, path: str) -> ifcopenshell.file | None:
        abspath = os.path.abspath(path)
        try:
            mtime = os.path.getmtime(abspath)
        except OSError:
            return None

        cached = self._store.get(abspath)
        if cached is not None and cached[0] == mtime:
            # Move to end (most recently used)
            if abspath in self._order:
                self._order.remove(abspath)
            self._order.append(abspath)
            return cached[1]
        return None

    def put(self, path: str, ifc_file: ifcopenshell.file) -> None:
        abspath = os.path.abspath(path)
        try:
            mtime = os.path.getmtime(abspath)
        except OSError:
            return

        # Evict if full
        while len(self._store) >= self._max and self._order:
            oldest = self._order.pop(0)
            self._store.pop(oldest, None)

        self._store[abspath] = (mtime, ifc_file)
        if abspath in self._order:
            self._order.remove(abspath)
        self._order.append(abspath)

    def invalidate(self, path: str) -> None:
        """Remove a path from the cache (e.g. after writing to it)."""
        abspath = os.path.abspath(path)
        self._store.pop(abspath, None)
        if abspath in self._order:
            self._order.remove(abspath)


_ifc_cache = _IfcCache()


def load_ifc(ifc_path: str | None, ifc_base64: str | None) -> ifcopenshell.file:
    """Load an IFC file from a local path or a base64-encoded string.

    Path-based loads are cached by (path, mtime) so repeated tool calls on the
    same file don't re-parse.  Base64 loads are never cached.
    """
    if ifc_path:
        cached = _ifc_cache.get(ifc_path)
        if cached is not None:
            return cached
        ifc_file = ifcopenshell.open(ifc_path)
        _ifc_cache.put(ifc_path, ifc_file)
        return ifc_file

    if ifc_base64:
        data = base64.b64decode(ifc_base64)
        tmp = tempfile.NamedTemporaryFile(suffix=".ifc", delete=False)
        try:
            tmp.write(data)
            tmp.close()
            return ifcopenshell.open(tmp.name)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    raise ValueError("Either ifc_path or ifc_base64 must be provided.")


def invalidate_cache(path: str) -> None:
    """Invalidate the IFC cache for a path (call after writing)."""
    _ifc_cache.invalidate(path)


# ---------------------------------------------------------------------------
# Write helpers (consolidated here so all IFC I/O lives in one module)
# ---------------------------------------------------------------------------

def write_ifc(
    ifc_file: ifcopenshell.file,
    output_path: str | None,
    backup: bool,
) -> tuple[str | None, str | None]:
    """Write *ifc_file* to *output_path* (with optional .bak backup) or return base64.

    Returns ``(output_path, None)`` when written to disk, or
    ``(None, base64_string)`` when no output_path is given.
    """
    if output_path:
        if backup and os.path.exists(output_path):
            os.rename(output_path, output_path + ".bak")
        ifc_file.write(output_path)
        # Invalidate cache for the written path so the next load picks up changes
        _ifc_cache.invalidate(output_path)
        return output_path, None

    # No output path → return base64
    with tempfile.NamedTemporaryFile(suffix=".ifc", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        ifc_file.write(tmp_path)
        with open(tmp_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return None, encoded


def resolve_output_path(ifc_path: str | None, output_path: str | None) -> str | None:
    """Auto-generate ``<stem>_enriched.ifc`` when *ifc_path* is known and *output_path* is omitted."""
    if output_path is not None:
        return output_path
    if ifc_path:
        from pathlib import Path
        p = Path(ifc_path)
        return str(p.with_stem(p.stem + "_enriched"))
    return None


# ---------------------------------------------------------------------------
# Element helpers
# ---------------------------------------------------------------------------

def get_element_info(element: Any) -> dict[str, str | None]:
    return {
        "global_id": element.GlobalId,
        "ifc_type": element.is_a(),
        "name": getattr(element, "Name", None),
        "description": getattr(element, "Description", None),
        "object_type": getattr(element, "ObjectType", None),
    }


def get_property_sets(element: Any) -> list[dict[str, Any]]:
    """Return all property sets attached to an element."""
    psets = []
    for rel in getattr(element, "IsDefinedBy", []):
        if rel.is_a("IfcRelDefinesByProperties"):
            pdef = rel.RelatingPropertyDefinition
            if pdef.is_a("IfcPropertySet"):
                props: dict[str, Any] = {}
                for prop in pdef.HasProperties:
                    if prop.is_a("IfcPropertySingleValue") and prop.NominalValue is not None:
                        props[prop.Name] = prop.NominalValue.wrappedValue
                    elif prop.is_a("IfcPropertySingleValue"):
                        props[prop.Name] = None
                    else:
                        props[prop.Name] = str(prop)
                psets.append({"pset_name": pdef.Name, "properties": props})
    return psets


def get_lvi_code_from_element(
    element: Any,
    pset_name: str = "LVI_Luokitus",
    prop_name: str = "LVI_Tuoteosa",
) -> str | None:
    """Extract the LVI code stored in a property set, if present."""
    for pset in get_property_sets(element):
        if pset["pset_name"] == pset_name:
            return pset["properties"].get(prop_name)
    return None


def iter_mep_elements(
    ifc_file: ifcopenshell.file,
    ifc_types: list[str] | None = None,
) -> list[Any]:
    """Return all MEP elements matching the requested types."""
    types_to_query = ifc_types or DEFAULT_MEP_TYPES
    elements: list[Any] = []
    for ifc_type in types_to_query:
        try:
            elements.extend(ifc_file.by_type(ifc_type))
        except Exception:
            pass
    return elements
