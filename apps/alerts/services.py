from django.db import transaction

from apps.audit_log.models import AuditEvent

from .models import Alert, AlertStatusEvent


class AlertStatusChangeError(ValueError):
    pass


class AlertStatusConflictError(AlertStatusChangeError):
    pass


def change_alert_status(
    *,
    alert,
    organization,
    changed_by,
    to_status,
    note,
    expected_status,
):
    valid_statuses = set(Alert.Status.values)
    if to_status not in valid_statuses:
        raise AlertStatusChangeError("O novo estado não é válido.")

    normalized_note = (note or "").strip()
    if not normalized_note:
        raise AlertStatusChangeError("A justificação é obrigatória.")

    with transaction.atomic():
        try:
            locked_alert = Alert.objects.select_for_update().get(
                id=alert.id,
                organization=organization,
            )
        except Alert.DoesNotExist as exc:
            raise AlertStatusChangeError(
                "O alerta não pertence à organização indicada."
            ) from exc

        if locked_alert.status != expected_status:
            raise AlertStatusConflictError(
                "O estado foi alterado por outra pessoa. Recarregue a página."
            )
        if locked_alert.status == to_status:
            raise AlertStatusChangeError(
                "O novo estado deve ser diferente do estado atual."
            )

        previous_status = locked_alert.status
        status_event = AlertStatusEvent.objects.create(
            organization=organization,
            alert=locked_alert,
            changed_by=changed_by,
            from_status=previous_status,
            to_status=to_status,
            note=normalized_note,
        )
        locked_alert.status = to_status
        locked_alert.save(update_fields=("status", "updated_at"))
        AuditEvent.objects.create(
            organization=organization,
            actor=changed_by,
            action="alert.status_changed",
            resource_type="alert",
            resource_id=locked_alert.id,
            metadata={
                "status_event_id": str(status_event.id),
                "from_status": previous_status,
                "to_status": to_status,
            },
        )

    return locked_alert, status_event
