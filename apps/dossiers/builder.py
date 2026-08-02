import hashlib
import json
import uuid
from collections import Counter
from datetime import timezone as datetime_timezone

from django.db.models import Prefetch
from django.utils import timezone

from apps.alerts.models import Alert, AlertEvidence, AlertStatusEvent
from apps.core.choices import Severity
from apps.imports.models import ImportBatch
from apps.organizations.models import Membership
from apps.rules.models import RuleRun


WORK_DOSSIER_CONTRACT = "auditflow-work-dossier-v1"

LIMITATIONS = (
    {
        "code": "not_an_audit_opinion",
        "message": (
            "O dossier não constitui opinião ou relatório de auditoria nem "
            "certificação legal das contas."
        ),
    },
    {
        "code": "rule_matches_only",
        "message": (
            "Os alertas indicam apenas correspondências aos critérios das "
            "regras executadas."
        ),
    },
    {
        "code": "human_review_required",
        "message": (
            "Fraude, erro material, incumprimento ou deficiência de controlo "
            "exigem investigação e conclusão próprias."
        ),
    },
    {
        "code": "scope_limited_to_import",
        "message": (
            "O âmbito está limitado à importação identificada e não representa "
            "a totalidade das operações da organização."
        ),
    },
)


class WorkDossierError(RuntimeError):
    pass


class WorkDossierPermissionError(WorkDossierError):
    pass


class WorkDossierDataIntegrityError(WorkDossierError):
    pass


def _format_datetime(value):
    if value is None:
        return None
    if timezone.is_naive(value):
        raise WorkDossierDataIntegrityError(
            "O dossier não aceita datas e horas sem fuso horário."
        )
    value = value.astimezone(datetime_timezone.utc)
    timespec = "microseconds" if value.microsecond else "seconds"
    return value.isoformat(timespec=timespec).replace("+00:00", "Z")


def _serialize_user(user):
    if user is None:
        return None
    return {
        "email": user.email,
        "user_id": str(user.id),
    }


