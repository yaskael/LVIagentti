# Using LVI IFC MCP — End User Guide

This guide explains how to connect the LVI MCP server to different AI tools and how to submit IFC files for classification and verification.

---

## 1. Connect to an AI tool

The server must be running before you can use it. See [README.md](README.md) for setup steps.

### Claude Desktop

Claude Desktop has native MCP support. Once the server is configured in `claude_desktop_config.json` (see README), restart Claude Desktop and the tools appear automatically in every conversation — no extra steps needed.

**Config file locations:**
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

**Local Python install:**
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

**Docker:**
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

After saving the config, restart Claude Desktop. You will see a tools icon (hammer) in the chat input indicating the MCP server is connected.

---

### Cursor

Cursor supports MCP servers via its settings.

1. Open **Cursor Settings** > **MCP** (or edit `~/.cursor/mcp.json`)
2. Add the same config block as the Claude Desktop example above
3. Restart Cursor — the tools will be available to the AI assistant in chat

---

### MCP Inspector (browser-based testing tool)

MCP Inspector is useful for testing tools directly without an AI.

```bash
# Start the server in SSE mode
python -m lvi_mcp.server --transport sse --host 127.0.0.1 --port 8000

# Or with Docker Compose
docker compose --profile sse up
```

Open MCP Inspector in your browser, connect to `http://127.0.0.1:8000/sse`, and call tools directly with JSON inputs.

---

## 2. Provide an IFC file

All IFC tools accept the file in one of two ways.

### Option A — Local file path

If the server runs on the same machine as your IFC files, pass the absolute path:

```
ifc_path: /absolute/path/to/model.ifc
```

**With Docker, file access requires a volume mount.** The container filesystem is isolated — it cannot see files on your host machine unless you explicitly mount a folder at startup. There is no file upload endpoint; files must be pre-mounted before the container starts.

```bash
# 1. Place your IFC files in a folder on the host
mkdir ~/ifc_files
cp model.ifc ~/ifc_files/

# 2. Mount that folder when starting the container
docker run -i --rm \
  -v ~/ifc_files:/ifc_files:ro \
  lvi-mcp

# 3. Reference files using the container-side path (not your host path)
# Correct:   ifc_path: /ifc_files/model.ifc
# Wrong:     ifc_path: ~/ifc_files/model.ifc   (host path, invisible to container)
```

For Claude Desktop with Docker, use an absolute host path in the config:
```json
{
  "mcpServers": {
    "lvi-mcp": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "-v", "C:/Users/you/ifc_files:/ifc_files:ro", "lvi-mcp"]
    }
  }
}
```

If you add new IFC files to the mounted folder, they are immediately accessible without restarting the container. However, if you need to mount a different folder, you must restart with an updated `-v` flag.

### Option B — Base64-encoded content

> **File size warning:** Base64 is only suitable for small IFC files (under ~10 MB). Larger files cause problems at multiple levels:
> - The base64 string (~33% larger than the source file) must fit in the AI model's context window — 100 MB files are millions of tokens and will be rejected or truncated.
> - The full encoded string travels through the MCP stdio pipe, which is very slow for large payloads.
> - Decoding loads the full bytes into memory before writing to a temp file, so peak RAM usage is roughly 3× the file size.
>
> **For files over ~10 MB, always use `ifc_path` instead.**

If you cannot share a file path (e.g. the server has no access to your filesystem), encode the file as base64 and pass it as `ifc_base64`.

**Linux / macOS:**
```bash
base64 -i model.ifc | tr -d '\n'
```

**Windows (PowerShell):**
```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("C:\path\to\model.ifc"))
```

Paste the output string as the `ifc_base64` value in your tool call.

---

## 3. What to ask the AI

Once connected in Claude Desktop or Cursor, just describe what you want in plain language. The AI will call the right tools automatically.

### Look up a code or product name
```
What is LVI code T-LVI-01-01-001?
Search the LVI codelist for "pumppu"
What does the short name LJK mean?
```

### Classify a single element
```
Classify the element with GlobalId 2HjK... in /ifc_files/rakennus.ifc
What LVI product code best matches this element?
```

### Validate a whole model
```
Validate all LVI codes in /ifc_files/rakennus.ifc
Which elements have missing or invalid LVI codes?
```

### Generate a report
```
Give me a full LVI classification report for /ifc_files/rakennus.ifc
How many elements are classified vs unclassified?
Show the LVI code distribution by hierarchy group
```

### List elements
```
List all MEP elements in /ifc_files/rakennus.ifc
Show only IfcFlowTerminal elements from the model
```

---

## 4. Tool reference

| Tool | What it does | Requires IFC | Key options |
|---|---|---|---|
| `lookup_lvi_code_tool` | Search codelist by code, Finnish term, or short name | No | `max_results` (default 10) |
| `parse_ifc_elements_tool` | List MEP/HVAC elements — paginated | Yes | `offset`, `limit` (default 50), `ifc_types` |
| `extract_ifc_properties_tool` | Property sets for one element (by GlobalId) | Yes | `pset_names` — filter to specific sets |
| `classify_ifc_element_tool` | Suggest LVI codes with confidence scores | Yes | — |
| `validate_lvi_codes_tool` | Check LVI codes — only invalid by default, paginated | Yes | `only_invalid` (default true), `offset`, `limit` |
| `generate_lvi_report_tool` | Summary: counts, distribution, hierarchy | Yes | `max_unclassified_ids` (default 50) |

### Pagination

`parse_ifc_elements_tool` and `validate_lvi_codes_tool` return pages of results:

```json
{
  "total": 3200,
  "offset": 0,
  "limit": 50,
  "items": [ ... ]
}
```

The AI knows there are 3200 total and can ask for subsequent pages. You never need to request all results at once — ask for more only if needed.

### Property set defaults

Validation and reporting tools look for LVI codes here by default:

| Setting | Default value |
|---|---|
| Property set | `LVI_Luokitus` |
| Property name | `LVI_Tuoteosa` |

You can override these per request — just mention it in your prompt:
```
Validate LVI codes in model.ifc using property set "Pset_LVI" and property "Tuotekoodi"
```

### Large model behaviour

For models with thousands of elements, the AI will:
1. Start with `generate_lvi_report_tool` to get counts without loading all data
2. Use `validate_lvi_codes_tool` with `only_invalid=true` to focus on problems
3. Page through results with `offset` only if needed
4. Call `classify_ifc_element_tool` on specific elements, not the whole model

This keeps each tool call small and avoids burning tokens on data the AI doesn't need.

---

## 5. Example workflow — IFC verification

A typical session to check and fix an IFC model:

1. **Get a summary first**
   > "Generate a report for /ifc_files/rakennus.ifc"

   The AI returns totals: how many elements are classified, unclassified, or have invalid codes.

2. **Validate all codes**
   > "Validate LVI codes in /ifc_files/rakennus.ifc"

   Returns per-element results. Elements with invalid codes also get a suggested correct code.

3. **Investigate a specific element**
   > "Extract properties for element 2HjK... from /ifc_files/rakennus.ifc"

   Shows all property sets so you can see exactly what data is stored.

4. **Classify an untagged element**
   > "Classify element 3xPq... from /ifc_files/rakennus.ifc"

   Returns ranked LVI code matches with confidence scores and reasoning for each suggestion.

5. **Confirm a code meaning**
   > "What is T-LVI-02-03-005?"

   Returns the full Finnish label, short name, definition, and hierarchy position.
