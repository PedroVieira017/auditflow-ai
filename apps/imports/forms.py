from pathlib import Path

from django import forms

from .contracts import INVOICE_CSV_MAX_FILE_SIZE_BYTES


class InvoiceCSVUploadForm(forms.Form):
    file = forms.FileField(
        label="Ficheiro CSV",
        help_text="CSV UTF-8, ate 10 MiB.",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]
        filename = uploaded_file.name or ""

        if len(filename) > 255:
            raise forms.ValidationError(
                "O nome do ficheiro nao pode exceder 255 caracteres.",
                code="filename_too_long",
            )

        if Path(filename).suffix.lower() != ".csv":
            raise forms.ValidationError(
                "Selecione um ficheiro com a extensao .csv.",
                code="invalid_extension",
            )

        if uploaded_file.size == 0:
            raise forms.ValidationError(
                "O ficheiro esta vazio.",
                code="empty_file",
            )

        if uploaded_file.size > INVOICE_CSV_MAX_FILE_SIZE_BYTES:
            raise forms.ValidationError(
                "O ficheiro excede o limite de 10 MiB.",
                code="file_too_large",
            )

        initial_position = uploaded_file.tell()
        sample = uploaded_file.read(8192)
        uploaded_file.seek(initial_position)

        if b"\x00" in sample:
            raise forms.ValidationError(
                "O ficheiro contem dados binarios e nao parece ser um CSV.",
                code="binary_content",
            )

        try:
            sample.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise forms.ValidationError(
                "O ficheiro deve usar codificacao UTF-8.",
                code="invalid_encoding",
            ) from exc

        return uploaded_file
