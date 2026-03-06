"""MCP server entry point — registers all LVI tools."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from lvi_mcp.models import (
    ClassifyIfcElementInput,
    ExtractIfcPropertiesInput,
    GenerateLviReportInput,
    LookupLviCodeInput,
    ParseIfcElementsInput,
    ValidateLviCodesInput,
)
from lvi_mcp.tools.ifc_tools import extract_ifc_properties, parse_ifc_elements
from lvi_mcp.tools.lvi_tools import (
    classify_ifc_element,
    generate_lvi_report,
    lookup_lvi_code,
    validate_lvi_codes,
)

mcp = FastMCP(
    "lvi-mcp",
    description="Finnish LVI (HVAC) IFC classification using the LVI-TUOTEOSA product codelist.",
)


def _json(obj: Any) -> str:
    """Serialize Pydantic models or plain objects to a JSON string."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump_json(indent=2)
    if isinstance(obj, list):
        items = []
        for item in obj:
            if hasattr(item, "model_dump"):
                items.append(item.model_dump())
            else:
                items.append(item)
        return json.dumps(items, ensure_ascii=False, indent=2)
    return json.dumps(obj, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool: parse_ifc_elements
# ---------------------------------------------------------------------------

@mcp.tool()
def parse_ifc_elements_tool(
    ifc_path: str | None = None,
    ifc_base64: str | None = None,
    ifc_types: list[str] | None = None,
    offset: int = 0,
    limit: int = 50,
) -> str:
    """List MEP/HVAC elements from an IFC file (paginated).

    Provide either ifc_path (local file path) or ifc_base64 (base64-encoded IFC content).
    Optionally filter by IFC entity types such as ["IfcFlowTerminal", "IfcPipeSegment"].
    Returns {total, offset, limit, items} where items is a page of elements.
    Use offset/limit to page through large models without burning tokens.
    """
    params = ParseIfcElementsInput(
        ifc_path=ifc_path, ifc_base64=ifc_base64, ifc_types=ifc_types,
        offset=offset, limit=limit,
    )
    results = parse_ifc_elements(params)
    return _json(results)


# ---------------------------------------------------------------------------
# Tool: extract_ifc_properties
# ---------------------------------------------------------------------------

@mcp.tool()
def extract_ifc_properties_tool(
    global_id: str,
    ifc_path: str | None = None,
    ifc_base64: str | None = None,
    pset_names: list[str] | None = None,
) -> str:
    """Extract property sets for a single IFC element identified by GlobalId.

    Provide either ifc_path or ifc_base64 and the element's GlobalId.
    Optionally pass pset_names to only return specific property sets (saves tokens).
    Returns property sets and their name/value pairs as JSON.
    """
    params = ExtractIfcPropertiesInput(
        ifc_path=ifc_path, ifc_base64=ifc_base64, global_id=global_id,
        pset_names=pset_names,
    )
    result = extract_ifc_properties(params)
    return _json(result)


# ---------------------------------------------------------------------------
# Tool: classify_ifc_element
# ---------------------------------------------------------------------------

@mcp.tool()
def classify_ifc_element_tool(
    global_id: str,
    ifc_path: str | None = None,
    ifc_base64: str | None = None,
) -> str:
    """Classify a single IFC element against the LVI-TUOTEOSA Finnish product codelist.

    Matches the element's name, object_type, and description against level-3 codelist
    entries and returns the best matching LVI codes with confidence scores and reasoning.
    """
    params = ClassifyIfcElementInput(
        ifc_path=ifc_path, ifc_base64=ifc_base64, global_id=global_id
    )
    result = classify_ifc_element(params)
    return _json(result)


# ---------------------------------------------------------------------------
# Tool: validate_lvi_codes
# ---------------------------------------------------------------------------

@mcp.tool()
def validate_lvi_codes_tool(
    ifc_path: str | None = None,
    ifc_base64: str | None = None,
    property_set_name: str = "LVI_Luokitus",
    property_name: str = "LVI_Tuoteosa",
    only_invalid: bool = True,
    offset: int = 0,
    limit: int = 50,
) -> str:
    """Validate LVI-TUOTEOSA codes stored in an IFC model's property sets (paginated).

    Checks every MEP element for an LVI code in the specified property set/property.
    By default only returns elements with missing or invalid codes (only_invalid=True).
    Set only_invalid=False to include valid elements too.
    Returns {total, offset, limit, items} with per-element validation status and suggestions.
    """
    params = ValidateLviCodesInput(
        ifc_path=ifc_path,
        ifc_base64=ifc_base64,
        property_set_name=property_set_name,
        property_name=property_name,
        only_invalid=only_invalid,
        offset=offset,
        limit=limit,
    )
    results = validate_lvi_codes(params)
    return _json(results)


# ---------------------------------------------------------------------------
# Tool: generate_lvi_report
# ---------------------------------------------------------------------------

@mcp.tool()
def generate_lvi_report_tool(
    ifc_path: str | None = None,
    ifc_base64: str | None = None,
    property_set_name: str = "LVI_Luokitus",
    property_name: str = "LVI_Tuoteosa",
    max_unclassified_ids: int = 50,
) -> str:
    """Generate a summary LVI classification report from an IFC model.

    Returns total element counts, code distribution, hierarchy breakdown by LVI group,
    unclassified_element_count (total), and the first N unclassified element IDs
    (capped by max_unclassified_ids to limit token usage).
    """
    params = GenerateLviReportInput(
        ifc_path=ifc_path,
        ifc_base64=ifc_base64,
        property_set_name=property_set_name,
        property_name=property_name,
        max_unclassified_ids=max_unclassified_ids,
    )
    result = generate_lvi_report(params)
    return _json(result)


# ---------------------------------------------------------------------------
# Tool: lookup_lvi_code
# ---------------------------------------------------------------------------

@mcp.tool()
def lookup_lvi_code_tool(
    query: str,
    max_results: int = 10,
) -> str:
    """Search the LVI-TUOTEOSA Finnish HVAC product codelist.

    Accepts a code value (e.g. "T-LVI-01-01-001"), a Finnish term (e.g. "lämmönjakokeskus"),
    or a short name (e.g. "LJK"). Returns matching entries with full hierarchy context.
    No IFC file required.
    """
    params = LookupLviCodeInput(query=query, max_results=max_results)
    results = lookup_lvi_code(params)
    return _json(results)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    import os

    parser = argparse.ArgumentParser(description="LVI MCP Server")
    parser.add_argument(
        "--transport",
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
        choices=["stdio", "sse"],
        help="Transport type (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MCP_HOST", "127.0.0.1"),
        help="Host for SSE transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_PORT", "8000")),
        help="Port for SSE transport (default: 8000)",
    )
    args = parser.parse_args()

    if args.transport == "sse":
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
