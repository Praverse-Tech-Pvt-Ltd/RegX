from .models import *
from django import forms
from django import forms


#ANDA
class ANDAForm(forms.ModelForm):
    class Meta:
        model = ANDAUserReports
        fields = ["product_name"]
        widgets = {
            "product_name": forms.TextInput(attrs={'class': 'form-control w-50'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.report_name = kwargs.pop("report_name", None)
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.user = self.user
        if self.report_name:
            instance.report_name = self.report_name
        if commit:
            instance.save()
        return instance


#Size Shape Score
class SizeShapeScoreForm(forms.ModelForm):
    class Meta:
        model = ProductComparison
        fields = [
            "company_product_name",
            "product_type",
            "product_name",
        ]
        widgets = {
            "user": forms.HiddenInput(),
            "product_type": forms.Select(attrs={'class': 'form-control w-50'}),
            "company_product_name": forms.TextInput(attrs={'class': 'form-control w-50'}),
            "product_name": forms.TextInput(attrs={'class': 'form-control w-50'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.user = self.user
        if commit:
            instance.save()
        return instance


# IIG
class IIGForm(forms.ModelForm):
    class Meta:
        model = IIGChecklistUser
        fields = ["product_name"]
        widgets = {
            "product_name": forms.TextInput(attrs={'class': 'form-control w-50'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.report = kwargs.pop("report", None)
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.user = self.user
        if self.report:
            instance.report = self.report
        if commit:
            instance.save()
        return instance

# Appendix
# class AppendixForm(forms.ModelForm):
#     class Meta:
#         model = AppendixChecklistUser
#         fields = ["checklist_name"]
#         widgets = {
#             "user": forms.HiddenInput(),
#         }

#     def __init__(self, *args, **kwargs):
#         self.user = kwargs.pop("user", None)
#         super().__init__(*args, **kwargs)

#     def save(self, commit=True):
#         instance = super().save(commit=False)
#         if self.user:
#             instance.user = self.user
#         if commit:
#             instance.save()
#         return instance

# Validation
class ValidationForm(forms.ModelForm):
    class Meta:
        model = ValidationUserReports
        fields = ["product_name"]
        widgets = {
            "product_name": forms.TextInput(attrs={'class': 'form-control w-50'}),
        }
        labels = {
            "product_name": "API Name",
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.report_name = kwargs.pop("report_name", None)
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.user = self.user
        if self.report_name:
            instance.report_name = self.report_name
        if commit:
            instance.save()
        return instance

#VP
class VPForm(forms.ModelForm):
    class Meta:
        model = VPUserReports
        fields = ["product_name","category"]
        widgets = {
            "product_name": forms.TextInput(attrs={'class': 'form-control w-50'}),
            "category": forms.TextInput(attrs={'class': 'form-control w-50'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.report_name = kwargs.pop("report_name", None)
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.user = self.user
        if self.report_name:
            instance.report_name = self.report_name
        if commit:
            instance.save()
        return instance

#White Paper
class GeneralForm(forms.ModelForm):
    class Meta:
        model = GeneralChecklistUSer
        fields = ["product_name"]
        widgets = {
            "user": forms.HiddenInput(),
            "product_name": forms.TextInput(attrs={'class': 'form-control w-50'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.user = self.user
        if commit:
            instance.save()
        return instance

class DMFForm(forms.ModelForm):
    class Meta:
        model = DMFChecklistUser
        fields= ['name_of_api','name_of_api_vendor','dmf_status','dmf', 'dmf_version']
        widgets = {
            "user": forms.HiddenInput(),
            "name_of_api": forms.TextInput(attrs={'class': 'form-control w-50'}),
            "name_of_api_vendor": forms.TextInput(attrs={'class': 'form-control w-50'}),
            "dmf_status": forms.TextInput(attrs={'class': 'form-control w-50'}),
            "dmf": forms.TextInput(attrs={'class': 'form-control w-50'}),
            "dmf_version": forms.TextInput(attrs={'class': 'form-control w-50'}),
        }
        labels = {
            "name_of_api": "Name of API",
            "name_of_api_vendor": "Name of API Vendor",
            "dmf_status": "DMF Status",
            "dmf": "DMF No. :",
            "dmf_version": "DMF Version",
        }
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.user = self.user
        if commit:
            instance.save()
        return instance
