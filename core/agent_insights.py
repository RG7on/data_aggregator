"""
Rule-based advisory insights for scrape diagnostics.

This module is intentionally local-only and deterministic.
It analyzes recent scrape logs + report config and returns explainable
recommendations without mutating project settings.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Tuple

from core.config import get_settings
from core.database import get_latest_scrape_status, get_scrape_log


def _parse_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def _report_key(source: str, report_id: str, label: str) -> Tuple[str, str]:
    ident = (report_id or '').strip() or f"label:{(label or '').strip()}"
    return (source, ident)


def _config_index() -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Return {(source, report_identity): report_cfg} for known workers."""
    settings = get_settings() or {}
    workers = settings.get("workers", {})
    idx: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for source in ("cuic", "smax"):
        reports = (workers.get(source) or {}).get("reports", [])
        for rep in reports:
            label = (rep or {}).get("label", "")
            report_id = (rep or {}).get("report_id", "")
            if not label and not report_id:
                continue
            idx[_report_key(source, str(report_id or ''), str(label or ''))] = rep or {}

    return idx


def _status_streak(events: List[Dict[str, Any]], status: str) -> int:
    streak = 0
    for e in events:
        if (e.get("status") or "").lower() == status:
            streak += 1
        else:
            break
    return streak


def _contains_any(text: str, needles: List[str]) -> bool:
    t = (text or "").lower()
    return any(n in t for n in needles)


