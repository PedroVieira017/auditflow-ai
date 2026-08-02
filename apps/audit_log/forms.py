from django import forms

from .presentation import ACTION_LABELS


class AuditEventFilterForm(forms.Form):
    action = forms.ChoiceField(
        choices=(("", "Todos os tipos"), *ACTION_LABELS.items()),
        label="Tipo de evento",
        required=False,
    )
