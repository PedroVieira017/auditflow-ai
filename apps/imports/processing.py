import csv
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from io import TextIOWrapper

from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from apps.audit_log.models import AuditEvent
from apps.invoices.models import InvoiceRecord

from .contracts import (
    INVOICE_CSV_ALLOWED_CURRENCIES,
    INVOICE_CSV_AMOUNT_PATTERN,
    INVOICE_CSV_COLUMNS,
    INVOICE_CSV_CURRENCY_PATTERN,
    INVOICE_CSV_DATE_FORMAT,
    INVOICE_CSV_DECODER,
    INVOICE_CSV_DELIMITER,
    INVOICE_CSV_MAX_DATA_ROWS,
    INVOICE_CSV_MAX_FIELD_LENGTHS,
    INVOICE_CSV_UNSAFE_TEXT_PREFIXES,
    normalize_match_text,
)
from .models import ImportBatch


logger = logging.getLogger(__name__)
MAX_STORED_ERRORS = 100


@dataclass(frozen=True)
class ParsedInvoiceRow:
    source_row_number: int
    supplier_identifier: str
    invoice_number: str
    normalized_invoice_number: str
    invoice_date: date
    gross_amount: Decimal
    currency: str
    source_values: dict


@dataclass
class CSVValidationResult:
    invoice_rows: list[ParsedInvoiceRow] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    row_count: int = 0
    valid_row_count: int = 0
    invalid_row_count: int = 0
    total_error_count: int = 0

    @property
    def is_valid(self) -> bool:
        return self.total_error_count == 0

    def add_error(self, *, source_row, field_name, code, message) -> None:
        self.total_error_count += 1
        if len(self.errors) < MAX_STORED_ERRORS:
            self.errors.append(
                {
                    "source_row": source_row,
                    "field": field_name,
                    "code": code,
                    "message": message,
                }
            )


def _validate_text_field(result, *, source_row, field_name, value):
    cleaned_value = value.strip()
    if not cleaned_value:
        result.add_error(
            source_row=source_row,
            field_name=field_name,
            code="required",
            message="Este campo e obrigatorio.",
        )
        return None

    if len(cleaned_value) > INVOICE_CSV_MAX_FIELD_LENGTHS[field_name]:
        result.add_error(
            source_row=source_row,
            field_name=field_name,
            code="field_too_long",
            message=(
                "O campo excede o limite de "
                f"{INVOICE_CSV_MAX_FIELD_LENGTHS[field_name]} caracteres."
            ),
        )
        return None

    if cleaned_value.startswith(INVOICE_CSV_UNSAFE_TEXT_PREFIXES):
        result.add_error(
            source_row=source_row,
            field_name=field_name,
            code="unsafe_spreadsheet_prefix",
            message="O campo comeca por um carater inseguro para folhas de calculo.",
        )
        return None

    return cleaned_value


def _validate_date(result, *, source_row, value):
    cleaned_value = value.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned_value):
        result.add_error(
            source_row=source_row,
            field_name="data_fatura",
            code="invalid_date_format",
            message="A data deve usar o formato AAAA-MM-DD.",
        )
        return None

    try:
        return datetime.strptime(cleaned_value, INVOICE_CSV_DATE_FORMAT).date()
    except ValueError:
        result.add_error(
            source_row=source_row,
            field_name="data_fatura",
            code="invalid_date",
            message="A data indicada nao existe no calendario.",
        )
        return None


def _validate_amount(result, *, source_row, value):
    cleaned_value = value.strip()
    if not cleaned_value:
        result.add_error(
            source_row=source_row,
            field_name="valor_total",
            code="required",
            message="Este campo e obrigatorio.",
        )
        return None

    if cleaned_value.startswith("-"):
        result.add_error(
            source_row=source_row,
            field_name="valor_total",
            code="must_be_positive",
            message="O valor deve ser superior a zero.",
        )
        return None

    if "." in cleaned_value:
        result.add_error(
            source_row=source_row,
            field_name="valor_total",
            code="thousands_separator_not_allowed",
            message="Nao utilize separadores de milhares.",
        )
        return None

    integer_part, separator, decimal_part = cleaned_value.partition(",")
    if separator and len(integer_part) > 16:
        result.add_error(
            source_row=source_row,
            field_name="valor_total",
            code="amount_too_large",
            message="O valor excede o limite suportado.",
        )
        return None

    if not separator or len(decimal_part) != 2:
        result.add_error(
            source_row=source_row,
            field_name="valor_total",
            code="invalid_decimal_places",
            message="O valor deve ter exatamente duas casas decimais.",
        )
        return None

    if not re.fullmatch(INVOICE_CSV_AMOUNT_PATTERN, cleaned_value):
        result.add_error(
            source_row=source_row,
            field_name="valor_total",
            code="invalid_amount_format",
            message="O valor possui um formato invalido.",
        )
        return None

    amount = Decimal(cleaned_value.replace(",", "."))
    if amount <= 0:
        result.add_error(
            source_row=source_row,
            field_name="valor_total",
            code="must_be_positive",
            message="O valor deve ser superior a zero.",
        )
        return None
    return amount


