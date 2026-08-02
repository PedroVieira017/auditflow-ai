from dataclasses import dataclass


ACTION_LABELS = {
    "import.created": "Importação criada",
    "import.processed": "Importação processada",
    "import.validation_failed": "Validação da importação falhou",
    "rule_run.completed": "Execução de regra concluída",
    "rule_run.failed": "Execução de regra falhou",
    "alert.status_changed": "Estado do alerta alterado",
    "dossier.generated": "Dossier gerado",
}

RESOURCE_LABELS = {
    "alert": "Alerta",
    "import_batch": "Importação",
    "rule_run": "Execução de regra",
    "work_dossier": "Dossier",
}

ACTION_DETAIL_FIELDS = {
    "import.created": (
        ("original_filename", "Ficheiro", False),
        ("contract_version", "Contrato", True),
        ("size_bytes", "Tamanho em bytes", False),
        ("file_sha256", "SHA-256 do ficheiro", True),
    ),
    "import.processed": (
        ("row_count", "Linhas processadas", False),
    ),
    "import.validation_failed": (
        ("row_count", "Linhas recebidas", False),
        ("valid_row_count", "Linhas válidas", False),
        ("invalid_row_count", "Linhas inválidas", False),
        ("error_count", "Erros encontrados", False),
        ("stored_error_count", "Erros guardados", False),
    ),
    "rule_run.completed": (
        ("rule_key", "Regra", True),
        ("rule_version", "Versão", False),
        ("alert_count", "Alertas gerados", False),
    ),
    "rule_run.failed": (
        ("rule_key", "Regra", True),
        ("rule_version", "Versão", False),
    ),
    "alert.status_changed": (
        ("from_status", "Estado anterior", True),
        ("to_status", "Novo estado", True),
        ("status_event_id", "Evento da decisão", True),
    ),
    "dossier.generated": (
        ("contract", "Contrato", True),
        ("format", "Formato", True),
        ("import_batch_id", "Importação", True),
        ("payload_hash", "SHA-256 do payload", True),
    ),
}


@dataclass(frozen=True)
class AuditEventDetail:
    label: str
    value: str
    monospace: bool = False


@dataclass(frozen=True)
class AuditEventPresentation:
    event: object
    action_label: str
    resource_label: str
    details: tuple[AuditEventDetail, ...]


def present_audit_event(event):
    details = []
    metadata = event.metadata if isinstance(event.metadata, dict) else {}
    for key, label, monospace in ACTION_DETAIL_FIELDS.get(event.action, ()):
        if key not in metadata:
            continue
        value = metadata[key]
        details.append(
            AuditEventDetail(
                label=label,
                value="—" if value is None else str(value),
                monospace=monospace,
            )
        )

    return AuditEventPresentation(
        event=event,
        action_label=ACTION_LABELS.get(event.action, event.action),
        resource_label=RESOURCE_LABELS.get(
            event.resource_type,
            event.resource_type,
        ),
        details=tuple(details),
    )