def canonical_payload_bytes(payload):
    payload_without_integrity = {
        key: value
        for key, value in payload.items()
        if key != "integrity"
    }
    return json.dumps(
        payload_without_integrity,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def calculate_payload_hash(payload):
    return hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()


def _validate_generation_permission(*, import_batch, generated_by):
    is_allowed = (
        generated_by is not None
        and getattr(generated_by, "is_active", False)
        and Membership.objects.filter(
            organization=import_batch.organization,
            organization__is_active=True,
            user=generated_by,
            is_active=True,
            role__in=(Membership.Role.OWNER, Membership.Role.ANALYST),
        ).exists()
    )
    if not is_allowed:
        raise WorkDossierPermissionError(
            "O utilizador não pode gerar dossiers para esta organização."
        )


def _load_rule_runs(import_batch):
    return list(
        RuleRun.objects.for_organization(import_batch.organization)
        .filter(import_batch=import_batch)
        .select_related("rule_definition")
        .order_by("rule_definition__key", "rule_definition__version", "id")
    )


def _load_alerts(import_batch):
    evidence = (
        AlertEvidence.objects.for_organization(import_batch.organization)
        .select_related("invoice_record")
        .order_by("invoice_record__source_row_number", "id")
    )
    status_events = (
        AlertStatusEvent.objects.for_organization(import_batch.organization)
        .select_related("changed_by")
        .order_by("created_at", "id")
    )
    return list(
        Alert.objects.for_organization(import_batch.organization)
        .filter(rule_run__import_batch=import_batch)
        .prefetch_related(
            Prefetch("evidence", queryset=evidence),
            Prefetch("status_events", queryset=status_events),
        )
        .order_by("created_at", "id")
    )


def _serialize_rule_run(rule_run):
    if rule_run.status not in RuleRun.Status.values:
        raise WorkDossierDataIntegrityError(
            "Uma execução de regra possui um estado inválido."
        )
    definition = rule_run.rule_definition
    return {
        "alert_count": rule_run.alert_count,
        "completed_at": _format_datetime(rule_run.completed_at),
        "id": str(rule_run.id),
        "parameters": rule_run.parameters,
        "rule": {
            "description": definition.description,
            "key": definition.key,
            "name": definition.name,
            "version": definition.version,
        },
        "started_at": _format_datetime(rule_run.started_at),
        "status": rule_run.status,
    }


def _serialize_evidence(*, evidence, import_batch):
    invoice = evidence.invoice_record
    if invoice.import_batch_id != import_batch.id:
        raise WorkDossierDataIntegrityError(
            "Uma evidência referencia uma fatura de outra importação."
        )
    if not evidence.facts:
        raise WorkDossierDataIntegrityError(
            "Uma evidência não possui os factos que fundamentaram o alerta."
        )
    return {
        "evidence_id": str(evidence.id),
        "facts": evidence.facts,
        "invoice_record_id": str(invoice.id),
        "source_row_number": invoice.source_row_number,
    }


def _serialize_status_history(alert):
    serialized_events = []
    expected_from_status = Alert.Status.NEW
    for event in alert.status_events.all():
        if (
            event.from_status not in Alert.Status.values
            or event.to_status not in Alert.Status.values
        ):
            raise WorkDossierDataIntegrityError(
                "O histórico de decisões do alerta possui um estado inválido."
            )
        if not (event.note or "").strip():
            raise WorkDossierDataIntegrityError(
                "Uma decisão do alerta não possui justificação."
            )
        if event.from_status != expected_from_status:
            raise WorkDossierDataIntegrityError(
                "O histórico de decisões do alerta não é contínuo."
            )
        serialized_events.append(
            {
                "changed_at": _format_datetime(event.created_at),
                "changed_by": _serialize_user(event.changed_by),
                "event_id": str(event.id),
                "from_status": event.from_status,
                "note": event.note,
                "to_status": event.to_status,
            }
        )
        expected_from_status = event.to_status

    if expected_from_status != alert.status:
        raise WorkDossierDataIntegrityError(
            "O estado atual do alerta não corresponde ao seu histórico."
        )
    return serialized_events


def _serialize_alert(*, alert, import_batch):
    if alert.status not in Alert.Status.values:
        raise WorkDossierDataIntegrityError("O alerta possui um estado inválido.")
    if alert.severity not in Severity.values:
        raise WorkDossierDataIntegrityError(
            "O alerta possui uma prioridade inválida."
        )
    serialized_evidence = [
        _serialize_evidence(evidence=item, import_batch=import_batch)
        for item in alert.evidence.all()
    ]
    if not serialized_evidence:
        raise WorkDossierDataIntegrityError(
            "Um alerta não possui evidências associadas."
        )
    return {
        "created_at": _format_datetime(alert.created_at),
        "evidence": serialized_evidence,
        "explanation": alert.explanation,
        "fingerprint": alert.fingerprint,
        "id": str(alert.id),
        "recommended_action": alert.recommended_action,
        "rule_run_id": str(alert.rule_run_id),
        "severity": alert.severity,
        "status": alert.status,
        "status_history": _serialize_status_history(alert),
        "title": alert.title,
    }


def _validate_run_alert_counts(*, rule_runs, alerts):
    alerts_by_run = Counter(alert.rule_run_id for alert in alerts)
    for rule_run in rule_runs:
        if rule_run.alert_count != alerts_by_run[rule_run.id]:
            raise WorkDossierDataIntegrityError(
                "A contagem persistida de alertas da execução não corresponde "
                "aos alertas existentes."
            )


def build_work_dossier_payload(
    *,
    import_batch,
    generated_by,
    generation_id=None,
    generated_at=None,
):
    try:
        import_batch = ImportBatch.objects.select_related(
            "organization",
            "uploaded_by",
        ).get(id=import_batch.id)
    except ImportBatch.DoesNotExist as exc:
        raise WorkDossierDataIntegrityError(
            "A importação já não existe."
        ) from exc

    if import_batch.status != ImportBatch.Status.COMPLETED:
        raise WorkDossierDataIntegrityError(
            "Apenas importações concluídas podem originar um dossier."
        )
    if import_batch.completed_at is None:
        raise WorkDossierDataIntegrityError(
            "A importação concluída não possui data de conclusão."
        )
    _validate_generation_permission(
        import_batch=import_batch,
        generated_by=generated_by,
    )

    try:
        generation_id = uuid.UUID(str(generation_id or uuid.uuid4()))
    except (AttributeError, TypeError, ValueError) as exc:
        raise WorkDossierDataIntegrityError(
            "O identificador da geração do dossier é inválido."
        ) from exc
    generated_at = generated_at or timezone.now()
    formatted_generated_at = _format_datetime(generated_at)

    rule_runs = _load_rule_runs(import_batch)
    alerts = _load_alerts(import_batch)
    _validate_run_alert_counts(rule_runs=rule_runs, alerts=alerts)
    serialized_alerts = [
        _serialize_alert(alert=alert, import_batch=import_batch)
        for alert in alerts
    ]

    status_counts = Counter(alert.status for alert in alerts)
    severity_counts = Counter(alert.severity for alert in alerts)
    payload = {
        "alerts": serialized_alerts,
        "contract": WORK_DOSSIER_CONTRACT,
        "document": {
            "certification": "not_certified",
            "classification": "internal_working_document",
            "generated_at": formatted_generated_at,
            "generated_by": _serialize_user(generated_by),
            "generation_id": str(generation_id),
        },
        "limitations": [dict(limitation) for limitation in LIMITATIONS],
        "organization": {
            "id": str(import_batch.organization_id),
            "name": import_batch.organization.name,
        },
        "rule_runs": [_serialize_rule_run(rule_run) for rule_run in rule_runs],
        "scope": {
            "import": {
                "completed_at": _format_datetime(import_batch.completed_at),
                "file_sha256": import_batch.file_sha256,
                "id": str(import_batch.id),
                "invalid_row_count": import_batch.invalid_row_count,
                "original_filename": import_batch.original_filename,
                "row_count": import_batch.row_count,
                "status": import_batch.status,
                "uploaded_by": _serialize_user(import_batch.uploaded_by),
                "valid_row_count": import_batch.valid_row_count,
            },
            "type": "import_batch",
        },
        "summary": {
            "alert_count": len(alerts),
            "alerts_by_severity": {
                severity: severity_counts[severity]
                for severity in (
                    Severity.CRITICAL,
                    Severity.HIGH,
                    Severity.LOW,
                    Severity.MEDIUM,
                )
            },
            "alerts_by_status": {
                status: status_counts[status]
                for status in (
                    Alert.Status.FALSE_POSITIVE,
                    Alert.Status.NEW,
                    Alert.Status.RESOLVED,
                    Alert.Status.VALID,
                )
            },
            "rule_run_count": len(rule_runs),
        },
    }
    payload["integrity"] = {
        "algorithm": "sha256",
        "payload_hash": calculate_payload_hash(payload),
    }
    return payload
