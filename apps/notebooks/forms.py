from django import forms
from django.conf import settings

from .models import Notebook
from .services.document_processor import ALLOWED_EXTENSIONS, allowed_upload_suffix


class PDFUploadForm(forms.ModelForm):
    class Meta:
        model = Notebook
        fields = ('title', 'pdf_file')
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'e.g. Biology Chapter 5 - Cell Respiration',
            }),
            'pdf_file': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': ','.join(sorted(ALLOWED_EXTENSIONS)),
            }),
        }
        labels = {
            'pdf_file': 'Study document',
        }
        help_texts = {
            'pdf_file': (
                f'PDF, Word (.docx), or plain text (.txt, .md). '
                f'Max {getattr(settings, "MAX_UPLOAD_MB", settings.MAX_PDF_SIZE_MB)} MB.'
            ),
        }

    def clean_pdf_file(self):
        pdf = self.cleaned_data.get('pdf_file')
        if pdf:
            max_mb = getattr(settings, 'MAX_UPLOAD_MB', settings.MAX_PDF_SIZE_MB)
            max_bytes = max_mb * 1024 * 1024
            if pdf.size > max_bytes:
                raise forms.ValidationError(
                    f'File too large. Maximum size is {max_mb} MB.'
                )
            ext = allowed_upload_suffix(pdf.name)
            if ext is None:
                allowed = ', '.join(sorted(ALLOWED_EXTENSIONS))
                raise forms.ValidationError(
                    f'Unsupported file type. Allowed extensions: {allowed}'
                )
        return pdf


class NotesEditForm(forms.Form):
    notes_content = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control notes-textarea', 'rows': 30}),
        required=False,
    )


class SummaryForm(forms.Form):
    user_summary = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control summary-textarea',
            'rows': 6,
            'placeholder': 'Write a summary of what you learned from this material...',
        }),
        required=False,
    )
