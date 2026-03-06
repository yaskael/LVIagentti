"""IFC-facing MCP tools: parse_ifc_elements and extract_ifc_properties."""

from __future__ import annotations

from lvi_mcp.ifc_parser import (
    get_element_info,
    get_property_sets,
    iter_mep_elements,
    load_ifc,
)
from lvi_mcp.models import (
    ElementProperties,
    ExtractIfcPropertiesInput,
    IfcElementInfo,
    PaginatedResponse,
    ParseIfcElementsInput,
    PropertySetInfo,
)


def parse_ifc_elements(params: ParseIfcElementsInput) -> PaginatedResponse:
    """List MEP/HVAC elements from an IFC file with pagination."""
    ifc_file = load_ifc(params.ifc_path, params.ifc_base64)
    elements = iter_mep_elements(ifc_file, params.ifc_types)
    total = len(elements)

    page = elements[params.offset : params.offset + params.limit]
    items = [IfcElementInfo(**get_element_info(el)) for el in page]

    return PaginatedResponse(
        total=total,
        offset=params.offset,
        limit=params.limit,
        items=items,
    )


def extract_ifc_properties(params: ExtractIfcPropertiesInput) -> ElementProperties:
    """Extract property sets for a single IFC element, optionally filtered."""
    ifc_file = load_ifc(params.ifc_path, params.ifc_base64)

    try:
        element = ifc_file.by_guid(params.global_id)
    except Exception:
        element = None

    if element is None:
        raise ValueError(f"Element with GlobalId '{params.global_id}' not found.")

    info = get_element_info(element)
    raw_psets = get_property_sets(element)

    if params.pset_names:
        allowed = set(params.pset_names)
        raw_psets = [ps for ps in raw_psets if ps["pset_name"] in allowed]

    psets = [PropertySetInfo(**ps) for ps in raw_psets]

    return ElementProperties(
        global_id=info["global_id"],
        ifc_type=info["ifc_type"],
        name=info["name"],
        property_sets=psets,
    )