def _rule_diagnose(source: str, report_id: str, label: str, events: List[Dict[str, Any]], cfg: Dict[str, Any]) -> Dict[str, Any] | None:
    """Return one top insight for a report key or None when healthy/insufficient."""
    if not events:
        return None

    last = events[0]
    last_status = (last.get("status") or "").lower()
    msg = (last.get("message") or "").strip()
    msg_l = msg.lower()

    error_streak = _status_streak(events, "error")
    no_data_streak = _status_streak(events, "no_data")
    skipped_streak = _status_streak(events, "skipped")

    evidence = {
        "report_id": report_id,
        "last_status": last_status,
        "last_message": msg,
        "last_row_count": last.get("row_count", 0),
        "error_streak": error_streak,
        "no_data_streak": no_data_streak,
        "skipped_streak": skipped_streak,
        "last_timestamp": last.get("timestamp", ""),
        "data_type": (cfg or {}).get("data_type", "ongoing"),
        "enabled": (cfg or {}).get("enabled", True),
    }

    if last_status == "error":
        if _contains_any(msg_l, ["sso", "microsoft", "login", "mfa", "session expired", "auth"]):
            return {
                "source": source,
                "report_id": report_id,
                "report_label": label,
                "severity": "high",
                "confidence": 0.92,
                "suspected_root_cause": "authentication_or_session_expired",
                "why": "The latest error message looks like an SSO/authentication/session problem.",
                "recommended_actions": [
                    "Run report validation in headed mode to refresh login session.",
                    "Verify account can access the source portal manually.",
                    "Re-run manual scrape after session refresh.",
                ],
                "evidence": evidence,
            }

        if _contains_any(msg_l, ["timeout", "timed out", "navigation", "wait_for", "selector", "iframe", "table view"]):
            return {
                "source": source,
                "report_id": report_id,
                "report_label": label,
                "severity": "high" if error_streak >= 2 else "medium",
                "confidence": 0.86,
                "suspected_root_cause": "selector_or_timing_instability",
                "why": "The failure signature matches timeout/navigation/selector issues.",
                "recommended_actions": [
                    "Run discovery/validation for this report to verify current page structure.",
                    "Increase relevant worker timeout settings if portal latency is high.",
                    "Check report URL/path still resolves to the intended page.",
                ],
                "evidence": evidence,
            }

        if _contains_any(msg_l, ["verification failed", "missing field", "field filter", "selectedfieldids", "selectedfields"]):
            return {
                "source": source,
                "report_id": report_id,
                "report_label": label,
                "severity": "medium",
                "confidence": 0.88,
                "suspected_root_cause": "filter_schema_or_saved_config_mismatch",
                "why": "The report opened, but the saved filter configuration does not match the current wizard state.",
                "recommended_actions": [
                    "Open the report in the control panel and re-save the filter settings.",
                    "Re-discover filters/properties if the wizard schema changed.",
                    "Check field-filter IDs and selected values against the current report definition.",
                ],
                "evidence": evidence,
            }

        if _contains_any(msg_l, ["could not open", "filter wizard failed", "reports iframe not found", "tab failed"]):
            return {
                "source": source,
                "report_id": report_id,
                "report_label": label,
                "severity": "medium",
                "confidence": 0.8,
                "suspected_root_cause": "report_path_or_wizard_issue",
                "why": "The report likely moved or its wizard flow changed.",
                "recommended_actions": [
                    "Re-validate report path/link from the control panel.",
                    "Re-discover filters/properties and save updated config.",
                    "Confirm report is still accessible with current permissions.",
                ],
                "evidence": evidence,
            }

        return {
            "source": source,
            "report_id": report_id,
            "report_label": label,
            "severity": "high" if error_streak >= 2 else "medium",
            "confidence": 0.65,
            "suspected_root_cause": "generic_worker_error",
            "why": "The report is failing but the message does not map to a specific known pattern.",
            "recommended_actions": [
                "Inspect recent scrape logs for this report.",
                "Run report validation/discovery to refresh config context.",
                "Retry manual scrape after validation.",
            ],
            "evidence": evidence,
        }

    if last_status == "no_data" and no_data_streak >= 3:
        return {
            "source": source,
            "report_id": report_id,
            "report_label": label,
            "severity": "medium",
            "confidence": 0.84,
            "suspected_root_cause": "persistent_empty_result",
            "why": "This report returned no data repeatedly, which suggests a filter/window mismatch.",
            "recommended_actions": [
                "Review report filters/date presets in configuration.",
                "Validate report manually to confirm source system has records.",
                "If intentionally empty, keep as-is and snooze this insight.",
            ],
            "evidence": evidence,
        }

    if last_status == "skipped" and (cfg or {}).get("data_type") == "historical" and skipped_streak >= 2:
        return {
            "source": source,
            "report_id": report_id,
            "report_label": label,
            "severity": "low",
            "confidence": 0.9,
            "suspected_root_cause": "historical_skip_expected",
            "why": "This report is historical and is being skipped because data already exists.",
            "recommended_actions": [
                "No action needed if this behavior is expected.",
                "Change data_type to ongoing only if the source data can change retroactively.",
            ],
            "evidence": evidence,
        }

    return None


def _severity_rank(level: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(level, 0)


def build_agent_insights(
    lookback: int = 300,
    max_reports: int = 20,
    include_evidence: bool = False,
) -> Dict[str, Any]:
    """
    Build explainable advisory insights from recent scrape history.
    """
    lookback = max(50, min(_parse_int(lookback, 300), 5000))
    max_reports = max(1, min(_parse_int(max_reports, 20), 200))

    events = get_scrape_log(lookback)
    by_key: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)

    for e in events:
        source = (e.get("source") or "").strip().lower()
        label = (e.get("report_label") or "").strip()
        report_id = (e.get("report_id") or "").strip()
        if not source or not label or label == "_worker":
            continue
        by_key[_report_key(source, report_id, label)].append(e)

    cfg_idx = _config_index()
    insights: List[Dict[str, Any]] = []

    for key, key_events in by_key.items():
        source, identity = key
        label = (key_events[0].get("report_label") or "").strip()
        report_id = (key_events[0].get("report_id") or "").strip()
        insight = _rule_diagnose(source, report_id, label, key_events, cfg_idx.get(key, {}))
        if not insight:
            continue
        if not include_evidence:
            insight.pop("evidence", None)
        insight["last_seen"] = key_events[0].get("timestamp", "")
        insights.append(insight)

    insights.sort(
        key=lambda x: (
            _severity_rank(x.get("severity", "")),
            float(x.get("confidence", 0.0)),
            x.get("last_seen", ""),
        ),
        reverse=True,
    )

    trimmed = insights[:max_reports]
    counts = {"high": 0, "medium": 0, "low": 0}
    for i in trimmed:
        sev = i.get("severity", "")
        if sev in counts:
            counts[sev] += 1

    return {
        "meta": {
            "mode": "local_rule_engine",
            "advisory_only": True,
            "lookback": lookback,
            "reports_analyzed": len(by_key),
            "insights_returned": len(trimmed),
        },
        "summary": {
            "high": counts["high"],
            "medium": counts["medium"],
            "low": counts["low"],
        },
        "insights": trimmed,
    }


