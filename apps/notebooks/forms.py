from django import forms
from django.conf import settings
from .models import Notebook


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
                'accept': '.pdf',
            }),
        }

    def clean_pdf_file(self):
        pdf = self.cleaned_data.get('pdf_file')
        if pdf:
            max_bytes = settings.MAX_PDF_SIZE_MB * 1024 * 1024
            if pdf.size > max_bytes:
                raise forms.ValidationError(
                    f'File too large. Maximum size is {settings.MAX_PDF_SIZE_MB} MB.'
                )
            if not pdf.name.lower().endswith('.pdf'):
                raise forms.ValidationError('Only PDF files are supported.')
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
