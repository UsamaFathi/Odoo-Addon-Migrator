from odoo_migrator.analysis.compat import Finding, Severity, deduplicate_findings


def test_specific_finding_replaces_generic_same_concern():
    generic = Finding(Severity.REVIEW_REQUIRED, "method.missing_target", "demo", "missing method", object_name="sale.order.action_confirm")
    specific = Finding(Severity.REVIEW_REQUIRED, "python.method.removed", "demo", "removed method", path="models/sale.py", rule_id="python.method.removed.14_to_15", object_name="sale.order.action_confirm", suggested_action="Review")
    result = deduplicate_findings([generic, specific])
    assert result == (specific,)
