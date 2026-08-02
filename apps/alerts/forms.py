from django import forms

from .models import Alert


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
