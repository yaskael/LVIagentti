# LVI IFC MCP Server

A production-ready Python [MCP](https://modelcontextprotocol.io/) server for Finnish HVAC/MEP IFC file analysis, using the national **LVI-TUOTEOSA** product codelist (RYTJ).

**LVI** = Lämmitys (Heating) · Vesi (Plumbing) · Ilmastointi (Ventilation)

---

## Features

| Tool | Description |
|---|---|
| `parse_ifc_elements_tool` | List MEP/HVAC elements — paginated (`offset`, `limit`), filterable by IFC type |
| `extract_ifc_properties_tool` | Property sets for one element — filter by `pset_names` to save tokens |
| `classify_ifc_element_tool` | Match one element to the best LVI-TUOTEOSA code with confidence scores |
| `batch_classify_tool` | **Classify multiple elements in one call** — pass a list of GlobalIds |
| `validate_lvi_codes_tool` | Validate LVI codes — paginated, returns only invalid by default; includes `match_reasoning` |
| `generate_lvi_report_tool` | Summary: counts, code distribution, hierarchy; unclassified IDs capped to avoid token burn |
| `lookup_lvi_code_tool` | Search the codelist by code, Finnish term, or short name (no IFC needed) |
| `enrich_ifc_tool` | **Write LVI codes back into the IFC model** — dry-run preview, backup, split skip reasons |
| `auto_enrich_ifc_tool` | **Classify + enrich all unclassified elements in one call** — auto-assigns high-confidence codes |

All list-returning tools are paginated and filter server-side — the AI receives only the data it needs.

---

## Getting Started

### Option A — Run locally with Python

**Prerequisites:** Python 3.11+

**1. Clone and install**
```bash
git clone https://github.com/your-org/LVIagentti.git
cd LVIagentti
pip install -e ".[dev]"
```

This installs the `lvi-mcp` console script and all dependencies (`mcp[cli]`, `ifcopenshell`, `pydantic`, `python-dotenv`).

**2. Verify the install**
```bash
lvi-mcp --help
# or
python -m lvi_mcp.server --help
```

**3. Start the server**

| Mode | Command |
|---|---|
| stdio (for Claude Desktop / MCP clients) | `python -m lvi_mcp.server` |
| SSE / HTTP (for MCP Inspector or browser clients) | `python -m lvi_mcp.server --transport sse --host 127.0.0.1 --port 8000` |
| Interactive dev UI (MCP Inspector) | `mcp dev src/lvi_mcp/server.py` |

SSE server will be available at `http://127.0.0.1:8000/sse`.

**4. Connect Claude Desktop**

Add to your Claude Desktop MCP config (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "lvi-mcp": {
      "command": "python",
      "args": ["-m", "lvi_mcp.server"],
      "cwd": "/absolute/path/to/LVIagentti"
    }
  }
}
```

---

### Option B — Run with Docker

**Prerequisites:** Docker

**1. Build the image**
```bash
docker build -t lvi-mcp .
```

**2. Run (stdio — for Claude Desktop)**
```bash
# Create a folder for your IFC files first
mkdir ifc_files

docker run -i --rm \
  -v ./ifc_files:/ifc_files:ro \
  lvi-mcp
```

**3. Run (SSE / HTTP — for MCP Inspector)**
```bash
docker compose --profile sse up
# Server available at http://localhost:8000/sse
```

**4. Connect Claude Desktop with Docker**
```json
{
  "mcpServers": {
    "lvi-mcp": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "-v", "/absolute/path/to/ifc_files:/ifc_files:ro", "lvi-mcp"]
    }
  }
}
```

> **IFC file access:** Place `.ifc` files in `./ifc_files/` and reference them as `/ifc_files/model.ifc` inside the container.

---

## Quick Verification

```bash
# 1. Lookup by Finnish term
mcp call lookup_lvi_code_tool '{"query": "lämmönjakokeskus"}'
# Expected: T-LVI-01-01-001 Lämmönjakokeskus (LJK)

# 2. Lookup by short name (limit results)
mcp call lookup_lvi_code_tool '{"query": "LJK", "max_results": 5}'

# 3. Summary report (recommended first call on any model)
mcp call generate_lvi_report_tool '{"ifc_path": "/path/to/model.ifc"}'

# 4. Validate — only invalid elements, first page of 50
mcp call validate_lvi_codes_tool '{"ifc_path": "/path/to/model.ifc", "only_invalid": true}'

