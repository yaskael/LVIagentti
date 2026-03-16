# LVI IFC MCP — Process & Workflow Descriptions

This document describes every workflow, data flow, and internal mechanism in the LVI MCP server. It is designed as input for generating diagrams, flowcharts, and architecture visuals.

---

## 1. System Architecture Overview

**Diagram type:** Component / block diagram

### Components

```
┌─────────────────────────────────────────────────────────────┐
│  AI Client (Claude Desktop / MCP Inspector / Custom)        │
│  Sends tool calls via MCP protocol (stdio or SSE)           │
└─────────────────┬───────────────────────────────────────────┘
                  │ MCP Protocol (JSON-RPC)
                  ▼
┌─────────────────────────────────────────────────────────────┐
│  server.py — FastMCP Instance                               │
│  9 registered @mcp.tool() functions                         │
│  Validates input → delegates to business logic → returns JSON│
└──────┬──────────┬──────────────────────────┬────────────────┘
       │          │                          │
       ▼          ▼                          ▼
┌────────────┐ ┌───────────────┐  ┌───────────────────────┐
│ ifc_parser │ │  codelist.py  │  │      models.py        │
│            │ │               │  │                       │
│ load_ifc() │ │ LviCodelist   │  │ Pydantic input/output │
│ write_ifc()│ │ (singleton)   │  │ validation models     │
│ IFC Cache  │ │ classify_     │  │                       │
│ resolve_   │ │  from_text()  │  │                       │
│  output()  │ │ search()      │  │                       │
└─────┬──────┘ └───────┬───────┘  └───────────────────────┘
      │                │
      ▼                ▼
┌────────────┐ ┌───────────────┐
│ .ifc files │ │ codelist JSON │
│ (on disk   │ │ (bundled in   │
│  or base64)│ │  data/ dir)   │
└────────────┘ └───────────────┘
```

### Key relationships
- `server.py` is the only MCP-facing module; it converts flat tool arguments into Pydantic models
- `tools/ifc_tools.py` handles IFC parsing tools (parse, extract)
- `tools/lvi_tools.py` handles all LVI business logic (classify, validate, report, enrich)
- Both tool modules import from `ifc_parser.py` (file I/O) and `codelist.py` (classification)
- `models.py` defines all input/output contracts (shared across server + tools)

---

## 2. IFC File Cache

**Diagram type:** State / sequence diagram

### How the cache works

```
Tool call arrives with ifc_path="/model.ifc"
        │
        ▼
┌─ _IfcCache.get("/model.ifc") ──────────────────────────┐
│                                                          │
│  Compute absolute path + read file mtime                 │
│        │                                                 │
│        ▼                                                 │
│  ┌─ Cache hit? (path exists AND mtime matches) ─┐       │
│  │                                                │       │
│  │ YES: return cached ifcopenshell.file           │       │
│  │       move entry to end of LRU order           │       │
│  │                                                │       │
│  │ NO:  return None → caller runs                 │       │
│  │       ifcopenshell.open(path)                  │       │
│  │       then calls _IfcCache.put(path, ifc_file) │       │
│  │       (evicts oldest if at max capacity of 4)  │       │
│  └────────────────────────────────────────────────┘       │
└──────────────────────────────────────────────────────────┘
```

### Cache invalidation

```
write_ifc(ifc_file, output_path, backup=True)
        │
        ▼
  Backup existing file → write new file
        │
        ▼
  _IfcCache.invalidate(output_path)
  (removes entry so next load_ifc reads fresh from disk)
```

### Cache lifecycle across a typical session

```
Call 1: generate_lvi_report_tool(ifc_path="model.ifc")
        → Cache MISS → parse file → cache it (1 entry)

Call 2: validate_lvi_codes_tool(ifc_path="model.ifc")
        → Cache HIT (same path, same mtime) → no re-parse

Call 3: auto_enrich_ifc_tool(ifc_path="model.ifc")
        → Cache HIT for read
        → write_ifc("model_enriched.ifc") → invalidate "model_enriched.ifc"

Call 4: enrich_ifc_tool(ifc_path="model.ifc")
        → _load_for_enrichment detects model_enriched.ifc exists
        → load_ifc("model_enriched.ifc") → Cache MISS → parse & cache (2 entries)
        → write_ifc("model_enriched.ifc") → invalidate
```

---

## 3. Enrichment Chaining Mechanism

