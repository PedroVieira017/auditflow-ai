import unicodedata


INVOICE_CSV_CONTRACT_VERSION = "supplier-invoices-v1"
INVOICE_CSV_COLUMNS = (
    "fornecedor_id",
    "numero_fatura",
    "data_fatura",
    "valor_total",
    "moeda",
)
INVOICE_CSV_DELIMITER = ";"
INVOICE_CSV_DECODER = "utf-8-sig"
INVOICE_CSV_DATE_FORMAT = "%Y-%m-%d"
INVOICE_CSV_AMOUNT_PATTERN = r"^(?:0|[1-9]\d{0,15}),\d{2}$"
INVOICE_CSV_CURRENCY_PATTERN = r"^[A-Z]{3}$"
INVOICE_CSV_ALLOWED_CURRENCIES = frozenset({"EUR"})
INVOICE_CSV_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
INVOICE_CSV_MAX_DATA_ROWS = 50_000
INVOICE_CSV_MAX_FIELD_LENGTHS = {
    "fornecedor_id": 120,
    "numero_fatura": 120,
}
INVOICE_CSV_UNSAFE_TEXT_PREFIXES = ("=", "+", "@", "\t", "\r")


def normalize_match_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.strip().split()).upper()
