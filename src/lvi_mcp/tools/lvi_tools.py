"""LVI classification, validation, reporting, and lookup tools."""

from __future__ import annotations

from lvi_mcp.codelist import CodeEntry, get_codelist
from lvi_mcp.ifc_parser import (
    get_element_info,
    get_lvi_code_from_element,
    get_property_sets,
    iter_mep_elements,
    load_ifc,
)
from lvi_mcp.models import (
    ClassificationResult,
    ClassifyIfcElementInput,
    GenerateLviReportInput,
    LookupLviCodeInput,
    LviCodeEntry,
    LviMatch,
    LviReport,
    PaginatedResponse,
    ValidateLviCodesInput,
    ValidationResult,
)


def _entry_to_lvi_match(entry: CodeEntry, score: float, reasoning: str) -> LviMatch:
    return LviMatch(
        code=entry.code,
        pref_label_fi=entry.pref_label_fi,
        short_name=entry.short_name,
        definition_fi=entry.definition_fi,
        level=entry.level,
        parent_code=entry.parent_code,
        parent_label_fi=entry.parent_label_fi,
        score=score,
        reasoning=reasoning,
    )


def _entry_to_code_entry(entry: CodeEntry, score: float = 0.0) -> LviCodeEntry:
    return LviCodeEntry(
        code=entry.code,
        pref_label_fi=entry.pref_label_fi,
        short_name=entry.short_name,
        definition_fi=entry.definition_fi,
        level=entry.level,
        parent_code=entry.parent_code,
        parent_label_fi=entry.parent_label_fi,
        grandparent_code=entry.grandparent_code,
        grandparent_label_fi=entry.grandparent_label_fi,
        score=score,
    )


def _collect_element_text_props(element: object) -> dict[str, str]:
    """Pull string values from all property sets for classification input."""
    props: dict[str, str] = {}
    for pset in get_property_sets(element):
        for k, v in pset["properties"].items():
            if isinstance(v, str):
                props[k] = v
    return props


# ---------------------------------------------------------------------------
# classify_ifc_element
# ---------------------------------------------------------------------------

def classify_ifc_element(params: ClassifyIfcElementInput) -> ClassificationResult:
    """Find the best matching LVI-TUOTEOSA code(s) for a single IFC element."""
    ifc_file = load_ifc(params.ifc_path, params.ifc_base64)

    try:
        element = ifc_file.by_guid(params.global_id)
    except Exception:
        element = None

    if element is None:
        raise ValueError(f"Element '{params.global_id}' not found.")

    info = get_element_info(element)
    extra_props = _collect_element_text_props(element)

    cl = get_codelist()
    raw_matches = cl.classify_from_text(
        name=info["name"],
        object_type=info["object_type"],
        description=info["description"],
        extra_props=extra_props,
    )

    matches = [_entry_to_lvi_match(e, s, r) for e, s, r in raw_matches]
    return ClassificationResult(
        global_id=info["global_id"],
        ifc_type=info["ifc_type"],
        name=info["name"],
        matches=matches,
    )


# ---------------------------------------------------------------------------
# validate_lvi_codes
# ---------------------------------------------------------------------------

