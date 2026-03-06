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


class ValidationResult(BaseModel):
    global_id: str
    ifc_type: str
    name: str | None
    current_code: str | None
    is_valid: bool
    suggested_code: str | None
    suggested_label: str | None
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