**Diagram type:** Sequence diagram

### Problem it solves

```
WITHOUT chaining:
  auto_enrich(model.ifc) → writes model_enriched.ifc (118 codes assigned)
  enrich(model.ifc, manual assignments) → reloads model.ifc (ORIGINAL!)
                                        → writes model_enriched.ifc
                                        → OVERWRITES the 118 auto-assigned codes!

WITH chaining:
  auto_enrich(model.ifc) → writes model_enriched.ifc (118 codes assigned)
  enrich(model.ifc, manual assignments) → detects model_enriched.ifc exists
                                        → loads model_enriched.ifc instead
                                        → writes model_enriched.ifc
                                        → All 118 + manual assignments preserved!
```

### Decision logic in `_load_for_enrichment()`

```
_load_for_enrichment(ifc_path, ifc_base64, output_path)
        │
        ▼
  resolved = resolve_output_path(ifc_path, output_path)
        │
        ▼
  ┌─ Is resolved path different from ifc_path? ──┐
  │                                                │
  │ YES ──► ┌─ Does resolved path exist on disk? ──┐
  │         │                                       │
  │         │ YES: load_ifc(resolved, None)         │
  │         │      "Chain from previous enrichment" │
  │         │                                       │
  │         │ NO:  load_ifc(ifc_path, ifc_base64)   │
  │         │      "First enrichment, use original"  │
  │         └───────────────────────────────────────┘
  │                                                │
  │ NO (or resolved is None):                      │
  │    load_ifc(ifc_path, ifc_base64)              │
  │    "Use original"                              │
  └────────────────────────────────────────────────┘
```

---

## 4. Workflow A — Automatic Enrichment

**Diagram type:** Flowchart (swimlane: AI client | MCP server)

### Steps

```
AI Client                              MCP Server
─────────                              ──────────
    │
    │  1. generate_lvi_report_tool
    │     (ifc_path="model.ifc")
    ├─────────────────────────────────────►│
    │                                      │ load_ifc → cache
    │                                      │ iter_mep_elements
    │                                      │ count classified/unclassified
    │◄─────────────────────────────────────┤ return LviReport
    │  {total: 500, unclassified: 142}     │
    │                                      │
    │  2. auto_enrich_ifc_tool             │
    │     (dry_run=True, min_score=0.7)    │
    ├─────────────────────────────────────►│
    │                                      │ load_ifc → cache HIT
    │                                      │ for each unclassified element:
    │                                      │   classify_from_text()
    │                                      │   → score >= 0.7? → proposal
    │                                      │   → score < 0.7? → low_confidence
    │◄─────────────────────────────────────┤ return AutoEnrichResult
    │  {auto_assigned: 118,                │   (dry_run=True, no file written)
    │   low_confidence: 24,                │
    │   proposals: [...],                  │
    │   low_confidence_elements: [...]}    │
    │                                      │
    │  AI reviews proposals, decides to    │
    │  proceed...                          │
    │                                      │
    │  3. auto_enrich_ifc_tool             │
    │     (dry_run=False, min_score=0.7)   │
    ├─────────────────────────────────────►│
    │                                      │ load_ifc → cache HIT
    │                                      │ classify + write property sets
    │                                      │ resolve_output_path → "model_enriched.ifc"
    │                                      │ backup existing? → rename to .bak
    │                                      │ write_ifc → invalidate cache
    │◄─────────────────────────────────────┤ return AutoEnrichResult
    │  {output_path: "model_enriched.ifc", │   (dry_run=False)
    │   auto_assigned: 118,                │
    │   low_confidence_elements: [...]}    │
    │                                      │
    │  AI picks codes for low_confidence   │
    │  elements manually...                │
    │                                      │
    │  4. enrich_ifc_tool                  │
    │     (assignments=[...24 manual...])  │
    ├─────────────────────────────────────►│
    │                                      │ _load_for_enrichment:
    │                                      │   model_enriched.ifc exists!
    │                                      │   → load from enriched file (CHAINING)
    │                                      │ apply 24 manual assignments
    │                                      │ write_ifc → model_enriched.ifc
    │◄─────────────────────────────────────┤ return EnrichIfcResult
    │  {assigned: 24, dry_run: false}      │   (all 118+24 = 142 codes preserved)
    │                                      │
    │  5. validate_lvi_codes_tool          │
    │     (final verification)             │
    ├─────────────────────────────────────►│
    │                                      │ load enriched file → verify all codes
    │◄─────────────────────────────────────┤ return PaginatedResponse
    │  {total: 0 invalid} ✓               │
```

