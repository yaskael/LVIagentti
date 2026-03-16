# LVI IFC MCP — Project Conventions

## Language & Runtime
- Python 3.11+
- Package manager: pip (editable install)

## Key Dependencies
- `mcp[cli]` — Anthropic MCP Python SDK (`FastMCP`)
- `ifcopenshell` — IFC file parsing and writing
- `pydantic` v2 — input/output validation
- `python-dotenv` — optional env config

## Project Layout
```
src/lvi_mcp/
  server.py       # FastMCP instance + @mcp.tool() registrations
  ifc_parser.py   # load_ifc(), write_ifc(), IFC cache, iter_mep_elements(), get_property_sets()
  codelist.py     # LviCodelist class, get_codelist() singleton
  models.py       # Pydantic input/output models
  tools/
    ifc_tools.py  # parse_ifc_elements, extract_ifc_properties
    lvi_tools.py  # classify, batch_classify, validate, report, lookup, enrich, auto_enrich
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

## Architecture

### IFC I/O — all in `ifc_parser.py`
All IFC file reading and writing lives in one module:
- `load_ifc(ifc_path, ifc_base64)` — load from path (cached) or base64 blob
- `write_ifc(ifc_file, output_path, backup)` — write to path (with .bak backup) or return base64
- `resolve_output_path(ifc_path, output_path)` — auto-generate `<stem>_enriched.ifc`
- `invalidate_cache(path)` — clear cache entry after writing

### IFC File Cache
`_IfcCache` in `ifc_parser.py` caches parsed IFC files by `(absolute_path, mtime)`.
- LRU eviction, max 4 entries
- A typical report → validate → classify → enrich workflow parses the file **once**
- Cache is automatically invalidated when `write_ifc()` writes to a cached path

### Enrichment Chaining
Both `enrich_ifc_tool` and `auto_enrich_ifc_tool` use `_load_for_enrichment()`:
- If the resolved output path already exists (e.g. from a prior enrichment), the model
  is loaded from **that file** instead of the original `ifc_path`
- This means sequential `auto_enrich → enrich` calls stack changes correctly
- Without this, the second call would reload the original and discard the first pass

### Codelist — singleton in `codelist.py`
`get_codelist()` returns a module-level `LviCodelist` singleton loaded once at import.
The codelist is Finnish-only; `short_name` and `definition_fi` are the best semantic hints.

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

### Avoiding duplicate work
- `auto_enrich_ifc_tool` accepts `exclude_global_ids` — pass IDs already
  handled by `validate_lvi_codes_tool` to skip redundant classification.
- `batch_classify_tool` classifies N elements in one call instead of N separate calls.

### Recommended tool call order (summary → drill-down → enrich)
1. `generate_lvi_report_tool` — compact overview (counts + distribution)
2. `validate_lvi_codes_tool` — only problems, paginated, includes `match_reasoning`
3. `batch_classify_tool` — classify multiple elements in one call instead of one-by-one
4. `classify_ifc_element_tool` — targeted classification of a single element
5. `extract_ifc_properties_tool` — deep dive with `pset_names` filter
6. `enrich_ifc_tool` — write confirmed codes back; use `dry_run=True` first to preview
7. `auto_enrich_ifc_tool` — classify + write all unclassified elements in one call

### When adding new tools
- **Never return unbounded lists.** Always add `offset`/`limit` or a `max_results` cap.
- **Filter server-side first.** If the AI only needs a subset, provide a filter param.
- **Return counts alongside data** so the AI knows the full scope without loading it.

## Enrichment (write-back)

### enrich_ifc_tool
- Accepts a list of `{global_id, lvi_code}` assignments.
- Only codes present in the codelist are written; unknown codes go to `skipped_invalid_code`.
- Elements not found in the model go to `skipped_not_found` (separate from invalid codes).
- `dry_run=True` validates and counts without touching any file.
- `backup=True` (default) renames an existing output file to `.bak` before overwriting.
- **Enrichment chaining:** if the resolved output file already exists from a prior call,
  loads from it so sequential enrichments stack.
- **Output path defaulting:** if `ifc_path` was given and `output_path` is omitted, saves
  as `<stem>_enriched.ifc` in the same directory. If `ifc_base64` was used and no
  `output_path` is given, returns base64.

### auto_enrich_ifc_tool
- Finds all unclassified elements, classifies each, and writes codes >= `min_score` (default 0.7).
- Elements below `min_score` are returned in `low_confidence_elements` for manual review.
- Same `dry_run` / `backup` / output-path defaulting / chaining as `enrich_ifc_tool`.
- `overwrite_existing=True` to reclassify elements that already have a valid code.
- `exclude_global_ids` to skip elements already classified elsewhere (avoids duplicate work).
- Replaces the multi-call classify-then-enrich workflow with a single tool call.

## Codelist Structure
- File: `data/codelist_LVI-TUOTEOSA_Versio_1_0.json`
- 3-level hierarchy: `T-LVI-XX` > `T-LVI-XX-XX` > `T-LVI-XX-XX-XXX`
- Level 3 entries have `shortName` (e.g. `LJK`) and Finnish `prefLabel`
- Labels are Finnish-only; `short_name` and `definition_fi` are the best semantic hints
  available for non-Finnish speakers.

## Validation Rules
- All tool inputs validated via Pydantic models in `models.py`
- IFC source validation enforced by `IfcInputBase.require_one_source`

## Adding New Tools
1. Add Pydantic input/output models in `models.py`
2. Implement business logic in `tools/ifc_tools.py` or `tools/lvi_tools.py`
3. Register with `@mcp.tool()` in `server.py`
