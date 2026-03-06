# Progress Log

## Session — 2026-03-06

### Documentation
- Created `README.md` with full project overview, Getting Started (Python + Docker), Quick Verification, Codelist, IFC Input, and LVI Property Set Convention sections
- Created `INSTRUCTIONS.md` — end-user guide covering: connecting to Claude Desktop / Cursor / MCP Inspector, providing IFC files (path vs base64), example prompts, tool reference, and a step-by-step IFC verification workflow
- Added SSE transport CLI args (`--transport`, `--host`, `--port`) to README
- Added `max_results` parameter to lookup quick verification example

### Docker hardening (`Dockerfile`, `docker-compose.yml`)
- Added `PYTHONUNBUFFERED=1` — prevents Python stdout buffering that can block MCP stdio transport
- Added `VOLUME /tmp` — ensures writable temp storage for base64 decoding when container runs `--read-only`
- Set `mem_limit: 4g` + `memswap_limit: 4g` on both services — IfcOpenShell loads full models into RAM (5–10× file size); without limits the OOM killer silently kills the container
- Added `restart: on-failure` on both services
- Added `healthcheck` on SSE service (polls `http://localhost:8000/sse` every 30s)
- Documented Docker volume mount requirement in INSTRUCTIONS.md (host path isolation, correct vs wrong path examples)

### Large file / token efficiency (`models.py`, `ifc_tools.py`, `lvi_tools.py`, `server.py`)

**Problem:** Large IFC models (10K+ elements) would dump megabytes of JSON into the AI context window, burning tokens rapidly.

**Changes:**
- Added `PaginatedResponse` model (`total`, `offset`, `limit`, `items`)
- `parse_ifc_elements_tool` — added `offset=0`, `limit=50`; returns `PaginatedResponse`
- `validate_lvi_codes_tool` — added `only_invalid=True` (skips valid elements by default), `offset=0`, `limit=50`; returns `PaginatedResponse`
- `extract_ifc_properties_tool` — added `pset_names: list[str] | None`; filters property sets server-side
- `generate_lvi_report_tool` — added `max_unclassified_ids=50`; report now includes `unclassified_element_count` (full total) + capped ID list
- `GenerateLviReportInput`, `ParseIfcElementsInput`, `ValidateLviCodesInput`, `ExtractIfcPropertiesInput` all updated with new fields

**Token savings on a 10K element model (typical):**
| Tool | Before | After (defaults) |
|---|---|---|
| `parse_ifc_elements_tool` | ~375K tokens | ~1.9K tokens |
| `validate_lvi_codes_tool` | ~500K tokens | ~1.9K tokens |
| `generate_lvi_report_tool` | ~100K tokens (8K GUIDs) | ~3K tokens |

### CLAUDE.md
- Added Token Efficiency design principle section
- Documents pagination convention, server-side filtering, recommended tool call order, and rules for new tools

### Base64 file size warning
- Documented in INSTRUCTIONS.md: base64 only suitable for files under ~10 MB
- Reasons: AI context window can't hold 100MB+ base64, MCP stdio pipe is slow for large payloads, peak RAM is ~3× file size
- Recommendation: always use `ifc_path` for real building models

---

## Known limitations / future work
- IfcOpenShell has no streaming — always loads full model into memory; no workaround at application level
- No HTTP file upload endpoint — files must be pre-mounted via Docker volume for Docker deployments
- `validate_lvi_codes_tool` still iterates all elements before paginating (server-side work is bounded but not lazy)