def validate_lvi_codes(params: ValidateLviCodesInput) -> PaginatedResponse:
    """Validate LVI codes stored in a property set across all MEP elements.

    Returns paginated results, optionally filtered to only invalid entries.
    """
    ifc_file = load_ifc(params.ifc_path, params.ifc_base64)
    elements = iter_mep_elements(ifc_file)
    cl = get_codelist()
    all_results: list[ValidationResult] = []

    for element in elements:
        info = get_element_info(element)
        current_code = get_lvi_code_from_element(
            element, params.property_set_name, params.property_name
        )

        if current_code is None:
            all_results.append(
                ValidationResult(
                    global_id=info["global_id"],
                    ifc_type=info["ifc_type"],
                    name=info["name"],
                    current_code=None,
                    is_valid=False,
                    suggested_code=None,
                    suggested_label=None,
                    message="No LVI code found in property set.",
                )
            )
            continue

        entry = cl.get(current_code)
        if entry is not None:
            if not params.only_invalid:
                all_results.append(
                    ValidationResult(
                        global_id=info["global_id"],
                        ifc_type=info["ifc_type"],
                        name=info["name"],
                        current_code=current_code,
                        is_valid=True,
                        suggested_code=None,
                        suggested_label=None,
                        message=f"Valid: {entry.pref_label_fi}",
                    )
                )
        else:
            # Try to suggest a correction via classification
            extra_props = _collect_element_text_props(element)
            suggestions = cl.classify_from_text(
                name=info["name"],
                object_type=info["object_type"],
                description=info["description"],
                extra_props=extra_props,
                max_results=1,
            )
            suggested_code = suggestions[0][0].code if suggestions else None
            suggested_label = suggestions[0][0].pref_label_fi if suggestions else None
            all_results.append(
                ValidationResult(
                    global_id=info["global_id"],
                    ifc_type=info["ifc_type"],
                    name=info["name"],
                    current_code=current_code,
                    is_valid=False,
                    suggested_code=suggested_code,
                    suggested_label=suggested_label,
                    message=f"Unknown LVI code '{current_code}'.",
                )
            )

    total = len(all_results)
    page = all_results[params.offset : params.offset + params.limit]

    return PaginatedResponse(
        total=total,
        offset=params.offset,
        limit=params.limit,
        items=page,
    )


# ---------------------------------------------------------------------------
# generate_lvi_report
# ---------------------------------------------------------------------------

def generate_lvi_report(params: GenerateLviReportInput) -> LviReport:
    """Generate a summary report of LVI code usage across an IFC model."""
    ifc_file = load_ifc(params.ifc_path, params.ifc_base64)
    elements = iter_mep_elements(ifc_file)
    cl = get_codelist()

    total = len(elements)
    code_distribution: dict[str, int] = {}
    unclassified_ids: list[str] = []
    invalid_count = 0

    for element in elements:
        info = get_element_info(element)
        current_code = get_lvi_code_from_element(
            element, params.property_set_name, params.property_name
        )

        if current_code is None:
            unclassified_ids.append(info["global_id"])
            continue

        entry = cl.get(current_code)
        if entry is None:
            invalid_count += 1
            unclassified_ids.append(info["global_id"])
            continue

        code_distribution[current_code] = code_distribution.get(current_code, 0) + 1

    classified = total - len(unclassified_ids)

    # Build hierarchy breakdown: level-1 -> level-2 -> count
    hierarchy: dict[str, dict[str, int]] = {}
    for code, count in code_distribution.items():
        entry = cl.get(code)
        if entry is None:
            continue
        if entry.level == 3 and entry.parent_code and entry.grandparent_code:
            l1 = entry.grandparent_code
            l2 = entry.parent_code
        elif entry.level == 2 and entry.parent_code:
            l1 = entry.parent_code
            l2 = entry.code
        elif entry.level == 1:
            l1 = entry.code
            l2 = entry.code
        else:
            l1 = "unknown"
            l2 = "unknown"

        hierarchy.setdefault(l1, {})
        hierarchy[l1][l2] = hierarchy[l1].get(l2, 0) + count

    unclassified_total = len(unclassified_ids)
    capped_ids = unclassified_ids[: params.max_unclassified_ids]

    return LviReport(
        total_elements=total,
        classified_elements=classified,
        unclassified_elements=unclassified_total - invalid_count,
        invalid_code_elements=invalid_count,
        code_distribution=code_distribution,
        hierarchy_breakdown=hierarchy,
        unclassified_element_count=unclassified_total,
        unclassified_element_ids=capped_ids,
    )


# ---------------------------------------------------------------------------
# lookup_lvi_code
# ---------------------------------------------------------------------------

def lookup_lvi_code(params: LookupLviCodeInput) -> list[LviCodeEntry]:
    """Search the LVI-TUOTEOSA codelist by code value or Finnish term."""
    cl = get_codelist()
    results = cl.search(params.query, max_results=params.max_results)
    return [_entry_to_code_entry(entry, score) for entry, score in results]
