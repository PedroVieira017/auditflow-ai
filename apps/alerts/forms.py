from django import forms
from django.utils import timezone

from apps.core.choices import Severity
from apps.imports.models import ImportBatch

from .models import Alert


class ImportBatchChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        created_at = timezone.localtime(obj.created_at)
        return f"{obj.original_filename} — {created_at:%d/%m/%Y %H:%M}"


class AlertFilterForm(forms.Form):
    query = forms.CharField(
        label="Pesquisar",
        required=False,
        max_length=100,
        strip=True,
        widget=forms.TextInput(
            attrs={"placeholder": "Alerta, fornecedor, fatura ou ficheiro"}
        ),
    )
    status = forms.ChoiceField(
        label="Estado",
        required=False,
        choices=(("", "Todos os estados"), *Alert.Status.choices),
    )
    severity = forms.ChoiceField(
        label="Prioridade",
        required=False,
        choices=(("", "Todas as prioridades"), *Severity.choices),
    )
    import_batch = ImportBatchChoiceField(
        label="Importação",
        required=False,
        queryset=ImportBatch.objects.none(),
        empty_label="Todas as importações",
    )

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["import_batch"].queryset = (
            ImportBatch.objects.for_organization(organization)
            .filter(rule_runs__alerts__isnull=False)
            .distinct()
            .order_by("-created_at")
        )


class AlertStatusForm(forms.Form):
    status = forms.ChoiceField(label="Novo estado")
    note = forms.CharField(
        label="Justificação",
        max_length=2_000,
        strip=True,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=(
            "Explique a verificação realizada e a razão da decisão. "
            "O estado Válido confirma apenas a exceção observada."
        ),
    )
    expected_status = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, current_status, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (value, label)
            for value, label in Alert.Status.choices
            if value != current_status
        ]
        self.fields["expected_status"].initial = current_status

    def clean_note(self):
        note = self.cleaned_data["note"].strip()
        if not note:
            raise forms.ValidationError("A justificação é obrigatória.")
        return note
