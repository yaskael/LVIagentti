"""LVI classification, validation, reporting, lookup, and enrichment tools."""

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
    AutoEnrichInput,
    AutoEnrichProposal,
    AutoEnrichResult,
    BatchClassificationResult,
    BatchClassifyInput,
    ClassificationResult,
    ClassifyIfcElementInput,
    EnrichIfcInput,
    EnrichIfcResult,
    GenerateLviReportInput,
    LookupLviCodeInput,
    LviCodeAssignment,
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
# batch_classify_ifc_elements
# ---------------------------------------------------------------------------

def batch_classify_ifc_elements(params: BatchClassifyInput) -> BatchClassificationResult:
    """Classify multiple IFC elements in a single call."""
    ifc_file = load_ifc(params.ifc_path, params.ifc_base64)
    cl = get_codelist()

    results: list[ClassificationResult] = []
    not_found_ids: list[str] = []

    for global_id in params.global_ids:
        try:
            element = ifc_file.by_guid(global_id)
        except Exception:
            element = None

        if element is None:
            not_found_ids.append(global_id)
            continue

        info = get_element_info(element)
        extra_props = _collect_element_text_props(element)

        raw_matches = cl.classify_from_text(
            name=info["name"],
            object_type=info["object_type"],
            description=info["description"],
            extra_props=extra_props,
            max_results=params.max_matches_per_element,
        )

        matches = [_entry_to_lvi_match(e, s, r) for e, s, r in raw_matches]
        results.append(ClassificationResult(
            global_id=info["global_id"],
            ifc_type=info["ifc_type"],
            name=info["name"],
            matches=matches,
        ))

    return BatchClassificationResult(results=results, not_found_ids=not_found_ids)


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
                    match_reasoning=None,
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
                        match_reasoning=None,
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
            match_reasoning = suggestions[0][2] if suggestions else None
            all_results.append(
                ValidationResult(
                    global_id=info["global_id"],
                    ifc_type=info["ifc_type"],
                    name=info["name"],
                    current_code=current_code,
                    is_valid=False,
                    suggested_code=suggested_code,
                    suggested_label=suggested_label,
                    match_reasoning=match_reasoning,
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


# ---------------------------------------------------------------------------
# _resolve_output_path  (shared helper)
# ---------------------------------------------------------------------------

def _resolve_output_path(ifc_path: str | None, output_path: str | None) -> str | None:
    """Auto-generate <stem>_enriched.ifc when ifc_path is known and output_path is omitted."""
    if output_path is not None:
        return output_path
    if ifc_path:
        from pathlib import Path
        p = Path(ifc_path)
        return str(p.with_stem(p.stem + "_enriched"))
    return None


def _write_ifc(ifc_file: object, output_path: str | None, backup: bool) -> tuple[str | None, str | None]:
    """Write IFC to output_path (with optional backup) or encode as base64.

    Returns (output_path, ifc_base64).
    """
    import base64
    import os
    import tempfile

    if output_path:
        if backup and os.path.exists(output_path):
            os.rename(output_path, output_path + ".bak")
        ifc_file.write(output_path)  # type: ignore[attr-defined]
        return output_path, None

    with tempfile.NamedTemporaryFile(suffix=".ifc", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        ifc_file.write(tmp_path)  # type: ignore[attr-defined]
        with open(tmp_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return None, encoded


def _apply_lvi_assignment(
    ifc_file: object,
    element: object,
    lvi_code: str,
    pset_name: str,
    prop_name: str,
) -> None:
    """Create or update a property set entry on an IFC element."""
    import ifcopenshell  # type: ignore

    existing_pset = None
    for rel in getattr(element, "IsDefinedBy", []):
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        pdef = rel.RelatingPropertyDefinition
        if pdef.is_a("IfcPropertySet") and pdef.Name == pset_name:
            existing_pset = pdef
            break

    owner_histories = ifc_file.by_type("IfcOwnerHistory")  # type: ignore[attr-defined]
    owner_history = owner_histories[0] if owner_histories else None

    if existing_pset is not None:
        existing_prop = None
        for prop in existing_pset.HasProperties:
            if prop.Name == prop_name:
                existing_prop = prop
                break
        if existing_prop is not None:
            existing_prop.NominalValue = ifc_file.createIfcLabel(lvi_code)  # type: ignore[attr-defined]
        else:
            new_prop = ifc_file.createIfcPropertySingleValue(  # type: ignore[attr-defined]
                prop_name, None, ifc_file.createIfcLabel(lvi_code), None  # type: ignore[attr-defined]
            )
            existing_pset.HasProperties = list(existing_pset.HasProperties) + [new_prop]
    else:
        new_prop = ifc_file.createIfcPropertySingleValue(  # type: ignore[attr-defined]
            prop_name, None, ifc_file.createIfcLabel(lvi_code), None  # type: ignore[attr-defined]
        )
        new_pset = ifc_file.createIfcPropertySet(  # type: ignore[attr-defined]
            ifcopenshell.guid.new(), owner_history, pset_name, None, [new_prop]
        )
        ifc_file.createIfcRelDefinesByProperties(  # type: ignore[attr-defined]
            ifcopenshell.guid.new(), owner_history, None, None, [element], new_pset
        )


# ---------------------------------------------------------------------------
# enrich_ifc_with_lvi_codes
# ---------------------------------------------------------------------------

def enrich_ifc_with_lvi_codes(params: EnrichIfcInput) -> EnrichIfcResult:
    """Write LVI-TUOTEOSA codes into an IFC model's property sets."""
    ifc_file = load_ifc(params.ifc_path, params.ifc_base64)
    cl = get_codelist()

    assigned_count = 0
    skipped_not_found: list[str] = []
    skipped_invalid_code: list[str] = []

    for assignment in params.assignments:
        if cl.get(assignment.lvi_code) is None:
            skipped_invalid_code.append(assignment.global_id)
            continue

        try:
            element = ifc_file.by_guid(assignment.global_id)
        except Exception:
            element = None

        if element is None:
            skipped_not_found.append(assignment.global_id)
            continue

        if not params.dry_run:
            _apply_lvi_assignment(
                ifc_file, element, assignment.lvi_code,
                params.property_set_name, params.property_name,
            )
        assigned_count += 1

    if params.dry_run:
        return EnrichIfcResult(
            assigned_count=assigned_count,
            skipped_count=len(skipped_not_found) + len(skipped_invalid_code),
            skipped_not_found=skipped_not_found,
            skipped_invalid_code=skipped_invalid_code,
            output_path=None,
            ifc_base64=None,
            dry_run=True,
        )

    output_path = _resolve_output_path(params.ifc_path, params.output_path)
    out_path, ifc_b64 = _write_ifc(ifc_file, output_path, params.backup)

    return EnrichIfcResult(
        assigned_count=assigned_count,
        skipped_count=len(skipped_not_found) + len(skipped_invalid_code),
        skipped_not_found=skipped_not_found,
        skipped_invalid_code=skipped_invalid_code,
        output_path=out_path,
        ifc_base64=ifc_b64,
        dry_run=False,
    )


# ---------------------------------------------------------------------------
# auto_enrich_ifc
# ---------------------------------------------------------------------------

def auto_enrich_ifc(params: AutoEnrichInput) -> AutoEnrichResult:
    """Classify all unclassified MEP elements and enrich the model in one call."""
    ifc_file = load_ifc(params.ifc_path, params.ifc_base64)
    cl = get_codelist()
    elements = iter_mep_elements(ifc_file)

    proposals: list[AutoEnrichProposal] = []
    low_confidence: list[AutoEnrichProposal] = []
    total_unclassified = 0

    for element in elements:
        info = get_element_info(element)
        current_code = get_lvi_code_from_element(
            element, params.property_set_name, params.property_name
        )

        # Skip already classified elements unless overwrite_existing is set
        if current_code is not None and cl.get(current_code) is not None:
            if not params.overwrite_existing:
                continue

        total_unclassified += 1
        extra_props = _collect_element_text_props(element)
        matches = cl.classify_from_text(
            name=info["name"],
            object_type=info["object_type"],
            description=info["description"],
            extra_props=extra_props,
            max_results=1,
        )

        if not matches:
            low_confidence.append(AutoEnrichProposal(
                global_id=info["global_id"],
                ifc_type=info["ifc_type"],
                name=info["name"],
                proposed_code="",
                proposed_label="",
                short_name=None,
                score=0.0,
                reasoning="No match found in codelist.",
            ))
            continue

        top_entry, top_score, top_reasoning = matches[0]
        proposal = AutoEnrichProposal(
            global_id=info["global_id"],
            ifc_type=info["ifc_type"],
            name=info["name"],
            proposed_code=top_entry.code,
            proposed_label=top_entry.pref_label_fi,
            short_name=top_entry.short_name,
            score=top_score,
            reasoning=top_reasoning,
        )

        if top_score >= params.min_score:
            proposals.append(proposal)
            if not params.dry_run:
                _apply_lvi_assignment(
                    ifc_file, element, top_entry.code,
                    params.property_set_name, params.property_name,
                )
        else:
            low_confidence.append(proposal)

    if params.dry_run or not proposals:
        return AutoEnrichResult(
            total_unclassified=total_unclassified,
            auto_assigned_count=len(proposals),
            low_confidence_count=len(low_confidence),
            proposals=proposals,
            low_confidence_elements=low_confidence,
            output_path=None,
            ifc_base64=None,
            dry_run=True,
        )

    output_path = _resolve_output_path(params.ifc_path, params.output_path)
    out_path, ifc_b64 = _write_ifc(ifc_file, output_path, params.backup)

    return AutoEnrichResult(
        total_unclassified=total_unclassified,
        auto_assigned_count=len(proposals),
        low_confidence_count=len(low_confidence),
        proposals=proposals,
        low_confidence_elements=low_confidence,
        output_path=out_path,
        ifc_base64=ifc_b64,
        dry_run=False,
    )
