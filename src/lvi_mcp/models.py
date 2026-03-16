"""Pydantic models for LVI MCP tool inputs and outputs."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, model_validator

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Shared input base
# ---------------------------------------------------------------------------

class IfcInputBase(BaseModel):
    """Base model for tools that require an IFC file (path or base64)."""

    ifc_path: str | None = None
    ifc_base64: str | None = None

    @model_validator(mode="after")
    def require_one_source(self) -> "IfcInputBase":
        if not self.ifc_path and not self.ifc_base64:
            raise ValueError("Either ifc_path or ifc_base64 must be provided.")
        return self


# ---------------------------------------------------------------------------
# Tool input models
# ---------------------------------------------------------------------------

class ParseIfcElementsInput(IfcInputBase):
    ifc_types: list[str] | None = None
    """IFC entity types to filter, e.g. ["IfcFlowTerminal"]. Defaults to MEP types."""

    offset: int = 0
    """Skip the first N elements (for pagination)."""

    limit: int = 50
    """Maximum number of elements to return (default 50)."""


class ExtractIfcPropertiesInput(IfcInputBase):
    global_id: str
    """GlobalId of the IFC element to inspect."""

    pset_names: list[str] | None = None
    """If provided, only return these property sets. Otherwise return all."""


class ClassifyIfcElementInput(IfcInputBase):
    global_id: str


class BatchClassifyInput(IfcInputBase):
    global_ids: list[str]
    """List of GlobalIds to classify in one call."""

    max_matches_per_element: int = 3
    """Maximum number of LVI code matches to return per element (default 3)."""


class ValidateLviCodesInput(IfcInputBase):
    property_set_name: str = "LVI_Luokitus"
    """Name of the property set that holds the LVI code."""

    property_name: str = "LVI_Tuoteosa"
    """Name of the property within the property set."""

    only_invalid: bool = True
    """If True (default), only return elements with missing or invalid codes."""

    offset: int = 0
    """Skip the first N results (for pagination)."""

    limit: int = 50
    """Maximum number of results to return (default 50)."""


class GenerateLviReportInput(IfcInputBase):
    property_set_name: str = "LVI_Luokitus"
    property_name: str = "LVI_Tuoteosa"
    max_unclassified_ids: int = 50
    """Maximum number of unclassified element IDs to include (default 50)."""


class LookupLviCodeInput(BaseModel):
    query: str
    """Code value (T-LVI-01-01-001) or Finnish term (lämmönjakokeskus)."""

    max_results: int = 10


class LviCodeAssignment(BaseModel):
    global_id: str
    """GlobalId of the IFC element to enrich."""

    lvi_code: str
    """LVI-TUOTEOSA code to assign (e.g. T-LVI-01-01-001)."""


class EnrichIfcInput(IfcInputBase):
    assignments: list[LviCodeAssignment]
    """List of GlobalId → LVI code pairs to write into the model."""

    property_set_name: str = "LVI_Luokitus"
    """Property set to write the code into (default: LVI_Luokitus)."""

    property_name: str = "LVI_Tuoteosa"
    """Property name within the set (default: LVI_Tuoteosa)."""

    output_path: str | None = None
    """Where to save the enriched IFC. If omitted and ifc_path was given, defaults to
    <original_stem>_enriched.ifc in the same directory. If ifc_base64 was used and
    output_path is omitted, the result is returned as base64."""

    dry_run: bool = False
    """If True, validate assignments and return what would be written without modifying
    any file. No output file is created."""

    backup: bool = True
    """If True (default) and output_path already exists, rename existing file to
    <output_path>.bak before writing."""


class AutoEnrichInput(IfcInputBase):
    property_set_name: str = "LVI_Luokitus"
    property_name: str = "LVI_Tuoteosa"

    min_score: float = 0.7
    """Minimum classification confidence score to auto-assign (0–5). Elements with
    a top score below this threshold are reported as needing manual review."""

    overwrite_existing: bool = False
    """If False (default), skip elements that already have a valid LVI code."""

    output_path: str | None = None
    """Where to save the enriched IFC. Follows the same defaulting logic as enrich_ifc_tool:
    auto-generates <stem>_enriched.ifc when ifc_path is given and output_path is omitted."""

    dry_run: bool = False
    """If True, return the proposed assignments without writing any file."""

    backup: bool = True
    """Rename existing output file to .bak before overwriting."""


# ---------------------------------------------------------------------------
# Tool output models
# ---------------------------------------------------------------------------

class PaginatedResponse(BaseModel, Generic[T]):
    """Wrapper for paginated tool responses to limit token usage."""
    total: int
    """Total number of items available (before pagination)."""
    offset: int
    limit: int
    items: list[Any]
    """The paginated slice of results."""


class IfcElementInfo(BaseModel):
    global_id: str
    ifc_type: str
    name: str | None
    description: str | None
    object_type: str | None


class PropertySetInfo(BaseModel):
    pset_name: str
    properties: dict[str, Any]


class ElementProperties(BaseModel):
    global_id: str
    ifc_type: str
    name: str | None
    property_sets: list[PropertySetInfo]


class LviMatch(BaseModel):
    code: str
    pref_label_fi: str
    short_name: str | None
    definition_fi: str | None
    level: int
    parent_code: str | None
    parent_label_fi: str | None
    score: float
    reasoning: str


class ClassificationResult(BaseModel):
    global_id: str
    ifc_type: str
    name: str | None
    matches: list[LviMatch]


class BatchClassificationResult(BaseModel):
    results: list[ClassificationResult]
    not_found_ids: list[str]
    """GlobalIds that were not found in the IFC model."""


class ValidationResult(BaseModel):
    global_id: str
    ifc_type: str
    name: str | None
    current_code: str | None
    is_valid: bool
    suggested_code: str | None
    suggested_label: str | None
    match_reasoning: str | None
    """Why the suggested code was proposed (e.g. which property triggered the match)."""
    message: str


class LviReport(BaseModel):
    total_elements: int
    classified_elements: int
    unclassified_elements: int
    invalid_code_elements: int
    code_distribution: dict[str, int]
    """Maps LVI code -> count of elements."""

    hierarchy_breakdown: dict[str, dict[str, int]]
    """Maps level-1 code -> {level-2 code -> count}."""

    unclassified_element_count: int
    """Total number of unclassified element IDs (may exceed the list below)."""

    unclassified_element_ids: list[str]
    """First N unclassified element IDs (capped by max_unclassified_ids)."""


class LviCodeEntry(BaseModel):
    code: str
    pref_label_fi: str
    short_name: str | None
    definition_fi: str | None
    level: int
    parent_code: str | None
    parent_label_fi: str | None
    grandparent_code: str | None
    grandparent_label_fi: str | None
    score: float


class EnrichIfcResult(BaseModel):
    assigned_count: int
    """Number of elements successfully updated (or would be updated if dry_run=True)."""

    skipped_count: int
    """Total number of skipped assignments."""

    skipped_not_found: list[str]
    """GlobalIds skipped because the element was not found in the IFC model."""

    skipped_invalid_code: list[str]
    """GlobalIds skipped because the lvi_code does not exist in the codelist."""

    output_path: str | None
    """Absolute path of the saved file, or None for dry_run / base64 output."""

    ifc_base64: str | None
    """Base64-encoded enriched IFC content when no output_path could be determined."""

    dry_run: bool
    """True if no file was actually modified."""


class AutoEnrichProposal(BaseModel):
    global_id: str
    ifc_type: str
    name: str | None
    proposed_code: str
    proposed_label: str
    short_name: str | None
    score: float
    reasoning: str


class AutoEnrichResult(BaseModel):
    total_unclassified: int
    """Number of elements that had no valid LVI code before enrichment."""

    auto_assigned_count: int
    """Elements assigned a code at or above min_score."""

    low_confidence_count: int
    """Elements where the best match scored below min_score — need manual review."""

    proposals: list[AutoEnrichProposal]
    """All assignments made (or proposed if dry_run=True)."""

    low_confidence_elements: list[AutoEnrichProposal]
    """Elements that need manual review (best score < min_score)."""

    output_path: str | None
    ifc_base64: str | None
    dry_run: bool
