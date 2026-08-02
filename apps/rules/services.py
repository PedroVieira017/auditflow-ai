from django.db import transaction
from django.utils import timezone

from apps.alerts.models import Alert, AlertEvidence
from apps.audit_log.models import AuditEvent
from apps.imports.models import ImportBatch
from apps.invoices.models import InvoiceRecord

from .engine import InvoiceFact, RuleContext, execute_rule
from .models import RuleDefinition, RuleRun


class RuleExecutionError(RuntimeError):
    pass


class RuleDefinitionConflictError(RuleExecutionError):
    pass


def _get_or_create_rule_definition(rule):
    metadata = rule.metadata
    expected_values = {
        "name": metadata.name,
        "description": metadata.description,
        "default_severity": metadata.default_severity,
        "parameters_schema": dict(metadata.parameters_schema),
    }
    definition, created = RuleDefinition.objects.get_or_create(
        key=metadata.key,
        version=metadata.version,
        defaults={**expected_values, "is_active": True},
    )
    if not created:
        actual_values = {
            "name": definition.name,
            "description": definition.description,
            "default_severity": definition.default_severity,
            "parameters_schema": definition.parameters_schema,
        }
        if actual_values != expected_values:
            raise RuleDefinitionConflictError(
                f"A definicao persistida de {metadata.key} v{metadata.version} "
                "nao corresponde ao codigo."
            )
        if not definition.is_active:
            raise RuleExecutionError(
                f"A regra {metadata.key} v{metadata.version} esta inativa."
            )
    return definition


def _build_context(import_batch, parameters):
    invoices = InvoiceRecord.objects.for_organization(
        import_batch.organization
    ).filter(import_batch=import_batch).order_by("source_row_number", "id")
    invoice_facts = tuple(
        InvoiceFact(
            id=invoice.id,
            source_row_number=invoice.source_row_number,
            supplier_identifier=invoice.supplier_identifier,
            invoice_number=invoice.invoice_number,
            normalized_invoice_number=invoice.normalized_invoice_number,
            invoice_date=invoice.invoice_date,
            gross_amount=invoice.gross_amount,
            currency=invoice.currency,
        )
        for invoice in invoices
    )
    return RuleContext(
        organization_id=import_batch.organization_id,
        import_batch_id=import_batch.id,
        invoices=invoice_facts,
        parameters=parameters,
    )


def _persist_findings(*, import_batch, rule_run, findings):
    with transaction.atomic():
        locked_rule_run = RuleRun.objects.select_for_update().get(id=rule_run.id)
        for finding in findings:
            alert = Alert.objects.create(
                organization=import_batch.organization,
                rule_run=locked_rule_run,
                fingerprint=finding.fingerprint,
                title=finding.title,
                explanation=finding.explanation,
                severity=finding.severity,
                recommended_action=finding.recommended_action,
            )
            for evidence in finding.evidence:
                invoice_record = InvoiceRecord.objects.for_organization(
                    import_batch.organization
                ).get(
                    id=evidence.invoice_id,
                    import_batch=import_batch,
                )
                AlertEvidence.objects.create(
                    organization=import_batch.organization,
                    alert=alert,
                    invoice_record=invoice_record,
                    facts=dict(evidence.facts),
                )

        locked_rule_run.status = RuleRun.Status.COMPLETED
        locked_rule_run.alert_count = len(findings)
        locked_rule_run.completed_at = timezone.now()
        locked_rule_run.error_message = ""
        locked_rule_run.save(
            update_fields=(
                "status",
                "alert_count",
                "completed_at",
                "error_message",
                "updated_at",
            )
        )
        AuditEvent.objects.create(
            organization=import_batch.organization,
            actor=import_batch.uploaded_by,
            action="rule_run.completed",
            resource_type="rule_run",
            resource_id=locked_rule_run.id,
            metadata={
                "rule_key": locked_rule_run.rule_definition.key,
                "rule_version": locked_rule_run.rule_definition.version,
                "alert_count": len(findings),
            },
        )


def _mark_rule_run_failed(*, import_batch, rule_run, error):
    RuleRun.objects.filter(id=rule_run.id).update(
        status=RuleRun.Status.FAILED,
        completed_at=timezone.now(),
        error_message=str(error)[:2_000],
        alert_count=0,
    )
    AuditEvent.objects.create(
        organization=import_batch.organization,
        actor=import_batch.uploaded_by,
        action="rule_run.failed",
        resource_type="rule_run",
        resource_id=rule_run.id,
        metadata={
            "rule_key": rule_run.rule_definition.key,
            "rule_version": rule_run.rule_definition.version,
        },
    )


def execute_rule_for_import(*, rule, import_batch, parameters=None):
    if import_batch.status != ImportBatch.Status.COMPLETED:
        raise RuleExecutionError(
            "Apenas importacoes concluidas podem executar regras."
        )

    parameters = dict(parameters or {})
    rule_definition = _get_or_create_rule_definition(rule)
    rule_run = RuleRun.objects.create(
        organization=import_batch.organization,
        import_batch=import_batch,
        rule_definition=rule_definition,
        status=RuleRun.Status.RUNNING,
        parameters=parameters,
        started_at=timezone.now(),
    )

    try:
        context = _build_context(import_batch, parameters)
        findings = execute_rule(rule, context)
        _persist_findings(
            import_batch=import_batch,
            rule_run=rule_run,
            findings=findings,
        )
    except Exception as exc:
        _mark_rule_run_failed(
            import_batch=import_batch,
            rule_run=rule_run,
            error=exc,
        )
        raise RuleExecutionError(
            f"A execucao de {rule.metadata.key} v{rule.metadata.version} falhou."
        ) from exc

    rule_run.refresh_from_db()
    return rule_run