# 5. Parse elements — paginated (page 2)
mcp call parse_ifc_elements_tool '{"ifc_path": "/path/to/model.ifc", "offset": 50, "limit": 50}'
```

---

## Enriching an IFC Model with LVI Codes

The server supports two enrichment workflows.

### Workflow A — Automatic (recommended for first pass)

`auto_enrich_ifc_tool` classifies all unclassified elements and writes codes in one call:

```
1. generate_lvi_report_tool   → see scope (how many unclassified)
2. auto_enrich_ifc_tool       → dry_run=True to preview proposals
3. auto_enrich_ifc_tool       → dry_run=False to write the file
4. validate_lvi_codes_tool    → confirm result; review low_confidence_elements manually
```

**Example — preview without writing:**
```json
{
  "tool": "auto_enrich_ifc_tool",
  "arguments": {
    "ifc_path": "/path/to/model.ifc",
    "min_score": 0.7,
    "dry_run": true
  }
}
```

**Response:**
```json
{
  "total_unclassified": 142,
  "auto_assigned_count": 118,
  "low_confidence_count": 24,
  "proposals": [...],
  "low_confidence_elements": [...],
  "output_path": null,
  "ifc_base64": null,
  "dry_run": true
}
```

Elements in `low_confidence_elements` need manual review — pass them to `batch_classify_tool`
and use `enrich_ifc_tool` to write the confirmed assignments.

---

### Workflow B — Manual (precise control)

```
1. generate_lvi_report_tool   → overview
2. validate_lvi_codes_tool    → see which elements need codes + suggestions with reasoning
3. batch_classify_tool        → classify groups of elements in one call
4. enrich_ifc_tool            → dry_run=True to preview, then write
```

**Example — batch classify:**
```json
{
  "tool": "batch_classify_tool",
  "arguments": {
    "ifc_path": "/path/to/model.ifc",
    "global_ids": ["id1", "id2", "id3"],
    "max_matches_per_element": 3
  }
}
```

**Example — dry-run enrich:**
```json
{
  "tool": "enrich_ifc_tool",
  "arguments": {
    "ifc_path": "/path/to/model.ifc",
    "dry_run": true,
    "assignments": [
      {"global_id": "0A1B2C...", "lvi_code": "T-LVI-01-01-001"},
      {"global_id": "1B2C3D...", "lvi_code": "T-LVI-02-03-005"}
    ]
  }
}
```

**Example — write enriched file:**
```json
{
  "tool": "enrich_ifc_tool",
  "arguments": {
    "ifc_path": "/path/to/model.ifc",
    "assignments": [...]
  }
}
```

> When `output_path` is omitted and `ifc_path` was used, the enriched file is automatically
> saved as `<original_stem>_enriched.ifc` in the same directory. The original is backed up
> to `.bak` if it already exists.

**EnrichIfcResult fields:**
```json
{
  "assigned_count": 2,
  "skipped_count": 1,
  "skipped_not_found": [],
  "skipped_invalid_code": ["bad-id-here"],
  "output_path": "/path/to/model_enriched.ifc",
  "ifc_base64": null,
  "dry_run": false
}
```

`skipped_not_found` = GlobalId not in the IFC model.
`skipped_invalid_code` = code not in the LVI-TUOTEOSA codelist.

---

## Codelist

The LVI-TUOTEOSA codelist (`data/codelist_LVI-TUOTEOSA_Versio_1_0.json`) is sourced from the Finnish national code registry (RYTJ / Suomi.fi koodistot).

Hierarchy:
- Level 1: `T-LVI-XX` — Main group (e.g. LAITTEISTOT - LVI)
- Level 2: `T-LVI-XX-XX` — Sub-group (e.g. LÄMMITYS- JA JÄÄHDYTYSLAITTEISTOT)
- Level 3: `T-LVI-XX-XX-XXX` — Product name (e.g. Lämmönjakokeskus, shortName: LJK)

Labels are Finnish-only. The `short_name` field (e.g. `LJK`, `PP`, `IV`) and `definition_fi`
are the most useful semantic anchors when working without Finnish language knowledge.

---

## IFC Input

All IFC tools accept the file as either:
- `ifc_path` — absolute local file path (**preferred for files over 10 MB**)
- `ifc_base64` — base64-encoded `.ifc` file content (small files only; see [INSTRUCTIONS.md](INSTRUCTIONS.md) for size limits)

With Docker, the file must be in a mounted volume. See [INSTRUCTIONS.md](INSTRUCTIONS.md) for details.

---

## Large File Considerations

IfcOpenShell loads the entire IFC model into memory — there is no streaming. Memory usage is typically 5–10× the file size on disk. The Docker container is configured with a 4 GB memory limit by default (adjust `mem_limit` in `docker-compose.yml` for larger models).

---

## LVI Code Property Set Convention

By default, all tools read and write the LVI code from/to:
- Property set: `LVI_Luokitus`
- Property name: `LVI_Tuoteosa`

These can be overridden per tool call via `property_set_name` and `property_name`.
