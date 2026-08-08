"""Role → permitted actions. Enforced in the engine, reflected in the UI.

The separation rules the spec names (spec §4) are the point, not the list:

- the development worker cannot approve its own output,
- the independent reviewer cannot modify development results,
- only the Business Owner signs the plan,
- only the Release Manager approves release.

`require` raises rather than returns so a missing check is loud.
"""

from __future__ import annotations

from s7_delivery.factory.models import Role


class PermissionError_(Exception):
    """Named with a trailing underscore to avoid shadowing the builtin."""


# Action names are the engine's method names — one vocabulary end to end.
PERMISSIONS: dict[str, set[Role]] = {
    # intake
    "edit_requirement": {Role.BUSINESS_OWNER, Role.PRODUCT_ANALYST},
    "run_intake_analysis": {Role.PRODUCT_ANALYST, Role.DELIVERY_LEAD},
    "create_epic": {Role.PRODUCT_ANALYST, Role.DELIVERY_LEAD},
    "pass_intake_gate": {Role.DELIVERY_LEAD, Role.PRODUCT_ANALYST},
    # planning
    "generate_plan": {Role.PRODUCT_ANALYST, Role.DELIVERY_LEAD},
    "edit_story": {Role.DELIVERY_LEAD, Role.ENGINEERING_LEAD, Role.PRODUCT_ANALYST},
    "request_plan_revision": {Role.DELIVERY_LEAD, Role.PRODUCT_ANALYST},
    "sign_off_plan": {Role.BUSINESS_OWNER},
    # build & review
    "assign_task": {Role.ENGINEERING_LEAD, Role.DELIVERY_LEAD},
    "start_task": {Role.ENGINEERING_LEAD, Role.DELIVERY_LEAD},
    "run_development": {Role.ENGINEERING_LEAD, Role.DELIVERY_LEAD},
    "submit_for_review": {Role.ENGINEERING_LEAD, Role.DELIVERY_LEAD},
    "execute_review": {Role.INDEPENDENT_REVIEWER},
    "return_to_development": {Role.INDEPENDENT_REVIEWER},
    "approve_review": {Role.INDEPENDENT_REVIEWER},
    # quality
    "run_quality_checks": {Role.QA_LEAD, Role.DELIVERY_LEAD},
    "decide_quality_gate": {Role.QA_LEAD},
    # release
    "request_release_approval": {Role.RELEASE_MANAGER, Role.DELIVERY_LEAD},
    # Each required role records its own release approval; the final,
    # blocking decision is `deploy`, which only the Release Manager holds.
    "approve_release": {Role.BUSINESS_OWNER, Role.ENGINEERING_LEAD,
                        Role.QA_LEAD, Role.RELEASE_MANAGER},
    "deploy": {Role.RELEASE_MANAGER},
    "complete_handover": {Role.SUPPORT_LEAD, Role.RELEASE_MANAGER},
    # governance
    "create_amendment": {Role.DELIVERY_LEAD, Role.PRODUCT_ANALYST, Role.ENGINEERING_LEAD},
    "trigger_upstream_change": {Role.PRODUCT_ANALYST, Role.BUSINESS_OWNER},
    "run_self_correction": {Role.DELIVERY_LEAD, Role.ENGINEERING_LEAD},
    # run lifecycle — anyone driving the demo
    "manage_run": set(Role),
    # workspace handoff — packaging already-visible, already-labelled
    # artifacts for one assignee is not a governance decision, so it carries
    # the same "anyone driving the demo" permission as run lifecycle actions.
    "generate_workspace": set(Role),
}


def allowed(action: str, role: Role) -> bool:
    roles = PERMISSIONS.get(action)
    return roles is not None and role in roles


def require(action: str, role: Role) -> None:
    if action not in PERMISSIONS:
        raise PermissionError_(f"Unknown action: {action}")
    if role not in PERMISSIONS[action]:
        permitted = ", ".join(sorted(r.value for r in PERMISSIONS[action]))
        raise PermissionError_(
            f"Role '{role.value}' may not perform '{action}' (permitted: {permitted})"
        )


def actions_for(role: Role) -> list[str]:
    return sorted(a for a, roles in PERMISSIONS.items() if role in roles)
