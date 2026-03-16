# LVI IFC MCP — Project Conventions

## Language & Runtime
- Python 3.11+
- Package manager: pip (editable install)

## Key Dependencies
- `mcp[cli]` — Anthropic MCP Python SDK (`FastMCP`)
- `ifcopenshell` — IFC file parsing
- `pydantic` v2 — input/output validation
- `python-dotenv` — optional env config

## Project Layout
```
src/lvi_mcp/
  server.py       # FastMCP instance + @mcp.tool() registrations
  ifc_parser.py   # load_ifc(), iter_mep_elements(), get_property_sets()
  codelist.py     # LviCodelist class, get_codelist() singleton
  models.py       # Pydantic input/output models
  tools/
    ifc_tools.py  # parse_ifc_elements, extract_ifc_properties
    lvi_tools.py  # classify, validate, report, lookup, enrich
data/
  codelist_LVI-TUOTEOSA_Versio_1_0.json
```

## Running the Server
```bash
# Install (editable)
pip install -e ".[dev]"

# Start MCP server (stdio transport, for Claude Desktop / MCP clients)
python -m lvi_mcp.server
# or
mcp dev src/lvi_mcp/server.py
```

## IFC Input Convention
All IFC tools accept **either**:
- `ifc_path` — absolute local file path (preferred for files > 10 MB)
- `ifc_base64` — base64-encoded `.ifc` file content (small files only)

## Token Efficiency — Design Principle
**The MCP server does heavy lifting so the AI model receives only concise, relevant data.**

All list-returning tools use pagination and server-side filtering to prevent
large IFC models (10K+ elements) from dumping megabytes of JSON into the AI
context window.

### Pagination
- `parse_ifc_elements_tool` and `validate_lvi_codes_tool` return
  `{total, offset, limit, items}` — the AI sees one page at a time.
- Default `limit=50`. The AI can request more pages with `offset`.

### Server-side filtering
- `validate_lvi_codes_tool` defaults to `only_invalid=True` — valid elements
  are never sent to the AI unless explicitly requested.
- `extract_ifc_properties_tool` accepts `pset_names` to return only the
  property sets the AI needs.
- `generate_lvi_report_tool` caps `unclassified_element_ids` to the first
  N entries (default 50) and includes `unclassified_element_count` for the total.

### Recommended tool call order (summary → drill-down → enrich)
1. `generate_lvi_report_tool` — compact overview (counts + distribution)
2. `validate_lvi_codes_tool` — only problems, paginated
3. `classify_ifc_element_tool` — targeted classification of specific elements
4. `extract_ifc_properties_tool` — deep dive with `pset_names` filter
5. `enrich_ifc_tool` — write LVI codes back into the model once assignments are confirmed

### Enrichment (write-back)
- `enrich_ifc_tool` accepts a list of `{global_id, lvi_code}` assignments.
- Only codes that exist in the codelist are written; unknown codes are skipped and reported.
- Creates the `LVI_Luokitus` property set on the element if it doesn't exist, otherwise updates it.
- Returns the modified IFC as `output_path` (saved file) or `ifc_base64` (in-memory).
- `EnrichIfcResult` always includes `assigned_count`, `skipped_count`, and `skipped_ids`.

### When adding new tools
- **Never return unbounded lists.** Always add `offset`/`limit` or a `max_results` cap.
- **Filter server-side first.** If the AI only needs a subset, provide a filter param.
- **Return counts alongside data** so the AI knows the full scope without loading it.

## Codelist Structure
- File: `data/codelist_LVI-TUOTEOSA_Versio_1_0.json`
- 3-level hierarchy: `T-LVI-XX` > `T-LVI-XX-XX` > `T-LVI-XX-XX-XXX`
- Level 3 entries have `shortName` (e.g. `LJK`) and Finnish `prefLabel`

## Validation Rules
- All tool inputs validated via Pydantic models in `models.py`
- IFC source validation enforced by `IfcInputBase.require_one_source`

## Adding New Tools
1. Add Pydantic input/output models in `models.py`
2. Implement business logic in `tools/ifc_tools.py` or `tools/lvi_tools.py`
3. Register with `@mcp.tool()` in `server.py`