---

## 5. Workflow B — Manual Enrichment

**Diagram type:** Flowchart (swimlane: AI client | MCP server)

### Steps

```
AI Client                              MCP Server
─────────                              ──────────
    │
    │  1. generate_lvi_report_tool
    ├─────────────────────────────────────►│
    │◄─────────────────────────────────────┤ LviReport
    │  "142 elements need codes"           │
    │                                      │
    │  2. validate_lvi_codes_tool          │
    │     (only_invalid=True, limit=50)    │
    ├─────────────────────────────────────►│
    │                                      │ For each invalid element:
    │                                      │   classify_from_text → suggestion
    │◄─────────────────────────────────────┤ PaginatedResponse
    │  Each item has:                      │
    │   - current_code (or null)           │
    │   - suggested_code                   │
    │   - suggested_label                  │
    │   - match_reasoning                  │
    │                                      │
    │  AI reviews suggestions, wants       │
    │  deeper analysis for some...         │
    │                                      │
    │  3. batch_classify_tool              │
    │     (global_ids=[...ambiguous...])   │
    ├─────────────────────────────────────►│
    │                                      │ For each element:
    │                                      │   get name, type, description
    │                                      │   get all property set text values
    │                                      │   classify_from_text(max_results=3)
    │◄─────────────────────────────────────┤ BatchClassificationResult
    │  Multiple matches per element        │
    │  with scores + reasoning             │
    │                                      │
    │  Need even more detail on one?       │
    │                                      │
    │  4. extract_ifc_properties_tool      │
    │     (global_id="X", pset_names=[...])│
    ├─────────────────────────────────────►│
    │◄─────────────────────────────────────┤ ElementProperties
    │  Full property set dump              │
    │                                      │
    │  AI decides on all assignments...    │
    │                                      │
    │  5. enrich_ifc_tool                  │
    │     (dry_run=True, assignments=[...])│
    ├─────────────────────────────────────►│
    │◄─────────────────────────────────────┤ EnrichIfcResult (dry_run=True)
    │  "Would assign 42, skip 0"           │
    │                                      │
    │  6. enrich_ifc_tool                  │
    │     (dry_run=False, assignments=[...])│
    ├─────────────────────────────────────►│
    │                                      │ Write property sets
    │                                      │ write_ifc → model_enriched.ifc
    │◄─────────────────────────────────────┤ EnrichIfcResult
    │  {assigned: 42, output_path: "..."}  │
    │                                      │
    │  (Repeat steps 2-6 for next page     │
    │   of 50 elements if total > 50)      │
```

---

## 6. Workflow C — Hybrid (Auto + Manual Cleanup)

**Diagram type:** Flowchart showing how exclude_global_ids prevents duplicate work

### Steps

```
AI Client                              MCP Server
─────────                              ──────────
    │
    │  1. generate_lvi_report_tool
    ├─────────────────────────────────────►│
    │◄─────────────────────────────────────┤ LviReport
    │                                      │
    │  2. validate_lvi_codes_tool
    │     (only_invalid=True)
    ├─────────────────────────────────────►│
    │                                      │ classify_from_text for each invalid
    │◄─────────────────────────────────────┤ PaginatedResponse with suggestions
    │                                      │
    │  AI collects validated_ids from      │
    │  the results it already reviewed     │
    │  (e.g. IDs where it accepted the     │
    │   suggestion or decided "no code")   │
    │                                      │
    │  3. auto_enrich_ifc_tool             │
    │     (exclude_global_ids=             │
    │       [validated_ids...])            │
    ├─────────────────────────────────────►│
    │                                      │ Skip excluded IDs entirely
    │                                      │   → no redundant classify_from_text!
    │                                      │ Classify remaining unclassified only
    │                                      │ Write high-confidence codes
    │◄─────────────────────────────────────┤ AutoEnrichResult
    │                                      │
    │  4. enrich_ifc_tool                  │
    │     (assignments from validate       │
    │      suggestions + manual picks)     │
    ├─────────────────────────────────────►│
    │                                      │ _load_for_enrichment → CHAIN
    │                                      │ Apply manual assignments on top
    │◄─────────────────────────────────────┤ EnrichIfcResult
    │                                      │
    │  5. validate_lvi_codes_tool          │
    │     (final check)                    │
    ├─────────────────────────────────────►│
    │◄─────────────────────────────────────┤ All valid ✓
```