def _validate_currency(result, *, source_row, value):
    cleaned_value = value.strip()
    if not cleaned_value:
        result.add_error(
            source_row=source_row,
            field_name="moeda",
            code="required",
            message="Este campo e obrigatorio.",
        )
        return None

    if len(cleaned_value) == 3 and cleaned_value.upper() == cleaned_value:
        if not re.fullmatch(INVOICE_CSV_CURRENCY_PATTERN, cleaned_value):
            code = "invalid_currency"
            message = "A moeda deve conter tres letras."
        elif cleaned_value not in INVOICE_CSV_ALLOWED_CURRENCIES:
            code = "unsupported_currency"
            message = "Esta versao do contrato aceita apenas EUR."
        else:
            return cleaned_value
    elif len(cleaned_value) == 3 and cleaned_value.upper() != cleaned_value:
        code = "must_be_uppercase"
        message = "A moeda deve ser escrita em maiusculas."
    else:
        code = "invalid_currency"
        message = "A moeda deve conter tres letras."

    result.add_error(
        source_row=source_row,
        field_name="moeda",
        code=code,
        message=message,
    )
    return None


def _parse_data_row(result, *, source_row, row):
    if not row or all(not value.strip() for value in row):
        result.add_error(
            source_row=source_row,
            field_name=None,
            code="blank_row",
            message="A linha esta vazia.",
        )
        return None

    if len(row) != len(INVOICE_CSV_COLUMNS):
        result.add_error(
            source_row=source_row,
            field_name=None,
            code="unexpected_column_count",
            message=(
                f"Esperavam-se {len(INVOICE_CSV_COLUMNS)} colunas, "
                f"mas foram recebidas {len(row)}."
            ),
        )
        return None

    values = dict(zip(INVOICE_CSV_COLUMNS, row, strict=True))
    error_count_before = result.total_error_count
    supplier_identifier = _validate_text_field(
        result,
        source_row=source_row,
        field_name="fornecedor_id",
        value=values["fornecedor_id"],
    )
    invoice_number = _validate_text_field(
        result,
        source_row=source_row,
        field_name="numero_fatura",
        value=values["numero_fatura"],
    )
    invoice_date = _validate_date(
        result,
        source_row=source_row,
        value=values["data_fatura"],
    )
    gross_amount = _validate_amount(
        result,
        source_row=source_row,
        value=values["valor_total"],
    )
    currency = _validate_currency(
        result,
        source_row=source_row,
        value=values["moeda"],
    )

    if result.total_error_count > error_count_before:
        return None

    return ParsedInvoiceRow(
        source_row_number=source_row,
        supplier_identifier=supplier_identifier,
        invoice_number=invoice_number,
        normalized_invoice_number=normalize_match_text(invoice_number),
        invoice_date=invoice_date,
        gross_amount=gross_amount,
        currency=currency,
        source_values=values,
    )


def parse_invoice_csv(storage_key: str) -> CSVValidationResult:
    result = CSVValidationResult()
    reader = None

    try:
        with default_storage.open(storage_key, "rb") as stored_file:
            with TextIOWrapper(
                stored_file,
                encoding=INVOICE_CSV_DECODER,
                newline="",
            ) as text_file:
                reader = csv.reader(
                    text_file,
                    delimiter=INVOICE_CSV_DELIMITER,
                    strict=True,
                )
                try:
                    header = next(reader)
                except StopIteration:
                    result.add_error(
                        source_row=1,
                        field_name=None,
                        code="empty_file",
                        message="O ficheiro nao contem um cabecalho.",
                    )
                    return result

                if tuple(header) != INVOICE_CSV_COLUMNS:
                    result.add_error(
                        source_row=1,
                        field_name=None,
                        code="unexpected_header",
                        message="O cabecalho nao corresponde ao contrato CSV v1.",
                    )
                    return result

                for source_row, row in enumerate(reader, start=2):
                    result.row_count += 1
                    if result.row_count > INVOICE_CSV_MAX_DATA_ROWS:
                        result.add_error(
                            source_row=source_row,
                            field_name=None,
                            code="too_many_rows",
                            message=(
                                "O ficheiro excede o limite de "
                                f"{INVOICE_CSV_MAX_DATA_ROWS} linhas."
                            ),
                        )
                        result.invalid_row_count += 1
                        break

                    parsed_row = _parse_data_row(
                        result,
                        source_row=source_row,
                        row=row,
                    )
                    if parsed_row is None:
                        result.invalid_row_count += 1
                    else:
                        result.valid_row_count += 1
                        result.invoice_rows.append(parsed_row)

                if result.row_count == 0:
                    result.add_error(
                        source_row=None,
                        field_name=None,
                        code="no_data_rows",
                        message="O ficheiro nao contem linhas de dados.",
                    )
    except UnicodeDecodeError:
        result.add_error(
            source_row=reader.line_num if reader else None,
            field_name=None,
            code="invalid_encoding",
            message="O ficheiro deve usar codificacao UTF-8.",
        )
    except csv.Error:
        result.add_error(
            source_row=reader.line_num if reader else None,
            field_name=None,
            code="invalid_csv",
            message="O ficheiro possui uma estrutura CSV invalida.",
        )
    except OSError:
        result.add_error(
            source_row=None,
            field_name=None,
            code="storage_read_error",
            message="Nao foi possivel ler o ficheiro armazenado.",
        )

    return result


