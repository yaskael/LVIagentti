# LVI IFC MCP Server

A production-ready Python [MCP](https://modelcontextprotocol.io/) server for Finnish HVAC/MEP IFC file analysis, using the national **LVI-TUOTEOSA** product codelist (RYTJ).

**LVI** = Lämmitys (Heating) · Vesi (Plumbing) · Ilmastointi (Ventilation)

---

## Features

| Tool | Description |
|---|---|
| `parse_ifc_elements_tool` | List MEP/HVAC elements — paginated (`offset`, `limit`), filterable by IFC type |
| `extract_ifc_properties_tool` | Property sets for one element — filter by `pset_names` to save tokens |
| `classify_ifc_element_tool` | Match an element to the best LVI-TUOTEOSA code with confidence scores |
| `validate_lvi_codes_tool` | Validate LVI codes — paginated, returns only invalid by default (`only_invalid=True`) |
| `generate_lvi_report_tool` | Summary: counts, code distribution, hierarchy; unclassified IDs capped to avoid token burn |
| `lookup_lvi_code_tool` | Search the codelist by code, Finnish term, or short name (no IFC needed) |
| `enrich_ifc_tool` | **Write LVI codes back into the IFC model** — creates/updates `LVI_Luokitus` property sets, returns enriched file |

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

## Codelist

The LVI-TUOTEOSA codelist (`data/codelist_LVI-TUOTEOSA_Versio_1_0.json`) is sourced from the Finnish national code registry (RYTJ / Suomi.fi koodistot).

Hierarchy:
- Level 1: `T-LVI-XX` — Main group (e.g. LAITTEISTOT - LVI)
- Level 2: `T-LVI-XX-XX` — Sub-group (e.g. LÄMMITYS- JA JÄÄHDYTYSLAITTEISTOT)
- Level 3: `T-LVI-XX-XX-XXX` — Product name (e.g. Lämmönjakokeskus, shortName: LJK)

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

---

## Enriching an IFC Model with LVI Codes

The `enrich_ifc_tool` writes LVI-TUOTEOSA codes directly into an IFC model's property sets.

### Workflow

The recommended approach is to classify first, then enrich:

```
1. generate_lvi_report_tool   → see which elements are unclassified
2. classify_ifc_element_tool  → get suggested code(s) for each element
3. enrich_ifc_tool            → write confirmed codes back into the model
```

### Example: save enriched file to disk

```json
{
  "tool": "enrich_ifc_tool",
  "arguments": {
    "ifc_path": "/path/to/model.ifc",
    "output_path": "/path/to/model_enriched.ifc",
    "assignments": [
      {"global_id": "0A1B2C3D4E5F6G7H8I9J0K", "lvi_code": "T-LVI-01-01-001"},
      {"global_id": "1B2C3D4E5F6G7H8I9J0K1L", "lvi_code": "T-LVI-02-03-005"}
    ]
  }
}
```

### Example: get result as base64 (no output_path)

```json
{
  "tool": "enrich_ifc_tool",
  "arguments": {
    "ifc_base64": "<base64-encoded IFC>",
    "assignments": [
      {"global_id": "0A1B2C3D4E5F6G7H8I9J0K", "lvi_code": "T-LVI-01-01-001"}
    ]
  }
}
```

### Response

```json
{
  "assigned_count": 2,
  "skipped_count": 0,
  "skipped_ids": [],
  "output_path": "/path/to/model_enriched.ifc",
  "ifc_base64": null
}
```

Elements are skipped if their `global_id` is not found or their `lvi_code` does not exist in the codelist. Skipped IDs are always reported so the AI can retry or flag them.