---

## 7. Classification Engine — `classify_from_text()`

**Diagram type:** Scoring flowchart / decision tree

### Input assembly

```
IFC Element
    │
    ├── Name ─────────────────────┐
    ├── ObjectType ───────────────┤
    ├── Description ──────────────┤ concatenate + normalize
    └── All PropertySet values ───┤ (lowercase, strip accents)
         (string values only)     │
                                  ▼
                          candidates_text (normalized)
```

### Scoring algorithm (for each level-3 codelist entry)

```
candidates_text vs. CodeEntry
        │
        ├──► shortName match?
        │    e.g. "LJK" found in candidates_text
        │    → +3.0 points
        │
        ├──► prefLabel full match?
        │    all words (>3 chars) of "Lämmönjakokeskus" found
        │    → +2.0 points
        │
        ├──► prefLabel partial match?
        │    some words match → ratio × 1.5 points
        │
        └──► definition keyword match?
             words (>4 chars) from definition_fi found
             → +0.3 per matching word

Final score = sum of all matching tiers
Results sorted by score descending, top N returned
```

### Score interpretation

```
Score range     Meaning
──────────      ───────
4.0+            Excellent — shortName + label match (near certain)
2.0 – 3.9      Good — strong label or shortName match
0.7 – 1.9      Moderate — partial matches, likely correct
0.3 – 0.6      Low — only definition keywords matched
0.0             No match found

auto_enrich default threshold: min_score = 0.7
  → scores >= 0.7 are auto-assigned
  → scores < 0.7 go to low_confidence_elements
```

---

## 8. Validation Flow — `validate_lvi_codes()`

**Diagram type:** Decision tree per element

```
For each MEP element:
        │
        ▼
  Read property set LVI_Luokitus.LVI_Tuoteosa
        │
        ▼
  ┌─ Code present? ───────────────────────────┐
  │                                            │
  │ NO:  → ValidationResult                   │
  │        is_valid=False                      │
  │        message="No LVI code found"         │
  │        suggested_code=None                 │
  │                                            │
  │ YES: → Look up code in codelist            │
  │        │                                   │
  │        ▼                                   │
  │   ┌─ Code exists in codelist? ──────────┐ │
  │   │                                      │ │
  │   │ YES: → ValidationResult              │ │
  │   │        is_valid=True                 │ │
  │   │        (only included if             │ │
  │   │         only_invalid=False)          │ │
  │   │                                      │ │
  │   │ NO:  → classify_from_text()          │ │
  │   │        get best suggestion           │ │
  │   │        → ValidationResult            │ │
  │   │          is_valid=False              │ │
  │   │          suggested_code="T-LVI-..."  │ │
  │   │          match_reasoning="..."       │ │
  │   │          message="Unknown code"      │ │
  │   └──────────────────────────────────────┘ │
  └────────────────────────────────────────────┘

Results are paginated: return items[offset : offset+limit]
```

---

## 9. Report Generation — `generate_lvi_report()`

**Diagram type:** Data aggregation flow

```
IFC File
    │
    ▼
iter_mep_elements()  →  all MEP elements
    │
    ▼
For each element:
    ├── get LVI code from property set
    │
    ├── Code is None?      → count as "unclassified"
    ├── Code not in codelist? → count as "invalid_code"
    └── Code is valid?     → add to code_distribution{code: count}
                           → add to hierarchy_breakdown{L1: {L2: count}}

    │
    ▼
LviReport
    ├── total_elements: 500
    ├── classified_elements: 358
    ├── unclassified_elements: 135     (no code at all)
    ├── invalid_code_elements: 7       (code present but not in codelist)
    ├── code_distribution:
    │     {"T-LVI-01-01-001": 45, "T-LVI-02-03-005": 23, ...}
    ├── hierarchy_breakdown:
    │     {"T-LVI-01": {"T-LVI-01-01": 120, "T-LVI-01-02": 50}, ...}
    ├── unclassified_element_count: 142  (full count)
    └── unclassified_element_ids: [first 50 IDs]  (capped)
```

---

## 10. Enrich Write-Back — `_apply_lvi_assignment()`

**Diagram type:** Decision tree for property set manipulation