def _mark_import_failed(import_batch, result) -> None:
    with transaction.atomic():
        InvoiceRecord.objects.filter(import_batch=import_batch).delete()
        import_batch.status = ImportBatch.Status.FAILED
        import_batch.row_count = result.row_count
        import_batch.valid_row_count = result.valid_row_count
        import_batch.invalid_row_count = result.invalid_row_count
        import_batch.error_summary = result.errors
        import_batch.completed_at = timezone.now()
        import_batch.save(
            update_fields=(
                "status",
                "row_count",
                "valid_row_count",
                "invalid_row_count",
                "error_summary",
                "completed_at",
                "updated_at",
            )
        )
        AuditEvent.objects.create(
            organization=import_batch.organization,
            actor=import_batch.uploaded_by,
            action="import.validation_failed",
            resource_type="import_batch",
            resource_id=import_batch.id,
            metadata={
                "row_count": result.row_count,
                "valid_row_count": result.valid_row_count,
                "invalid_row_count": result.invalid_row_count,
                "error_count": result.total_error_count,
                "stored_error_count": len(result.errors),
            },
        )


def _persist_valid_import(import_batch, result) -> None:
    invoice_records = [
        InvoiceRecord(
            organization=import_batch.organization,
            import_batch=import_batch,
            source_row_number=row.source_row_number,
            supplier_identifier=row.supplier_identifier,
            invoice_number=row.invoice_number,
            normalized_invoice_number=row.normalized_invoice_number,
            invoice_date=row.invoice_date,
            gross_amount=row.gross_amount,
            currency=row.currency,
            source_values=row.source_values,
        )
        for row in result.invoice_rows
    ]

    with transaction.atomic():
        InvoiceRecord.objects.filter(import_batch=import_batch).delete()
        InvoiceRecord.objects.bulk_create(invoice_records, batch_size=1_000)
        import_batch.status = ImportBatch.Status.COMPLETED
        import_batch.row_count = result.row_count
        import_batch.valid_row_count = result.valid_row_count
        import_batch.invalid_row_count = 0
        import_batch.error_summary = []
        import_batch.completed_at = timezone.now()
        import_batch.save(
            update_fields=(
                "status",
                "row_count",
                "valid_row_count",
                "invalid_row_count",
                "error_summary",
                "completed_at",
                "updated_at",
            )
        )
        AuditEvent.objects.create(
            organization=import_batch.organization,
            actor=import_batch.uploaded_by,
            action="import.processed",
            resource_type="import_batch",
            resource_id=import_batch.id,
            metadata={"row_count": result.row_count},
        )


def process_import_batch(import_batch) -> CSVValidationResult:
    started_at = timezone.now()
    ImportBatch.objects.filter(id=import_batch.id).update(
        status=ImportBatch.Status.PROCESSING,
        started_at=started_at,
        completed_at=None,
        row_count=0,
        valid_row_count=0,
        invalid_row_count=0,
        error_summary=[],
    )
    import_batch.refresh_from_db()

    try:
        result = parse_invoice_csv(import_batch.storage_key)
    except Exception:
        logger.exception("Unexpected error while processing import %s", import_batch.id)
        result = CSVValidationResult()
        result.add_error(
            source_row=None,
            field_name=None,
            code="processing_error",
            message="O ficheiro nao pode ser processado devido a um erro interno.",
        )

    if result.is_valid:
        try:
            _persist_valid_import(import_batch, result)
        except Exception:
            logger.exception("Unable to persist import %s", import_batch.id)
            result.add_error(
                source_row=None,
                field_name=None,
                code="persistence_error",
                message="Os dados validados nao puderam ser guardados.",
            )
            _mark_import_failed(import_batch, result)
    else:
        _mark_import_failed(import_batch, result)

    import_batch.refresh_from_db()
    return result
