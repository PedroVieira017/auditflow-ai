from django import forms

from apps.core.choices import Severity

from .models import ControlScenario


OBJECTIVE_CATEGORY_CHOICES = (
    ("operations", "Operações"),
    ("reporting", "Relato e informação"),
    ("compliance", "Conformidade"),
)

CONTROL_TYPE_CHOICES = (
    ("preventive", "Preventivo"),
    ("detective", "Detetivo"),
    ("corrective", "Corretivo"),
)

CONTROL_FREQUENCY_CHOICES = (
    ("per_transaction", "Por transação"),
    ("per_import", "Por importação"),
    ("daily", "Diário"),
    ("weekly", "Semanal"),
    ("monthly", "Mensal"),
    ("quarterly", "Trimestral"),
    ("annual", "Anual"),
    ("ad_hoc", "Quando necessário"),
)


class ControlScenarioDraftForm(forms.Form):
    key = forms.RegexField(
        label="Chave estável",
        regex=r"^[A-Z][A-Z0-9_]*$",
        max_length=100,
        help_text=(
            "Use letras maiúsculas, números e underscores. A chave não poderá "
            "ser alterada depois da criação."
        ),
        widget=forms.TextInput(
            attrs={"placeholder": "AP_DUPLICATE_INVOICE_REVIEW"}
        ),
    )
    name = forms.CharField(
        label="Nome do cenário",
        max_length=200,
        widget=forms.TextInput(
            attrs={"placeholder": "Revisão de duplicação de faturas"}
        ),
    )
    description = forms.CharField(
        label="Descrição",
        max_length=2_000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    change_reason = forms.CharField(
        label="Motivo da configuração",
        max_length=2_000,
        help_text="Explique por que motivo este cenário está a ser criado.",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    objective_category = forms.ChoiceField(
        label="Categoria do objetivo",
        choices=OBJECTIVE_CATEGORY_CHOICES,
        initial="operations",
    )
    objective_statement = forms.CharField(
        label="Objetivo da organização",
        max_length=2_000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    risk_statement = forms.CharField(
        label="Risco associado",
        max_length=2_000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    control_name = forms.CharField(
        label="Nome do controlo",
        max_length=200,
    )
    control_description = forms.CharField(
        label="Procedimento de controlo",
        max_length=3_000,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    control_type = forms.ChoiceField(
        label="Tipo de controlo",
        choices=CONTROL_TYPE_CHOICES,
        initial="detective",
    )
    control_frequency = forms.ChoiceField(
        label="Frequência",
        choices=CONTROL_FREQUENCY_CHOICES,
        initial="per_import",
    )
    control_owner_role = forms.CharField(
        label="Função responsável pelo controlo",
        max_length=200,
        widget=forms.TextInput(
            attrs={"placeholder": "Responsável de contas a pagar"}
        ),
    )

    reviewer_role = forms.CharField(
        label="Função responsável pela revisão",
        max_length=200,
        widget=forms.TextInput(
            attrs={"placeholder": "Responsável de contas a pagar"}
        ),
    )
    review_due_days = forms.IntegerField(
        label="Prazo interno de revisão (dias)",
        min_value=1,
        max_value=365,
        initial=5,
    )
    indicator_target = forms.DecimalField(
        label="Objetivo de alertas por importação",
        min_value=0,
        max_digits=12,
        decimal_places=2,
        initial=0,
        help_text=(
            "Valor de referência para o indicador. Não cria uma conclusão "
            "automática sobre o controlo."
        ),
    )
    rule_severity = forms.ChoiceField(
        label="Prioridade dos alertas",
        choices=Severity.choices,
        initial=Severity.MEDIUM,
    )

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization

    def clean_key(self):
        key = self.cleaned_data["key"].strip()
        if ControlScenario.objects.for_organization(self.organization).filter(
            key=key
        ).exists():
            raise forms.ValidationError(
                "Já existe um cenário com esta chave na organização."
            )
        return key