```
_apply_lvi_assignment(ifc_file, element, "T-LVI-01-01-001", "LVI_Luokitus", "LVI_Tuoteosa")
        │
        ▼
  Search element's IsDefinedBy relations
  for IfcPropertySet with Name="LVI_Luokitus"
        │
        ▼
  ┌─ Property set exists? ───────────────────────────────────┐
  │                                                           │
  │ YES: ┌─ Property "LVI_Tuoteosa" exists in the set? ────┐ │
  │      │                                                   │ │
  │      │ YES: Update NominalValue to IfcLabel("T-LVI-..") │ │
  │      │                                                   │ │
  │      │ NO:  Create new IfcPropertySingleValue            │ │
  │      │      Append to HasProperties list                 │ │
  │      └───────────────────────────────────────────────────┘ │
  │                                                           │
  │ NO:  Create new IfcPropertySingleValue                    │
  │      Create new IfcPropertySet("LVI_Luokitus")            │
  │      Create new IfcRelDefinesByProperties                 │
  │      linking element ↔ property set                       │
  └───────────────────────────────────────────────────────────┘
```

---

## 11. Output Path Resolution & Backup

**Diagram type:** Decision flowchart

```
resolve_output_path(ifc_path, output_path)
        │
        ▼
  ┌─ output_path provided? ──────────────────┐
  │                                           │
  │ YES: return output_path as-is             │
  │                                           │
  │ NO:  ┌─ ifc_path provided? ────────────┐ │
  │      │                                  │ │
  │      │ YES: return "<stem>_enriched.ifc"│ │
  │      │      in same directory           │ │
  │      │                                  │ │
  │      │ NO:  return None                 │ │
  │      │      (base64 output mode)        │ │
  │      └──────────────────────────────────┘ │
  └───────────────────────────────────────────┘

write_ifc(ifc_file, resolved_path, backup)
        │
        ▼
  ┌─ resolved_path is not None? ──────────────┐
  │                                            │
  │ YES: ┌─ backup=True AND file exists? ────┐ │
  │      │                                    │ │
  │      │ YES: rename to "<path>.bak"        │ │
  │      │ NO:  skip                          │ │
  │      └────────────────────────────────────┘ │
  │      Write ifc_file to resolved_path        │
  │      Invalidate cache for resolved_path     │
  │      return (path, None)                    │
  │                                            │
  │ NO:  Write to temp file                    │
  │      Read temp → base64 encode             │
  │      Delete temp                           │
  │      return (None, base64_string)          │
  └────────────────────────────────────────────┘
```

---

## 12. Codelist Hierarchy

**Diagram type:** Tree / hierarchy diagram

```
LVI-TUOTEOSA Codelist (3-level hierarchy)
│
├── T-LVI-01  LAITTEISTOT - LVI
│   ├── T-LVI-01-01  LÄMMITYS- JA JÄÄHDYTYSLAITTEISTOT
│   │   ├── T-LVI-01-01-001  Lämmönjakokeskus (LJK)
│   │   ├── T-LVI-01-01-002  Kaukolämpöpaketti (KLP)
│   │   ├── T-LVI-01-01-003  Lämpöpumppu (LP)
│   │   └── ...
│   ├── T-LVI-01-02  ILMANVAIHTOLAITTEISTOT
│   │   ├── T-LVI-01-02-001  Ilmanvaihtokone (IVK)
│   │   └── ...
│   └── ...
│
├── T-LVI-02  PUTKISTOT
│   ├── T-LVI-02-01  LÄMMITYSPUTKISTOT
│   │   └── ...
│   ├── T-LVI-02-02  JÄÄHDYTYSPUTKISTOT
│   │   └── ...
│   └── ...
│
├── T-LVI-03  KANAVISTOT
│   └── ...
│
├── T-LVI-04  ERISTYKSET
│   └── ...
│
└── ... (more level-1 groups)

Level 1: T-LVI-XX          → Main group (grouping only, not assignable)
Level 2: T-LVI-XX-XX       → Sub-group (grouping only, not assignable)
Level 3: T-LVI-XX-XX-XXX   → Product code (assignable to IFC elements)
                               has shortName (e.g. "LJK") + prefLabel + definition
```

---

## 13. Data Model — Key Pydantic Models

**Diagram type:** ER diagram / class diagram

### Input models