def build_report_insight(
    source: str,
    report_label: str,
    lookback: int = 500,
    include_evidence: bool = True,
) -> Dict[str, Any]:
    """Return a focused insight for one report key."""
    source = (source or "").strip().lower()
    report_label = (report_label or "").strip()
    if not source or not report_label:
        return {"error": "source and report_label are required"}

    lookback = max(50, min(_parse_int(lookback, 500), 5000))
    events = get_scrape_log(lookback)
    cfg_idx = _config_index()
    cfg_by_label = {
        ((rep or {}).get('label') or '').strip(): rep
        for rep in cfg_idx.values()
    }
    requested_cfg = cfg_by_label.get(report_label)
    requested_id = ((requested_cfg or {}).get('report_id') or '').strip()
    scoped = [
        e for e in events
        if (e.get("source") or "").strip().lower() == source
        and (
            (requested_id and (e.get("report_id") or "").strip() == requested_id)
            or (e.get("report_label") or "").strip() == report_label
        )
    ]

    if not scoped:
        return {
            "source": source,
            "report_id": requested_id,
            "report_label": report_label,
            "insight": None,
            "message": "No recent scrape events found for this report.",
        }

    report_id = (scoped[0].get('report_id') or requested_id or '').strip()
    display_label = (scoped[0].get('report_label') or report_label).strip()
    insight = _rule_diagnose(source, report_id, display_label, scoped, cfg_idx.get(_report_key(source, report_id, display_label), {}))
    if insight and not include_evidence:
        insight.pop("evidence", None)

    return {
        "source": source,
        "report_id": report_id,
        "report_label": display_label,
        "events_considered": len(scoped),
        "insight": insight,
        "recent_events": scoped[:25] if include_evidence else scoped[:10],
    }


def build_health_summary() -> Dict[str, Any]:
    """Return high-level scrape health summary from latest statuses."""
    latest = get_latest_scrape_status() or []
    total = len(latest)
    ok = sum(1 for r in latest if (r.get("status") or "").lower() == "success")
    err = sum(1 for r in latest if (r.get("status") or "").lower() == "error")
    no_data = sum(1 for r in latest if (r.get("status") or "").lower() == "no_data")
    skipped = sum(1 for r in latest if (r.get("status") or "").lower() == "skipped")

    success_rate = round((ok / total) * 100, 1) if total else 0.0

    return {
        "total_reports": total,
        "success": ok,
        "error": err,
        "no_data": no_data,
        "skipped": skipped,
        "success_rate": success_rate,
    }


def parse_agent_query_params(qs: Dict[str, List[str]]) -> Dict[str, Any]:
    """Normalize query-string params for agent endpoints."""
    lookback = _parse_int((qs.get("lookback") or ["300"])[0], 300)
    max_reports = _parse_int((qs.get("max_reports") or ["20"])[0], 20)
    include_evidence = _parse_bool((qs.get("include_evidence") or ["false"])[0], False)
    return {
        "lookback": lookback,
        "max_reports": max_reports,
        "include_evidence": include_evidence,
    }
