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


def load_ifc(ifc_path: str | None, ifc_base64: str | None) -> ifcopenshell.file:
    """Load an IFC file from a local path or a base64-encoded string."""
    if ifc_path:
        return ifcopenshell.open(ifc_path)
    if ifc_base64:
        data = base64.b64decode(ifc_base64)
        tmp = tempfile.NamedTemporaryFile(suffix=".ifc", delete=False)
        try:
            tmp.write(data)
            tmp.close()
            return ifcopenshell.open(tmp.name)
        finally:
            # IfcOpenShell keeps the file open; we delete after it's loaded.
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
    raise ValueError("Either ifc_path or ifc_base64 must be provided.")


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
