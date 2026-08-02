import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.imports.contracts import (
    INVOICE_CSV_ALLOWED_CURRENCIES,
    INVOICE_CSV_AMOUNT_PATTERN,
    INVOICE_CSV_COLUMNS,
    INVOICE_CSV_CONTRACT_VERSION,
    INVOICE_CSV_CURRENCY_PATTERN,
    INVOICE_CSV_DATE_FORMAT,
    INVOICE_CSV_DECODER,
    INVOICE_CSV_DELIMITER,
    INVOICE_CSV_MAX_DATA_ROWS,
    INVOICE_CSV_MAX_FILE_SIZE_BYTES,
    INVOICE_CSV_MAX_FIELD_LENGTHS,
    INVOICE_CSV_UNSAFE_TEXT_PREFIXES,
    normalize_match_text,
)


class InvoiceCSVContractTests(SimpleTestCase):
    examples_dir = Path(settings.BASE_DIR) / "examples" / "csv"

    def read_rows(self, filename):
        with (self.examples_dir / filename).open(
            "r",
            encoding=INVOICE_CSV_DECODER,
            newline="",
        ) as csv_file:
            return list(
                csv.reader(
                    csv_file,
                    delimiter=INVOICE_CSV_DELIMITER,
                    strict=True,
                )
            )

    def read_json(self, filename):
        return json.loads(
            (self.examples_dir / filename).read_text(encoding="utf-8")
        )

    def test_contract_limits_are_explicit_and_bounded(self):
        self.assertEqual(INVOICE_CSV_CONTRACT_VERSION, "supplier-invoices-v1")
        self.assertEqual(INVOICE_CSV_MAX_FILE_SIZE_BYTES, 10 * 1024 * 1024)
        self.assertEqual(INVOICE_CSV_MAX_DATA_ROWS, 50_000)
        self.assertEqual(INVOICE_CSV_DELIMITER, ";")

    def test_valid_fixture_follows_the_contract(self):
        rows = self.read_rows("faturas_validas.csv")
        metadata = self.read_json("faturas_validas.expected.json")

        self.assertEqual(tuple(rows[0]), INVOICE_CSV_COLUMNS)
        self.assertEqual(len(rows) - 1, metadata["valid_data_rows"])
        self.assertEqual(metadata["contract_version"], INVOICE_CSV_CONTRACT_VERSION)

        for source_row, row in enumerate(rows[1:], start=2):
            with self.subTest(source_row=source_row):
                self.assertEqual(len(row), len(INVOICE_CSV_COLUMNS))
                values = dict(zip(INVOICE_CSV_COLUMNS, row, strict=True))
                self.assertTrue(all(value.strip() for value in values.values()))
                self.assertLessEqual(
                    len(values["fornecedor_id"]),
                    INVOICE_CSV_MAX_FIELD_LENGTHS["fornecedor_id"],
                )
                self.assertLessEqual(
                    len(values["numero_fatura"]),
                    INVOICE_CSV_MAX_FIELD_LENGTHS["numero_fatura"],
                )
                datetime.strptime(values["data_fatura"], INVOICE_CSV_DATE_FORMAT)
                self.assertRegex(values["valor_total"], INVOICE_CSV_AMOUNT_PATTERN)
                self.assertGreater(
                    Decimal(values["valor_total"].replace(",", ".")),
                    Decimal("0"),
                )
                self.assertRegex(values["moeda"], INVOICE_CSV_CURRENCY_PATTERN)
                self.assertIn(values["moeda"], INVOICE_CSV_ALLOWED_CURRENCIES)
                self.assertFalse(
                    values["fornecedor_id"].startswith(
                        INVOICE_CSV_UNSAFE_TEXT_PREFIXES
                    )
                )
                self.assertFalse(
                    values["numero_fatura"].startswith(
                        INVOICE_CSV_UNSAFE_TEXT_PREFIXES
                    )
                )

    def test_valid_fixture_contains_exactly_the_expected_duplicate_group(self):
        rows = self.read_rows("faturas_validas.csv")
        metadata = self.read_json("faturas_validas.expected.json")
        grouped_rows = defaultdict(list)

        for source_row, row in enumerate(rows[1:], start=2):
            values = dict(zip(INVOICE_CSV_COLUMNS, row, strict=True))
            duplicate_key = (
                normalize_match_text(values["fornecedor_id"]),
                normalize_match_text(values["numero_fatura"]),
                values["data_fatura"],
                str(Decimal(values["valor_total"].replace(",", "."))),
                values["moeda"],
            )
            grouped_rows[duplicate_key].append(source_row)

        duplicate_groups = []
        for key, source_rows in grouped_rows.items():
            if len(source_rows) < 2:
                continue
            duplicate_groups.append(
                {
                    "source_rows": source_rows,
                    "normalized_key": dict(zip(INVOICE_CSV_COLUMNS, key, strict=True)),
                }
            )

        duplicate_groups.sort(key=lambda item: item["source_rows"])
        expected_groups = sorted(
            metadata["expected_duplicate_groups"],
            key=lambda item: item["source_rows"],
        )

        self.assertEqual(duplicate_groups, expected_groups)

    def test_invalid_fixture_has_one_expected_error_for_every_data_row(self):
        rows = self.read_rows("faturas_invalidas.csv")
        manifest = self.read_json("erros_esperados.json")
        errors = manifest["files"]["faturas_invalidas.csv"]

        self.assertEqual(tuple(rows[0]), INVOICE_CSV_COLUMNS)
        self.assertEqual(
            {error["source_row"] for error in errors},
            set(range(2, len(rows) + 1)),
        )
        self.assertEqual(len(errors), len(rows) - 1)

    def test_invalid_header_fixture_is_declared_in_error_manifest(self):
        rows = self.read_rows("cabecalho_invalido.csv")
        manifest = self.read_json("erros_esperados.json")
        errors = manifest["files"]["cabecalho_invalido.csv"]

        self.assertNotEqual(tuple(rows[0]), INVOICE_CSV_COLUMNS)
        self.assertEqual(
            errors,
            [{"source_row": 1, "field": None, "code": "unexpected_header"}],
        )

    def test_amount_pattern_rejects_unsupported_syntax(self):
        unsupported_values = (
            "0,00",
            "-10,00",
            "1.234,56",
            "1234.56",
            "1234,5",
            "10000000000000000,00",
        )

        for value in unsupported_values:
            with self.subTest(value=value):
                pattern_matches = re.fullmatch(INVOICE_CSV_AMOUNT_PATTERN, value)
                if value == "0,00":
                    self.assertIsNotNone(pattern_matches)
                else:
                    self.assertIsNone(pattern_matches)
