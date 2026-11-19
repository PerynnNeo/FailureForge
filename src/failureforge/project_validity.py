"""Interpret recorded project solver checks without changing the original evidence."""


def assessment_error(result):
    if not result:
        return None
    if (result.get("numerical_diagnostics") or {}).get("passed") is False:
        return "Solver numerical checks failed"
    if (result.get("summary") or {}).get("within_small_deflection_screen") is False:
        return "Beam deflection exceeded the model's small-deflection applicability limit"
    checks = (result.get("dynamics") or {}).get("reference_qualification", [])
    if any(check.get("passed") is not True for check in checks):
        return "Robot model or controller failed its reference qualification"
    return None