```
IfcInputBase (abstract)
├── ifc_path: str | None
└── ifc_base64: str | None
    [validator: exactly one must be provided]

ParseIfcElementsInput(IfcInputBase)
├── ifc_types: list[str] | None
├── offset: int = 0
└── limit: int = 50

ClassifyIfcElementInput(IfcInputBase)
└── global_id: str

BatchClassifyInput(IfcInputBase)
├── global_ids: list[str]
└── max_matches_per_element: int = 3

ValidateLviCodesInput(IfcInputBase)
├── property_set_name: str = "LVI_Luokitus"
├── property_name: str = "LVI_Tuoteosa"
├── only_invalid: bool = True
├── offset: int = 0
└── limit: int = 50

EnrichIfcInput(IfcInputBase)
├── assignments: list[LviCodeAssignment]
├── property_set_name / property_name
├── output_path: str | None
├── dry_run: bool = False
└── backup: bool = True

AutoEnrichInput(IfcInputBase)
├── property_set_name / property_name
├── min_score: float = 0.7
├── overwrite_existing: bool = False
├── exclude_global_ids: list[str] | None
├── output_path: str | None
├── dry_run: bool = False
└── backup: bool = True
```

### Output models

```
PaginatedResponse[T]
├── total: int
├── offset: int
├── limit: int
└── items: list[T]

ClassificationResult
├── global_id, ifc_type, name
└── matches: list[LviMatch]
        ├── code, pref_label_fi, short_name
        ├── score: float
        └── reasoning: str

ValidationResult
├── global_id, ifc_type, name
├── current_code: str | None
├── is_valid: bool
├── suggested_code / suggested_label
├── match_reasoning: str | None
└── message: str

EnrichIfcResult
├── assigned_count: int
├── skipped_count: int
├── skipped_not_found: list[str]
├── skipped_invalid_code: list[str]
├── output_path / ifc_base64
└── dry_run: bool

AutoEnrichResult
├── total_unclassified: int
├── auto_assigned_count: int
├── low_confidence_count: int
├── proposals: list[AutoEnrichProposal]
├── low_confidence_elements: list[AutoEnrichProposal]
├── output_path / ifc_base64
└── dry_run: bool

LviReport
├── total_elements / classified / unclassified / invalid
├── code_distribution: {code: count}
├── hierarchy_breakdown: {L1: {L2: count}}
├── unclassified_element_count: int
└── unclassified_element_ids: list[str] (capped)
```

---

## 14. MCP Protocol Transport

**Diagram type:** Deployment / network diagram

```
┌──────────────────────┐     stdio (pipes)     ┌──────────────────┐
│  Claude Desktop      │◄─────────────────────►│  lvi-mcp server  │
│  (MCP client)        │     JSON-RPC           │  (Python process)│
└──────────────────────┘                        └──────────────────┘

           OR

┌──────────────────────┐     HTTP/SSE           ┌──────────────────┐
│  MCP Inspector       │◄─────────────────────►│  lvi-mcp server  │
│  (browser)           │  localhost:8000/sse    │  (uvicorn)       │
└──────────────────────┘                        └──────────────────┘

           OR

┌──────────────────────┐     stdio (pipes)     ┌───────────────────┐
│  Claude Desktop      │◄────────────────────►│  Docker container  │
│  (MCP client)        │     docker run -i     │  lvi-mcp          │
└──────────────────────┘                       │  /ifc_files mount │
                                               └───────────────────┘
```

---

## Summary of Diagram Suggestions

| # | Section | Recommended diagram type |
|---|---------|--------------------------|
| 1 | System Architecture | Component / block diagram |
| 2 | IFC File Cache | State diagram or sequence |
| 3 | Enrichment Chaining | Sequence diagram (before/after) |
| 4 | Workflow A — Automatic | Swimlane flowchart |
| 5 | Workflow B — Manual | Swimlane flowchart |
| 6 | Workflow C — Hybrid | Swimlane flowchart with highlight on exclude_global_ids |
| 7 | Classification Engine | Scoring decision tree |
| 8 | Validation Flow | Per-element decision tree |
| 9 | Report Generation | Data aggregation flow |
| 10 | Enrich Write-Back | IFC property set manipulation decision tree |
| 11 | Output Path & Backup | Decision flowchart |
| 12 | Codelist Hierarchy | Tree diagram |
| 13 | Data Models | ER / class diagram |
| 14 | MCP Transport | Deployment / network diagram |
