from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Row, Column
from .models import *
from RATools.models import *
from ckeditor.widgets import CKEditorWidget


class CustomUserCreationForm(UserCreationForm):
    helper = FormHelper()
    helper.form_method = "POST"
    helper.form_tag = False
    helper.form_show_labels = True

    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "contact_number",
            "address_line",
            "city",
            "state",
            "country",
            "pincode",
            "company_name",
            "designation",
            "description",
            "location",
            "reports",
            "role",
            "logo",
            "subscription_end_date"

        )

    def __init__(self, *args, **kwargs):
        super(CustomUserCreationForm, self).__init__(*args, **kwargs)

        for field in self.fields:
            self.fields[field].widget.attrs.update(
                {"class": "form-control form-control-user"}
            )

        self.fields["subscription_end_date"].widget = forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-control form-control-user",
            },
            format="%Y-%m-%d",
        )
        self.fields["subscription_end_date"].input_formats = ["%Y-%m-%d"]

        layout_rows = []
        field_names = [field_name for field_name in self.fields]

        row_fields = 3  # Number of fields per row

        for i in range(0, len(field_names), row_fields):
            columns = [
                Column(field, css_class="form-group col-md-4 mb-0 my-4")
                for field in field_names[i : i + row_fields]
            ]
            layout_rows.append(Row(*columns))

        self.helper.layout = Layout(*layout_rows)


class CustomUserChangeForm(UserChangeForm):
    helper = FormHelper()
    helper.form_method = "POST"
    helper.form_tag = False
    helper.form_show_labels = True

    class Meta:
        model = CustomUser
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "contact_number",
            "address_line",
            "city",
            "state",
            "country",
            "pincode",
            "company_name",
            "designation",
            "description",
            "location",
            "reports",
            "logo",
            "role",
            "subscription_end_date"
        )
        exclude = ("password",)

    def __init__(self, *args, **kwargs):
        super(CustomUserChangeForm, self).__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update(
                {"class": "form-control form-control-user"}
            )

        self.fields["subscription_end_date"].widget = forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-control form-control-user",
            },
            format="%Y-%m-%d",
        )
        self.fields["subscription_end_date"].input_formats = ["%Y-%m-%d"]
        layout_rows = []
        field_names = [field_name for field_name in self.fields if field_name != "done"]
        row_fields = 3

        for i in range(0, len(field_names), row_fields):
            columns = [
                Column(field, css_class="form-group col-md-4 mb-0 my-4")
                for field in field_names[i : i + row_fields]
            ]
            layout_rows.append(Row(*columns))

        self.helper.layout = Layout(*layout_rows)


class AssignedCheckerForm(forms.ModelForm):
    class Meta:
        model = AssignChecker
        fields = [
            "assigned_report",
            "level_report_1","level_report_2","level_report_3","level_report_4","level_report_5","level_report_6",
            "level_report_7","level_report_8","level_report_9","level_report_10","level_report_11","level_report_12",
            "level_report_13","level_report_14","level_report_15","level_report_16","level_report_17","level_report_18",
            "level_report_19","level_report_20","level_report_21","level_report_22","level_report_23","level_report_24",
            "level_report_25","level_report_26","level_report_27","level_report_28","level_report_29","level_report_30",
            "level_report_31","level_report_32","level_report_33",
            "level_report_34","level_report_35","level_report_36","level_report_37","level_report_38","level_report_39",

            "assigned_checker_level_1",
            "assigned_checker_level_2",
            "assigned_checker_level_3",
            "assigned_checker_level_4",
            "assigned_checker_level_5",
            "assigned_checker_level_6",
            "assigned_checker_level_7","view_sample_reports",
        ]
        widgets = {
            "user": forms.HiddenInput(),
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


# ANDA FORM
class AdminANDAReportForm(forms.ModelForm):
    module_name = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Enter Module Name"}
        )
    )
    chapter_name = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Enter Chapter Name"}
        )
    )
    category_name = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Enter Category Name"}
        ),
    )
    question = forms.CharField(
        widget=CKEditorWidget(
            attrs={
                "class": "form-control",
            }
        )
    )

    class Meta:
        model = ANDAReportQuestions
        fields = ["module_name", "chapter_name", "category_name", "question"]


# VP Form
class AdminVPReportForm(forms.ModelForm):
    category = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Enter Category"}
        )
    )
    sub_category = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Enter Sub Category"}
        )
    )
    sub_sub_category = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Enter Sub Sub Category"}
        ),
    )
    question = forms.CharField(
        widget=CKEditorWidget(
            attrs={
                "class": "form-control",
            }
        )
    )

    class Meta:
        model = VPReportQuestions
        fields = ["category", "sub_category", "sub_sub_category", "question"]


# DMF CA QuestionForm
class DMFCAQuestionForm(forms.ModelForm):
    module = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Enter Module"}
        )
    )
    category = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Enter Category"}
        )
    )
    sub_category = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Enter Sub Category"}
        ),
    )
    ectd_no = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Enter eCTD No"}
        )
    )
    ectd_sub_category = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Enter eCTD Sub Category"}
        )
    )
    question = forms.CharField(
        widget=CKEditorWidget(
            attrs={
                "class": "form-control",
            }
        )
    )
    note = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control"}
        )
    )

    class Meta:
        model = DMFCATableQuestion
        fields = [
            "module",
            "category",
            "sub_category",
            "ectd_no",
            "ectd_sub_category",
            "question",
            "note",
        ]


# DMF Review Table
class DMFReviewTableQuestionForm(forms.ModelForm):
    module = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Enter Module"}
        )
    )
    category = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Enter Category"}
        )
    )
    question = forms.CharField(
        widget=CKEditorWidget(
            attrs={
                "class": "form-control",
            }
        )
    )

    class Meta:
        model = DMFReviewTableQuestion
        fields = ["module", "category", "question"]


# General
class AdminGeneralReportForm(forms.ModelForm):
    category = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Enter Category"}
        )
    )
    sub_category = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Enter Sub Category"}
        )
    )
    question = forms.CharField(
        widget=CKEditorWidget(
            attrs={
                "class": "form-control",
            }
        )
    )

    class Meta:
        model = GeneralReportQuestions
        fields = ["category", "sub_category", "question"]
