from .duplicate_invoices import DUPLICATE_INVOICE_EXACT_RULE
from .engine import RuleRegistry


rule_registry = RuleRegistry()
rule_registry.register(DUPLICATE_INVOICE_EXACT_RULE)
