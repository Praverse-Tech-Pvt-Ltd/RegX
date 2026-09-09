from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import auth
from .forms import *
from django.db import transaction
from RATools.models import *
from .forms import *
from django.contrib import messages
from django.contrib.auth.decorators import login_required
import uuid

from django.shortcuts import render, redirect, get_object_or_404
from decouple import config
import logging

from . import regx_auth

logger = logging.getLogger(__name__)

# Create your views here.
def homepage(request):
    return render(request, "index.html")


@login_required(login_url="/adminmaster/login/")
def adminbase(request):
    return render(request, "AdminMaster/AdminMasterBase.html")


# def login(request):
#     if request.method == "GET":
#         return render(request, "AdminMaster/login.html")
#     elif request.method == "POST":
#         username = request.POST["username"]
#         password = request.POST["password"]
#         footprinte_ID = request.POST.get("footprint_ID")
#         print(footprinte_ID)
#         user = auth.authenticate(username=username, password=password)
#         if user is not None:
#             if config("SERVER") != "PRODUCTION":
#                 auth.login(request, user)
#             else:
#                 if user.footprint_ID == "No":
#                     print("User does not have a footprint ID")
#                     user.footprint_ID = footprinte_ID
#                     user.save()
#                     auth.login(request, user)
#                 else:
#                     if user.footprint_ID != footprinte_ID:
#                         print("Footprint ID does not match")
#                         return render(request, "AdminMaster/login.html", {"message": "Please Login from your registered device"})
#                     else:
#                         print("Footprint ID matches")
#                         auth.login(request, user)
#             if user.role == "admin":
#                 return redirect("/adminmaster/adminbase")
#             else:
#                 return redirect(("/ratools/"))
#         else:
#             message = "Invalid Crendential"
#             return render(request, "AdminMaster/login.html", {"message": message})




def _authenticate(username, password):
    """Check credentials against REGX first, then against this application.

    REGX is the authority: a person with a REGX account signs in here with the
    same email and password they use at /signin, and gets a `CustomUser`
    mirroring their REGX role. See `AdminMaster.regx_auth`.

    The local check stays as a fallback for the accounts REGX does not know --
    the Django superuser and any pre-existing company account -- and for the
    case where REGX is unreachable. It cannot be used to bypass REGX: mirrored
    accounts are saved with an unusable password, so `auth.authenticate` can
    never succeed for one.
    """
    try:
        user = regx_auth.authenticate(username, password)
    except regx_auth.RegxUnavailable as exc:
        # An outage must not lock out the accounts this application can still
        # verify on its own, so fall through rather than fail the login.
        logger.warning("REGX auth unavailable, falling back to local: %s", exc)
    else:
        if user is not None:
            return user

    return auth.authenticate(username=username, password=password)


def login(request):
    if request.method == "GET":
        return render(request, "AdminMaster/login.html")

    elif request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]
        user = _authenticate(username, password)

        if user is not None:
            cookie_token = request.COOKIES.get("device_token")

            if config("SERVER") != "PRODUCTION" or user.internal_team:
                auth.login(request, user)
                response = redirect("/adminmaster/adminbase" if user.role == "admin" else "/ratools/")
                return response
            else:
                # Production mode
                if user.login_token == "No":
                    print("Prod: First time login — setting device_token")
                    user.login_token = str(uuid.uuid4())
                    user.save()
                    auth.login(request, user)
                    response = redirect("/adminmaster/adminbase" if user.role == "admin" else "/ratools/")
                    response.set_cookie("device_token", user.login_token, max_age=10 * 365 * 24 * 60 * 60)
                    return response
                else:
                    if cookie_token != user.login_token:
                        print("Prod: Device token mismatch")
                        return render(request, "AdminMaster/login.html", {
                            "message": "Please login from your registered device."
                        })
                    else:
                        print("Prod: Device token matched")
                        auth.login(request, user)
                        response = redirect("/adminmaster/adminbase" if user.role == "admin" else "/ratools/")
                        response.set_cookie("device_token", user.login_token, max_age=10 * 365 * 24 * 60 * 60)
                        return response

        else:
            return render(request, "AdminMaster/login.html", {
                "message": "Invalid Credential"
            })


def logout(request):
    auth.logout(request)
    return redirect("/")


@login_required(login_url="/adminmaster/login/")
def view_users(request):
    logged_in_user = request.user
    show_flag = logged_in_user.role == "admin"
    data = CustomUser.objects.all()
    edit_url = "/adminmaster/edit_user"
    add_url = "/adminmaster/add_user"
    delete_url = "/adminmaster/delete_user"
    return render(
        request,
        "AdminMaster/AdminMasterBaseShow.html",
        {
            "data": data,
            "page_heading": "Users",
            "edit_url": edit_url,
            "add_url": add_url,
            "delete_url": delete_url,
            "button_heading": "User",
            "table_headers": ["First Name", "Last Name", "Role", "Actions"],
            "show_flag": show_flag,
            "active": "user",
            "form": CustomUserCreationForm(),
            "form_2": AssignedCheckerForm(),
        },
    )


@login_required(login_url="/adminmaster/login/")
def add_user(request):
    logged_in_user = request.user
    if request.method == "POST":
        form = CustomUserCreationForm(request.POST, request.FILES)
        form_2 = AssignedCheckerForm(request.POST)

        if form.is_valid() and form_2.is_valid():
            with transaction.atomic():
                new_user = form.save()
                assigned_checker_instance = form_2.save(commit=False)
                assigned_checker_instance.user = new_user
                assigned_checker_instance.save()
                form_2.save_m2m()  # Save the ManyToMany relationships

            return redirect("/adminmaster/view_users")
        # else:
        #     print(form.errors,form_2.errors)
        return redirect("/adminmaster/view_users")


@login_required(login_url="/adminmaster/login/")
def edit_user(request, id):
    user = get_object_or_404(CustomUser, id=id)
    assign_checker = AssignChecker.objects.filter(user=user).first()

    if request.method == "POST":
        form = CustomUserChangeForm(request.POST, request.FILES, instance=user)
        form_2 = AssignedCheckerForm(request.POST, instance=assign_checker)

        if form.is_valid() and form_2.is_valid():
            with transaction.atomic():
                form.save()
                assigned_checker_instance = form_2.save(commit=False)
                assigned_checker_instance.user = user
                assigned_checker_instance.save()
                form_2.save_m2m()
            return redirect("/adminmaster/view_users")
        else:
            print(form.errors, form_2.errors)
    else:
        form = CustomUserChangeForm(instance=user)
        form_2 = AssignedCheckerForm(instance=assign_checker)

    return render(request, "AdminMaster/profile.html", {"form": form, "form_2": form_2})


@login_required(login_url="/adminmaster/login/")
def delete_user(request, id):
    user = get_object_or_404(CustomUser, id=id)
    user.delete()
    return redirect("/adminmaster/view_users")


@login_required(login_url="/adminmaster/login/")
def adminmasterbase(request):
    return render(request, "AdminMaster/AdminMasterBase.html")


# views.py
@login_required(login_url="/adminmaster/login/")
def show_anda_mdi_dpi(request):
    REPORT_NAME = "Metered Dose Inhaler (MDI) and Dry Powder Inhaler (DPI) Dosage Form"

    reports = ANDAReportQuestions.objects.filter(report_name=REPORT_NAME)

    if request.method == "POST":
        form = AdminANDAReportForm(request.POST)
        if form.is_valid():
            new_report = form.save(commit=False)
            new_report.report_name = REPORT_NAME
            new_report.save()
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AdminANDAReportForm()

    # edit_form = AdminANDAReportForm()

    context = {
        "page_heading": "MDI & DPI Checklist Management",
        "table_headers": [
            "Module Name",
            "Chapter Name",
            "Category",
            "Question",
            "Actions",
        ],
        "reports": reports,
        "form": form,
        "action": "/adminmaster/add_anda_mdi_and_dpi/",
        "edit_url": "/adminmaster/edit_anda_mdi_and_dpi",
        "delete_url": "/adminmaster/delete_anda_mdi_and_dpit",
        "modal_title": "MDI & DPI Checklist Overview",
        "modal_body_content": "This section contains checklists for Metered Dose Inhalers (MDI) and Dry Powder Inhalers (DPI).",
    }

    return render(request, "AdminMaster/ANDA/AndaEditForms.html", context)


@login_required(login_url="/adminmaster/login/")
def add_anda_mdi_and_dpi(request):
    if request.method == "POST":
        try:
            form = AdminANDAReportForm(request.POST)
            if form.is_valid():
                new_report = form.save(commit=False)
                new_report.report_name = "Metered Dose Inhaler (MDI) and Dry Powder Inhaler (DPI) Dosage Form"
                new_report.save()
            else:
                messages.error(
                    request, "Form validation failed. Please check your inputs."
                )
        except Exception as e:
            messages.error(request, f"Error saving report: {str(e)}")

    return redirect("/adminmaster/show_anda_mdi_dpi")


@login_required(login_url="/adminmaster/login/")
def edit_anda_mdi_and_dpi(request, id):
    report = ANDAReportQuestions.objects.get(id=id)
    if request.method == "POST":
        try:
            # report_id = request.POST.get('report_id')
            form = AdminANDAReportForm(request.POST, instance=report)
            if form.is_valid():
                form.save()
            else:
                messages.error(request, "Please correct the errors below.")
        except ANDAReportQuestions.DoesNotExist:
            messages.error(request, "Report not found!")
        except Exception as e:
            messages.error(request, f"Error updating report: {str(e)}")
    else:
        form = AdminANDAReportForm(instance=report)
    return redirect("/adminmaster/show_anda_mdi_dpi")


@login_required(login_url="/adminmaster/login/")
def delete_anda_mdi_and_dpit(request, id):
    try:
        report = ANDAReportQuestions.objects.get(id=id)
        report.delete()
    except ANDAReportQuestions.DoesNotExist:
        messages.error(request, "Report not found!")
    return redirect("/adminmaster/show_anda_mdi_dpi")


# Nasal Spray Inhalation
@login_required(login_url="/adminmaster/login/")
def show_anda_nasalspray_inhalation_checklist(request):
    REPORT_NAME = "Nasal Spray  & Inhalation Dosage"

    reports = ANDAReportQuestions.objects.filter(report_name=REPORT_NAME)

    if request.method == "POST":
        form = AdminANDAReportForm(request.POST)
        if form.is_valid():
            new_report = form.save(commit=False)
            new_report.report_name = REPORT_NAME
            new_report.save()
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AdminANDAReportForm()

    context = {
        "page_heading": "Nasal Spray & Inhalation Dosage Checklist Management",
        "table_headers": [
            "Module Name",
            "Chapter Name",
            "Category",
            "Question",
            "Actions",
        ],
        "reports": reports,
        "form": form,
        "action": "/adminmaster/add_anda_nasalspray_inhalation_report/",
        "edit_url": "/adminmaster/edit_anda_nasalspray_inhalation_report",
        "delete_url": "/adminmaster/delete_anda_nasalspray_inhalation_report",
        "modal_title": "Nasal Spray & Inhalation Dosage Overview",
        "modal_body_content": "This section contains checklists for Nasal Spray and Inhalation Dosages.",
    }

    return render(request, "AdminMaster/ANDA/AndaEditForms.html", context)


@login_required(login_url="/adminmaster/login/")
def add_anda_nasalspray_inhalation_report(request):
    if request.method == "POST":
        try:
            form = AdminANDAReportForm(request.POST)
            if form.is_valid():
                new_report = form.save(commit=False)
                new_report.report_name = "Nasal Spray  & Inhalation Dosage"
                new_report.save()
            else:
                messages.error(
                    request, "Form validation failed. Please check your inputs."
                )
        except Exception as e:
            messages.error(request, f"Error saving report: {str(e)}")

    return redirect("/adminmaster/show_anda_nasalspray_inhalation_checklist")


@login_required(login_url="/adminmaster/login/")
def edit_anda_nasalspray_inhalation_report(request, id):
    if request.method == "POST":
        try:
            report = ANDAReportQuestions.objects.get(id=id)

            form = AdminANDAReportForm(request.POST, instance=report)
            if form.is_valid():
                form.save()
                messages.success(request, "Report updated successfully!")
            else:
                messages.error(request, "Please correct the errors below.")

        except ANDAReportQuestions.DoesNotExist:
            messages.error(request, "Report not found!")
        except Exception as e:
            messages.error(request, f"Error updating report: {str(e)}")

    return redirect("/adminmaster/show_anda_nasalspray_inhalation_checklist")


@login_required(login_url="/adminmaster/login/")
def delete_anda_nasalspray_inhalation_report(request, id):
    try:
        report = ANDAReportQuestions.objects.get(id=id)
        report.delete()
    except ANDAReportQuestions.DoesNotExist:
        messages.error(request, "Report not found!")

    return redirect("/adminmaster/show_anda_nasalspray_inhalation_checklist")


# OPHTHALMIC DOSAGE FORM
@login_required(login_url="/adminmaster/login/")
def show_anda_ophthalmic_dosage_table(request):
    REPORT_NAME = "Ophthalmic Dosage"

    reports = ANDAReportQuestions.objects.filter(report_name=REPORT_NAME)

    if request.method == "POST":
        form = AdminANDAReportForm(request.POST)
        if form.is_valid():
            new_report = form.save(commit=False)
            new_report.report_name = REPORT_NAME
            new_report.save()
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AdminANDAReportForm()

    context = {
        "page_heading": "Ophthalmic Dosage Checklist Management",
        "table_headers": [
            "Module Name",
            "Chapter Name",
            "Category",
            "Question",
            "Actions",
        ],
        "reports": reports,
        "form": form,
        "action": "/adminmaster/add_anda_ophthalmic_dosage/",
        "edit_url": "/adminmaster/edit_anda_ophthalmic_dosage",
        "delete_url": "/adminmaster/delete_anda_ophthalmic_dosage",
        "modal_title": "Ophthalmic Dosage Checklist Overview",
        "modal_body_content": "This section contains checklists for Ophthalmic Dosage Forms.",
    }

    return render(request, "AdminMaster/ANDA/AndaEditForms.html", context)


@login_required(login_url="/adminmaster/login/")
def add_anda_ophthalmic_dosage(request):
    if request.method == "POST":
        try:
            form = AdminANDAReportForm(request.POST)
            if form.is_valid():
                new_report = form.save(commit=False)
                new_report.report_name = "Ophthalmic Dosage"
                new_report.save()
            else:
                messages.error(
                    request, "Form validation failed. Please check your inputs."
                )
        except Exception as e:
            messages.error(request, f"Error saving report: {str(e)}")

    return redirect("/adminmaster/show_anda_ophthalmic_dosage_table")


@login_required(login_url="/adminmaster/login/")
def edit_anda_ophthalmic_dosage(request, id):
    report = ANDAReportQuestions.objects.get(id=id)
    if request.method == "POST":
        try:
            form = AdminANDAReportForm(request.POST, instance=report)
            if form.is_valid():
                form.save()
            else:
                messages.error(request, "Please correct the errors below.")
        except ANDAReportQuestions.DoesNotExist:
            messages.error(request, "Report not found!")
        except Exception as e:
            messages.error(request, f"Error updating report: {str(e)}")
    else:
        form = AdminANDAReportForm(instance=report)
    return redirect("/adminmaster/show_anda_ophthalmic_dosage_table")


@login_required(login_url="/adminmaster/login/")
def delete_anda_ophthalmic_dosage(request, id):
    try:
        report = ANDAReportQuestions.objects.get(id=id)
        report.delete()
    except ANDAReportQuestions.DoesNotExist:
        messages.error(request, "Report not found!")
    return redirect("/adminmaster/show_anda_ophthalmic_dosage_table")


# PARENTERAL DOSAGE FORM
@login_required(login_url="/adminmaster/login/")
def show_anda_parenteral_dosage_table(request):
    REPORT_NAME = "Parenteral Dosage"

    reports = ANDAReportQuestions.objects.filter(report_name=REPORT_NAME)

    if request.method == "POST":
        form = AdminANDAReportForm(request.POST)
        if form.is_valid():
            new_report = form.save(commit=False)
            new_report.report_name = REPORT_NAME
            new_report.save()
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AdminANDAReportForm()

    context = {
        "page_heading": "Parenteral Dosage Checklist Management",
        "table_headers": [
            "Module Name",
            "Chapter Name",
            "Category",
            "Question",
            "Actions",
        ],
        "reports": reports,
        "form": form,
        "action": "/adminmaster/add_anda_parenteral_dosage/",
        "edit_url": "/adminmaster/edit_anda_parenteral_dosage",
        "delete_url": "/adminmaster/delete_anda_parenteral_dosage",
        "modal_title": "Parenteral Dosage Checklist Overview",
        "modal_body_content": "This section contains checklists for Parenteral Dosage Forms.",
    }

    return render(request, "AdminMaster/ANDA/AndaEditForms.html", context)


@login_required(login_url="/adminmaster/login/")
def add_anda_parenteral_dosage(request):
    if request.method == "POST":
        try:
            form = AdminANDAReportForm(request.POST)
            if form.is_valid():
                new_report = form.save(commit=False)
                new_report.report_name = "Parenteral Dosage"
                new_report.save()
            else:
                messages.error(
                    request, "Form validation failed. Please check your inputs."
                )
        except Exception as e:
            messages.error(request, f"Error saving report: {str(e)}")

    return redirect("/adminmaster/show_anda_parenteral_dosage_table")


@login_required(login_url="/adminmaster/login/")
def edit_anda_parenteral_dosage(request, id):
    report = ANDAReportQuestions.objects.get(id=id)
    if request.method == "POST":
        try:
            form = AdminANDAReportForm(request.POST, instance=report)
            if form.is_valid():
                form.save()
            else:
                messages.error(request, "Please correct the errors below.")
        except ANDAReportQuestions.DoesNotExist:
            messages.error(request, "Report not found!")
        except Exception as e:
            messages.error(request, f"Error updating report: {str(e)}")
    else:
        form = AdminANDAReportForm(instance=report)
    return redirect("/adminmaster/show_anda_parenteral_dosage_table")


@login_required(login_url="/adminmaster/login/")
def delete_anda_parenteral_dosage(request, id):
    try:
        report = ANDAReportQuestions.objects.get(id=id)
        report.delete()
    except ANDAReportQuestions.DoesNotExist:
        messages.error(request, "Report not found!")
    return redirect("/adminmaster/show_anda_parenteral_dosage_table")


# SEMI SOLID TOPICAL DOSAGE FORM
@login_required(login_url="/adminmaster/login/")
def show_anda_semi_solid_topical_dosage_table(request):
    REPORT_NAME = "Semi Solid Dosage Form"

    reports = ANDAReportQuestions.objects.filter(report_name=REPORT_NAME)

    if request.method == "POST":
        form = AdminANDAReportForm(request.POST)
        if form.is_valid():
            new_report = form.save(commit=False)
            new_report.report_name = REPORT_NAME
            new_report.save()
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AdminANDAReportForm()

    context = {
        "page_heading": "Semi Solid Topical Dosage Checklist Management",
        "table_headers": [
            "Module Name",
            "Chapter Name",
            "Category",
            "Question",
            "Actions",
        ],
        "reports": reports,
        "form": form,
        "action": "/adminmaster/add_anda_semi_solid_topical_dosage/",
        "edit_url": "/adminmaster/edit_anda_semi_solid_topical_dosage",
        "delete_url": "/adminmaster/delete_anda_semi_solid_topical_dosage",
        "modal_title": "Semi Solid Topical Dosage Checklist Overview",
        "modal_body_content": "This section contains checklists for Semi Solid Topical Dosage Forms.",
    }

    return render(request, "AdminMaster/ANDA/AndaEditForms.html", context)


@login_required(login_url="/adminmaster/login/")
def add_anda_semi_solid_topical_dosage(request):
    if request.method == "POST":
        try:
            form = AdminANDAReportForm(request.POST)
            if form.is_valid():
                new_report = form.save(commit=False)
                new_report.report_name = "Semi Solid Dosage Form"
                new_report.save()
            else:
                messages.error(
                    request, "Form validation failed. Please check your inputs."
                )
        except Exception as e:
            messages.error(request, f"Error saving report: {str(e)}")

    return redirect("/adminmaster/show_anda_semi_solid_topical_dosage_table")


@login_required(login_url="/adminmaster/login/")
def edit_anda_semi_solid_topical_dosage(request, id):
    report = ANDAReportQuestions.objects.get(id=id)
    if request.method == "POST":
        try:
            form = AdminANDAReportForm(request.POST, instance=report)
            if form.is_valid():
                form.save()
            else:
                messages.error(request, "Please correct the errors below.")
        except ANDAReportQuestions.DoesNotExist:
            messages.error(request, "Report not found!")
        except Exception as e:
            messages.error(request, f"Error updating report: {str(e)}")
    else:
        form = AdminANDAReportForm(instance=report)
    return redirect("/adminmaster/show_anda_semi_solid_topical_dosage_table")


@login_required(login_url="/adminmaster/login/")
def delete_anda_semi_solid_topical_dosage(request, id):
    try:
        report = ANDAReportQuestions.objects.get(id=id)
        report.delete()
    except ANDAReportQuestions.DoesNotExist:
        messages.error(request, "Report not found!")
    return redirect("/adminmaster/show_anda_semi_solid_topical_dosage_table")


# SOLID ORAL DOSAGE FORM
@login_required(login_url="/adminmaster/login/")
def show_anda_solid_oral_dosage_table(request):
    REPORT_NAME = "Solid Oral Dosage"

    reports = ANDAReportQuestions.objects.filter(report_name=REPORT_NAME)

    if request.method == "POST":
        form = AdminANDAReportForm(request.POST)
        if form.is_valid():
            new_report = form.save(commit=False)
            new_report.report_name = REPORT_NAME
            new_report.save()
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AdminANDAReportForm()

    context = {
        "page_heading": "Solid Oral Dosage Checklist Management",
        "table_headers": [
            "Module Name",
            "Chapter Name",
            "Category",
            "Question",
            "Actions",
        ],
        "reports": reports,
        "form": form,
        "action": "/adminmaster/add_anda_solid_oral_dosage/",
        "edit_url": "/adminmaster/edit_anda_solid_oral_dosage",
        "delete_url": "/adminmaster/delete_anda_solid_oral_dosage",
        "modal_title": "Solid Oral Dosage Checklist Overview",
        "modal_body_content": "This section contains checklists for Solid Oral Dosage Forms.",
    }

    return render(request, "AdminMaster/ANDA/AndaEditForms.html", context)


@login_required(login_url="/adminmaster/login/")
def add_anda_solid_oral_dosage(request):
    if request.method == "POST":
        try:
            form = AdminANDAReportForm(request.POST)
            if form.is_valid():
                new_report = form.save(commit=False)
                new_report.report_name = "Solid Oral Dosage"
                new_report.save()
            else:
                messages.error(
                    request, "Form validation failed. Please check your inputs."
                )
        except Exception as e:
            messages.error(request, f"Error saving report: {str(e)}")

    return redirect("/adminmaster/show_anda_solid_oral_dosage_table")


@login_required(login_url="/adminmaster/login/")
def edit_anda_solid_oral_dosage(request, id):
    report = ANDAReportQuestions.objects.get(id=id)
    if request.method == "POST":
        try:
            form = AdminANDAReportForm(request.POST, instance=report)
            if form.is_valid():
                form.save()
            else:
                messages.error(request, "Please correct the errors below.")
        except ANDAReportQuestions.DoesNotExist:
            messages.error(request, "Report not found!")
        except Exception as e:
            messages.error(request, f"Error updating report: {str(e)}")
    else:
        form = AdminANDAReportForm(instance=report)
    return redirect("/adminmaster/show_anda_solid_oral_dosage_table")


@login_required(login_url="/adminmaster/login/")
def delete_anda_solid_oral_dosage(request, id):
    try:
        report = ANDAReportQuestions.objects.get(id=id)
        report.delete()
    except ANDAReportQuestions.DoesNotExist:
        messages.error(request, "Report not found!")
    return redirect("/adminmaster/show_anda_solid_oral_dosage_table")


# TRANSDERMAL DOSAGE FORM
@login_required(login_url="/adminmaster/login/")
def show_anda_transdermal_dosage_table(request):
    REPORT_NAME = "Transdermal"

    reports = ANDAReportQuestions.objects.filter(report_name=REPORT_NAME)

    if request.method == "POST":
        form = AdminANDAReportForm(request.POST)
        if form.is_valid():
            new_report = form.save(commit=False)
            new_report.report_name = REPORT_NAME
            new_report.save()
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AdminANDAReportForm()

    context = {
        "page_heading": "Transdermal Dosage Checklist Management",
        "table_headers": [
            "Module Name",
            "Chapter Name",
            "Category",
            "Question",
            "Actions",
        ],
        "reports": reports,
        "form": form,
        "action": "/adminmaster/add_anda_transdermal_dosage/",
        "edit_url": "/adminmaster/edit_anda_transdermal_dosage",
        "delete_url": "/adminmaster/delete_anda_transdermal_dosage",
        "modal_title": "Transdermal Dosage Checklist Overview",
        "modal_body_content": "This section contains checklists for Transdermal Dosage Forms.",
    }

    return render(request, "AdminMaster/ANDA/AndaEditForms.html", context)


@login_required(login_url="/adminmaster/login/")
def add_anda_transdermal_dosage(request):
    if request.method == "POST":
        try:
            form = AdminANDAReportForm(request.POST)
            if form.is_valid():
                new_report = form.save(commit=False)
                new_report.report_name = "Transdermal"
                new_report.save()
            else:
                messages.error(
                    request, "Form validation failed. Please check your inputs."
                )
        except Exception as e:
            messages.error(request, f"Error saving report: {str(e)}")

    return redirect("/adminmaster/show_anda_transdermal_dosage_table")


@login_required(login_url="/adminmaster/login/")
def edit_anda_transdermal_dosage(request, id):
    report = ANDAReportQuestions.objects.get(id=id)
    if request.method == "POST":
        try:
            form = AdminANDAReportForm(request.POST, instance=report)
            if form.is_valid():
                form.save()
            else:
                messages.error(request, "Please correct the errors below.")
        except ANDAReportQuestions.DoesNotExist:
            messages.error(request, "Report not found!")
        except Exception as e:
            messages.error(request, f"Error updating report: {str(e)}")
    else:
        form = AdminANDAReportForm(instance=report)
    return redirect("/adminmaster/show_anda_transdermal_dosage_table")


@login_required(login_url="/adminmaster/login/")
def delete_anda_transdermal_dosage(request, id):
    try:
        report = ANDAReportQuestions.objects.get(id=id)
        report.delete()
    except ANDAReportQuestions.DoesNotExist:
        messages.error(request, "Report not found!")
    return redirect("/adminmaster/show_anda_transdermal_dosage_table")


# GENERAL ANDA
@login_required(login_url="/adminmaster/login/")
def show_anda_general_table(request):
    REPORT_NAME = "General ANDA"

    reports = ANDAReportQuestions.objects.filter(report_name=REPORT_NAME)

    if request.method == "POST":
        form = AdminANDAReportForm(request.POST)
        if form.is_valid():
            new_report = form.save(commit=False)
            new_report.report_name = REPORT_NAME
            new_report.save()
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AdminANDAReportForm()

    context = {
        "page_heading": "General ANDA Checklist Management",
        "table_headers": [
            "Module Name",
            "Chapter Name",
            "Category",
            "Question",
            "Actions",
        ],
        "reports": reports,
        "form": form,
        "action": "/adminmaster/add_anda_general/",
        "edit_url": "/adminmaster/edit_anda_general",
        "delete_url": "/adminmaster/delete_anda_general",
        "modal_title": "General ANDA Checklist Overview",
        "modal_body_content": "This section contains checklists for General ANDA requirements.",
    }

    return render(request, "AdminMaster/ANDA/AndaEditForms.html", context)


@login_required(login_url="/adminmaster/login/")
def add_anda_general(request):
    if request.method == "POST":
        try:
            form = AdminANDAReportForm(request.POST)
            if form.is_valid():
                new_report = form.save(commit=False)
                new_report.report_name = "General ANDA"
                new_report.save()
            else:
                messages.error(
                    request, "Form validation failed. Please check your inputs."
                )
        except Exception as e:
            messages.error(request, f"Error saving report: {str(e)}")

    return redirect("/adminmaster/show_anda_general_table")


@login_required(login_url="/adminmaster/login/")
def edit_anda_general(request, id):
    report = ANDAReportQuestions.objects.get(id=id)
    if request.method == "POST":
        try:
            form = AdminANDAReportForm(request.POST, instance=report)
            if form.is_valid():
                form.save()
            else:
                messages.error(request, "Please correct the errors below.")
        except ANDAReportQuestions.DoesNotExist:
            messages.error(request, "Report not found!")
        except Exception as e:
            messages.error(request, f"Error updating report: {str(e)}")
    else:
        form = AdminANDAReportForm(instance=report)
    return redirect("/adminmaster/show_anda_general_table")


@login_required(login_url="/adminmaster/login/")
def delete_anda_general(request, id):
    try:
        report = ANDAReportQuestions.objects.get(id=id)
        report.delete()
    except ANDAReportQuestions.DoesNotExist:
        messages.error(request, "Report not found!")
    return redirect("/adminmaster/show_anda_general_table")


# VP
@login_required(login_url="/adminmaster/login/")
def show_vp_mdi_dpi(request):
    REPORT_NAME = "VP MDI and DPI Report"

    reports = VPReportQuestions.objects.filter(report_name=REPORT_NAME)

    if request.method == "POST":
        form = AdminVPReportForm(request.POST)
        if form.is_valid():
            new_report = form.save(commit=False)
            new_report.report_name = REPORT_NAME
            new_report.save()
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AdminVPReportForm()

    context = {
        "page_heading": "VP MDI & DPI Report Management",
        "table_headers": [
            "Category",
            "Sub Category",
            "Sub Sub Category",
            "Question",
            "Actions",
        ],
        "reports": reports,
        "form": form,
        "action": "/adminmaster/add_vp_mdi_and_dpi/",
        "edit_url": "/adminmaster/edit_vp_mdi_and_dpi",
        "delete_url": "/adminmaster/delete_vp_mdi_and_dpi",
        "modal_title": "VP MDI & DPI Report Overview",
        "modal_body_content": "This section contains reports for VP MDI and DPI management.",
    }

    return render(request, "AdminMaster/VP/VPEditForm.html", context)


@login_required(login_url="/adminmaster/login/")
def add_vp_mdi_and_dpi(request):
    if request.method == "POST":
        try:
            form = AdminVPReportForm(request.POST)
            if form.is_valid():
                new_report = form.save(commit=False)
                new_report.report_name = "VP MDI and DPI Report"
                new_report.save()
            else:
                messages.error(
                    request, "Form validation failed. Please check your inputs."
                )
        except Exception as e:
            messages.error(request, f"Error saving report: {str(e)}")

    return redirect("/adminmaster/show_vp_mdi_dpi")


@login_required(login_url="/adminmaster/login/")
def edit_vp_mdi_and_dpi(request, id):
    report = VPReportQuestions.objects.get(id=id)
    if request.method == "POST":
        try:
            form = AdminVPReportForm(request.POST, instance=report)
            if form.is_valid():
                form.save()
            else:
                messages.error(request, "Please correct the errors below.")
        except VPReportQuestions.DoesNotExist:
            messages.error(request, "Report not found!")
        except Exception as e:
            messages.error(request, f"Error updating report: {str(e)}")

    return redirect("/adminmaster/show_vp_mdi_dpi")


@login_required(login_url="/adminmaster/login/")
def delete_vp_mdi_and_dpi(request, id):
    try:
        report = VPReportQuestions.objects.get(id=id)
        report.delete()
    except VPReportQuestions.DoesNotExist:
        messages.error(request, "Report not found!")
    return redirect("/adminmaster/show_vp_mdi_dpi")


# Nasal and Inhalation
@login_required(login_url="/adminmaster/login/")
def show_vp_nasal_inhalation(request):
    report_name = "VP Nasal and Inhalation Report"
    reports = VPReportQuestions.objects.filter(report_name=report_name)

    if request.method == "POST":
        form = AdminVPReportForm(request.POST)
        if form.is_valid():
            new_report = form.save(commit=False)
            new_report.report_name = report_name
            new_report.save()
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AdminVPReportForm()

    context = {
        "page_heading": "VP Nasal & Inhalation Report Management",
        "table_headers": [
            "Category",
            "Sub Category",
            "Sub Sub Category",
            "Question",
            "Actions",
        ],
        "reports": reports,
        "form": form,
        "action": "/adminmaster/add_vp_nasal_inhalation/",
        "edit_url": "/adminmaster/edit_vp_nasal_inhalation",
        "delete_url": "/adminmaster/delete_vp_nasal_inhalation",
        "modal_title": "VP Nasal & Inhalation Report Overview",
        "modal_body_content": "This section contains reports for VP Nasal and Inhalation management.",
    }
    return render(request, "AdminMaster/VP/VPEditForm.html", context)


@login_required(login_url="/adminmaster/login/")
def add_vp_nasal_inhalation(request):
    if request.method == "POST":
        try:
            form = AdminVPReportForm(request.POST)
            if form.is_valid():
                new_report = form.save(commit=False)
                new_report.report_name = "VP Nasal and Inhalation Report"
                new_report.save()
            else:
                messages.error(
                    request, "Form validation failed. Please check your inputs."
                )
        except Exception as e:
            messages.error(request, f"Error saving report: {str(e)}")
    return redirect("/adminmaster/show_vp_nasal_inhalation")


@login_required(login_url="/adminmaster/login/")
def edit_vp_nasal_inhalation(request, id):
    report = VPReportQuestions.objects.get(id=id)
    if request.method == "POST":
        try:
            form = AdminVPReportForm(request.POST, instance=report)
            if form.is_valid():
                form.save()
            else:
                messages.error(request, "Please correct the errors below.")
        except VPReportQuestions.DoesNotExist:
            messages.error(request, "Report not found!")
        except Exception as e:
            messages.error(request, f"Error updating report: {str(e)}")
    return redirect("/adminmaster/show_vp_nasal_inhalation")


@login_required(login_url="/adminmaster/login/")
def delete_vp_nasal_inhalation(request, id):
    try:
        report = VPReportQuestions.objects.get(id=id)
        report.delete()
    except VPReportQuestions.DoesNotExist:
        messages.error(request, "Report not found!")
    return redirect("/adminmaster/show_vp_nasal_inhalation")


# Ophthalmic
@login_required(login_url="/adminmaster/login/")
def show_vp_ophthalmic(request):
    report_name = "VP Ophthalmic Report"
    reports = VPReportQuestions.objects.filter(report_name=report_name)

    if request.method == "POST":
        form = AdminVPReportForm(request.POST)
        if form.is_valid():
            new_report = form.save(commit=False)
            new_report.report_name = report_name
            new_report.save()
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AdminVPReportForm()

    context = {
        "page_heading": "VP Ophthalmic Report Management",
        "table_headers": [
            "Category",
            "Sub Category",
            "Sub Sub Category",
            "Question",
            "Actions",
        ],
        "reports": reports,
        "form": form,
        "action": "/adminmaster/add_vp_ophthalmic/",
        "edit_url": "/adminmaster/edit_vp_ophthalmic",
        "delete_url": "/adminmaster/delete_vp_ophthalmic",
        "modal_title": "VP Ophthalmic Report Overview",
        "modal_body_content": "This section contains reports for VP Ophthalmic management.",
    }
    return render(request, "AdminMaster/VP/VPEditForm.html", context)


@login_required(login_url="/adminmaster/login/")
def add_vp_ophthalmic(request):
    if request.method == "POST":
        try:
            form = AdminVPReportForm(request.POST)
            if form.is_valid():
                new_report = form.save(commit=False)
                new_report.report_name = "VP Ophthalmic Report"
                new_report.save()
            else:
                messages.error(
                    request, "Form validation failed. Please check your inputs."
                )
        except Exception as e:
            messages.error(request, f"Error saving report: {str(e)}")
    return redirect("/adminmaster/show_vp_ophthalmic")


@login_required(login_url="/adminmaster/login/")
def edit_vp_ophthalmic(request, id):
    report = VPReportQuestions.objects.get(id=id)
    if request.method == "POST":
        try:
            form = AdminVPReportForm(request.POST, instance=report)
            if form.is_valid():
                form.save()
            else:
                messages.error(request, "Please correct the errors below.")
        except VPReportQuestions.DoesNotExist:
            messages.error(request, "Report not found!")
        except Exception as e:
            messages.error(request, f"Error updating report: {str(e)}")
    return redirect("/adminmaster/show_vp_ophthalmic")


@login_required(login_url="/adminmaster/login/")
def delete_vp_ophthalmic(request, id):
    try:
        report = VPReportQuestions.objects.get(id=id)
        report.delete()
    except VPReportQuestions.DoesNotExist:
        messages.error(request, "Report not found!")
    return redirect("/adminmaster/show_vp_ophthalmic")


# Liquid Orals
@login_required(login_url="/adminmaster/login/")
def show_vp_liquidorals_table(request):
    REPORT_NAME = "VP - Oral Liquids Report"
    reports = VPReportQuestions.objects.filter(report_name=REPORT_NAME)

    if request.method == "POST":
        form = AdminVPReportForm(request.POST)
        if form.is_valid():
            new_report = form.save(commit=False)
            new_report.report_name = REPORT_NAME
            new_report.save()
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AdminVPReportForm()

    context = {
        "page_heading": "VP Oral Liquids Report Management",
        "table_headers": [
            "Category",
            "Sub Category",
            "Sub Sub Category",
            "Question",
            "Actions",
        ],
        "reports": reports,
        "form": form,
        "action": "/adminmaster/add_vp_liquidorals/",
        "edit_url": "/adminmaster/edit_vp_liquidorals",
        "delete_url": "/adminmaster/delete_vp_liquidorals",
        "modal_title": "VP Oral Liquids Report Overview",
        "modal_body_content": "This section contains reports for VP Oral Liquids management.",
    }
    return render(request, "AdminMaster/VP/VPEditForm.html", context)


@login_required(login_url="/adminmaster/login/")
def add_vp_liquidorals(request):
    if request.method == "POST":
        try:
            form = AdminVPReportForm(request.POST)
            if form.is_valid():
                new_report = form.save(commit=False)
                new_report.report_name = "VP - Oral Liquids Report"
                new_report.save()
            else:
                messages.error(
                    request, "Form validation failed. Please check your inputs."
                )
        except Exception as e:
            messages.error(request, f"Error saving report: {str(e)}")
    return redirect("/adminmaster/show_vp_liquidorals_table")


@login_required(login_url="/adminmaster/login/")
def edit_vp_liquidorals(request, id):
    report = VPReportQuestions.objects.get(id=id)
    if request.method == "POST":
        try:
            form = AdminVPReportForm(request.POST, instance=report)
            if form.is_valid():
                form.save()
            else:
                messages.error(request, "Please correct the errors below.")
        except VPReportQuestions.DoesNotExist:
            messages.error(request, "Report not found!")
        except Exception as e:
            messages.error(request, f"Error updating report: {str(e)}")
    return redirect("/adminmaster/show_vp_liquidorals_table")


@login_required(login_url="/adminmaster/login/")
def delete_vp_liquidorals(request, id):
    try:
        report = VPReportQuestions.objects.get(id=id)
        report.delete()
    except VPReportQuestions.DoesNotExist:
        messages.error(request, "Report not found!")
    return redirect("/adminmaster/show_vp_liquidorals_table")


# Parenteral
@login_required(login_url="/adminmaster/login/")
def show_vp_parenteral_table(request):
    REPORT_NAME = "VP - Parenteral Report"
    reports = VPReportQuestions.objects.filter(report_name=REPORT_NAME)

    if request.method == "POST":
        form = AdminVPReportForm(request.POST)
        if form.is_valid():
            new_report = form.save(commit=False)
            new_report.report_name = REPORT_NAME
            new_report.save()
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AdminVPReportForm()

    context = {
        "page_heading": "VP Parenteral Report Management",
        "table_headers": [
            "Category",
            "Sub Category",
            "Sub Sub Category",
            "Question",
            "Actions",
        ],
        "reports": reports,
        "form": form,
        "action": "/adminmaster/add_vp_parenteral/",
        "edit_url": "/adminmaster/edit_vp_parenteral",
        "delete_url": "/adminmaster/delete_vp_parenteral",
        "modal_title": "VP Parenteral Report Overview",
        "modal_body_content": "This section contains reports for VP Parenteral management.",
    }
    return render(request, "AdminMaster/VP/VPEditForm.html", context)


@login_required(login_url="/adminmaster/login/")
def add_vp_parenteral(request):
    if request.method == "POST":
        try:
            form = AdminVPReportForm(request.POST)
            if form.is_valid():
                new_report = form.save(commit=False)
                new_report.report_name = "VP - Parenteral Report"
                new_report.save()
            else:
                messages.error(
                    request, "Form validation failed. Please check your inputs."
                )
        except Exception as e:
            messages.error(request, f"Error saving report: {str(e)}")
    return redirect("/adminmaster/show_vp_parenteral_table")


@login_required(login_url="/adminmaster/login/")
def edit_vp_parenteral(request, id):
    report = VPReportQuestions.objects.get(id=id)
    if request.method == "POST":
        try:
            form = AdminVPReportForm(request.POST, instance=report)
            if form.is_valid():
                form.save()
            else:
                messages.error(request, "Please correct the errors below.")
        except VPReportQuestions.DoesNotExist:
            messages.error(request, "Report not found!")
        except Exception as e:
            messages.error(request, f"Error updating report: {str(e)}")
    return redirect("/adminmaster/show_vp_parenteral_table")


@login_required(login_url="/adminmaster/login/")
def delete_vp_parenteral(request, id):
    try:
        report = VPReportQuestions.objects.get(id=id)
        report.delete()
    except VPReportQuestions.DoesNotExist:
        messages.error(request, "Report not found!")
    return redirect("/adminmaster/show_vp_parenteral_table")


# Solid Oral
@login_required(login_url="/adminmaster/login/")
def show_vp_solidoral_table(request):
    REPORT_NAME = "VP - Solid Oral Report"
    reports = VPReportQuestions.objects.filter(report_name=REPORT_NAME)

    if request.method == "POST":
        form = AdminVPReportForm(request.POST)
        if form.is_valid():
            new_report = form.save(commit=False)
            new_report.report_name = REPORT_NAME
            new_report.save()
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AdminVPReportForm()

    context = {
        "page_heading": "VP Solid Oral Report Management",
        "table_headers": [
            "Category",
            "Sub Category",
            "Sub Sub Category",
            "Question",
            "Actions",
        ],
        "reports": reports,
        "form": form,
        "action": "/adminmaster/add_vp_solidoral/",
        "edit_url": "/adminmaster/edit_vp_solidoral",
        "delete_url": "/adminmaster/delete_vp_solidoral",
        "modal_title": "VP Solid Oral Report Overview",
        "modal_body_content": "This section contains reports for VP Solid Oral management.",
    }
    return render(request, "AdminMaster/VP/VPEditForm.html", context)


@login_required(login_url="/adminmaster/login/")
def add_vp_solidoral(request):
    if request.method == "POST":
        try:
            form = AdminVPReportForm(request.POST)
            if form.is_valid():
                new_report = form.save(commit=False)
                new_report.report_name = "VP - Solid Oral Report"
                new_report.save()
            else:
                messages.error(
                    request, "Form validation failed. Please check your inputs."
                )
        except Exception as e:
            messages.error(request, f"Error saving report: {str(e)}")
    return redirect("/adminmaster/show_vp_solidoral_table")


@login_required(login_url="/adminmaster/login/")
def edit_vp_solidoral(request, id):
    report = VPReportQuestions.objects.get(id=id)
    if request.method == "POST":
        try:
            form = AdminVPReportForm(request.POST, instance=report)
            if form.is_valid():
                form.save()
            else:
                messages.error(request, "Please correct the errors below.")
        except VPReportQuestions.DoesNotExist:
            messages.error(request, "Report not found!")
        except Exception as e:
            messages.error(request, f"Error updating report: {str(e)}")
    return redirect("/adminmaster/show_vp_solidoral_table")


@login_required(login_url="/adminmaster/login/")
def delete_vp_solidoral(request, id):
    try:
        report = VPReportQuestions.objects.get(id=id)
        report.delete()
    except VPReportQuestions.DoesNotExist:
        messages.error(request, "Report not found!")
    return redirect("/adminmaster/show_vp_solidoral_table")


# Topical
# @login_required(login_url='/adminmaster/login/')
def show_vp_topical_table(request):
    REPORT_NAME = "VP - Topical Report"
    reports = VPReportQuestions.objects.filter(report_name=REPORT_NAME)

    if request.method == "POST":
        form = AdminVPReportForm(request.POST)
        if form.is_valid():
            new_report = form.save(commit=False)
            new_report.report_name = REPORT_NAME
            new_report.save()
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AdminVPReportForm()

    context = {
        "page_heading": "VP Topical Report Management",
        "table_headers": [
            "Category",
            "Sub Category",
            "Sub Sub Category",
            "Question",
            "Actions",
        ],
        "reports": reports,
        "form": form,
        "action": "/adminmaster/add_vp_topical/",
        "edit_url": "/adminmaster/edit_vp_topical",
        "delete_url": "/adminmaster/delete_vp_topical",
        "modal_title": "VP Topical Report Overview",
        "modal_body_content": "This section contains reports for VP Topical management.",
    }
    return render(request, "AdminMaster/VP/VPEditForm.html", context)


@login_required(login_url="/adminmaster/login/")
def add_vp_topical(request):
    if request.method == "POST":
        try:
            form = AdminVPReportForm(request.POST)
            if form.is_valid():
                new_report = form.save(commit=False)
                new_report.report_name = "VP - Topical Report"
                new_report.save()
            else:
                messages.error(
                    request, "Form validation failed. Please check your inputs."
                )
        except Exception as e:
            messages.error(request, f"Error saving report: {str(e)}")
    return redirect("/adminmaster/show_vp_topical_table")


@login_required(login_url="/adminmaster/login/")
def edit_vp_topical(request, id):
    report = VPReportQuestions.objects.get(id=id)
    if request.method == "POST":
        try:
            form = AdminVPReportForm(request.POST, instance=report)
            if form.is_valid():
                form.save()
            else:
                messages.error(request, "Please correct the errors below.")
        except VPReportQuestions.DoesNotExist:
            messages.error(request, "Report not found!")
        except Exception as e:
            messages.error(request, f"Error updating report: {str(e)}")
    return redirect("/adminmaster/show_vp_topical_table")


@login_required(login_url="/adminmaster/login/")
def delete_vp_topical(request, id):
    try:
        report = VPReportQuestions.objects.get(id=id)
        report.delete()
    except VPReportQuestions.DoesNotExist:
        messages.error(request, "Report not found!")
    return redirect("/adminmaster/show_vp_topical_table")


# Transdermal Views
@login_required(login_url="/adminmaster/login/")
def show_vp_transdermal_table(request):
    REPORT_NAME = "VP - Transdermal Report"
    reports = VPReportQuestions.objects.filter(report_name=REPORT_NAME)

    if request.method == "POST":
        form = AdminVPReportForm(request.POST)
        if form.is_valid():
            new_report = form.save(commit=False)
            new_report.report_name = REPORT_NAME
            new_report.save()
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AdminVPReportForm()

    context = {
        "page_heading": "VP Transdermal Report Management",
        "table_headers": [
            "Category",
            "Sub Category",
            "Sub Sub Category",
            "Question",
            "Actions",
        ],
        "reports": reports,
        "form": form,
        "action": "/adminmaster/add_vp_transdermal/",
        "edit_url": "/adminmaster/edit_vp_transdermal",
        "delete_url": "/adminmaster/delete_vp_transdermal",
        "modal_title": "VP Transdermal Report Overview",
        "modal_body_content": "This section contains reports for VP Transdermal management.",
    }
    return render(request, "AdminMaster/VP/VPEditForm.html", context)


@login_required(login_url="/adminmaster/login/")
def add_vp_transdermal(request):
    if request.method == "POST":
        try:
            form = AdminVPReportForm(request.POST)
            if form.is_valid():
                new_report = form.save(commit=False)
                new_report.report_name = "VP - Transdermal Report"
                new_report.save()
            else:
                messages.error(
                    request, "Form validation failed. Please check your inputs."
                )
        except Exception as e:
            messages.error(request, f"Error saving report: {str(e)}")
    return redirect("/adminmaster/show_vp_transdermal_table")


@login_required(login_url="/adminmaster/login/")
def edit_vp_transdermal(request, id):
    report = VPReportQuestions.objects.get(id=id)
    if request.method == "POST":
        try:
            form = AdminVPReportForm(request.POST, instance=report)
            if form.is_valid():
                form.save()
            else:
                messages.error(request, "Please correct the errors below.")
        except VPReportQuestions.DoesNotExist:
            messages.error(request, "Report not found!")
        except Exception as e:
            messages.error(request, f"Error updating report: {str(e)}")
    return redirect("/adminmaster/show_vp_transdermal_table")


@login_required(login_url="/adminmaster/login/")
def delete_vp_transdermal(request, id):
    try:
        report = VPReportQuestions.objects.get(id=id)
        report.delete()
    except VPReportQuestions.DoesNotExist:
        messages.error(request, "Report not found!")
    return redirect("/adminmaster/show_vp_transdermal_table")


# DMF CA
@login_required(login_url="/adminmaster/login/")
def show_dmfca_table(request):
    questions = DMFCATableQuestion.objects.all()

    if request.method == "POST":
        form = DMFCAQuestionForm(request.POST)
        if form.is_valid():
            form.save()
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = DMFCAQuestionForm()

    context = {
        "page_heading": "DMFCA Question Management",
        "table_headers": [
            "Module",
            "Category",
            "Sub Category",
            "eCTD No",
            "eCTD Sub Category",
            "Question",
            "Note",
            "Actions",
        ],
        "questions": questions,
        "form": form,
        "action": "/adminmaster/add_dmfca_question/",
        "edit_url": "/adminmaster/edit_dmfca_question",
        "delete_url": "/adminmaster/delete_dmfca_question",
        "modal_title": "DMFCA Question Overview",
        "modal_body_content": "This section contains questions for DMFCA management.",
    }
    return render(request, "AdminMaster/DMF/DMFCAEditForm.html", context)


@login_required(login_url="/adminmaster/login/")
def add_dmfca_question(request):
    if request.method == "POST":
        try:
            form = DMFCAQuestionForm(request.POST)
            if form.is_valid():
                form.save()
            else:
                messages.error(
                    request, "Form validation failed. Please check your inputs."
                )
        except Exception as e:
            messages.error(request, f"Error saving question: {str(e)}")
    return redirect("/adminmaster/show_dmfca_table")


@login_required(login_url="/adminmaster/login/")
def edit_dmfca_question(request, id):
    try:
        question = DMFCATableQuestion.objects.get(id=id)
        if request.method == "POST":
            form = DMFCAQuestionForm(request.POST, instance=question)
            if form.is_valid():
                form.save()
            else:
                messages.error(request, "Please correct the errors below.")
    except DMFCATableQuestion.DoesNotExist:
        messages.error(request, "Question not found!")
    except Exception as e:
        messages.error(request, f"Error updating question: {str(e)}")
    return redirect("/adminmaster/show_dmfca_table")


@login_required(login_url="/adminmaster/login/")
def delete_dmfca_question(request, id):
    try:
        question = DMFCATableQuestion.objects.get(id=id)
        question.delete()
    except DMFCATableQuestion.DoesNotExist:
        messages.error(request, "Question not found!")
    except Exception as e:
        messages.error(request, f"Error deleting question: {str(e)}")
    return redirect("/adminmaster/show_dmfca_table")


# DMF Review table
@login_required(login_url="/adminmaster/login/")
def show_dmf_review_table(request):
    reports = DMFReviewTableQuestion.objects.all()

    if request.method == "POST":
        form = DMFReviewTableQuestionForm(request.POST)
        if form.is_valid():
            form.save()
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = DMFReviewTableQuestionForm()

    context = {
        "page_heading": "DMF Review Questions Management",
        "table_headers": ["Module", "Category", "Question", "Actions"],
        "reports": reports,
        "form": form,
        "action": "/adminmaster/add_dmf_review/",
        "edit_url": "/adminmaster/edit_dmf_review",
        "delete_url": "/adminmaster/delete_dmf_review",
        "modal_title": "DMF Review Questions Overview",
        "modal_body_content": "This section contains questions for DMF Review management.",
    }
    return render(request, "AdminMaster/DMF/DMFReviewForm.html", context)


@login_required(login_url="/adminmaster/login/")
def add_dmf_review(request):
    if request.method == "POST":
        try:
            form = DMFReviewTableQuestionForm(request.POST)
            if form.is_valid():
                form.save()
            else:
                messages.error(
                    request, "Form validation failed. Please check your inputs."
                )
        except Exception as e:
            messages.error(request, f"Error saving question: {str(e)}")
    return redirect("/adminmaster/show_dmf_review_table")


@login_required(login_url="/adminmaster/login/")
def edit_dmf_review(request, id):
    try:
        question = DMFReviewTableQuestion.objects.get(id=id)
        if request.method == "POST":
            form = DMFReviewTableQuestionForm(request.POST, instance=question)
            if form.is_valid():
                form.save()
            else:
                messages.error(request, "Please correct the errors below.")
    except DMFReviewTableQuestion.DoesNotExist:
        messages.error(request, "Question not found!")
    except Exception as e:
        messages.error(request, f"Error updating question: {str(e)}")
    return redirect("/adminmaster/show_dmf_review_table")


@login_required(login_url="/adminmaster/login/")
def delete_dmf_review(request, id):
    try:
        question = DMFReviewTableQuestion.objects.get(id=id)
        question.delete()
    except DMFReviewTableQuestion.DoesNotExist:
        messages.error(request, "Question not found!")
    return redirect("/adminmaster/show_dmf_review_table")


# GeneralWhitePaper
@login_required(login_url="/adminmaster/login/")
def show_general_white_papers_table(request):
    reports = GeneralReportQuestions.objects.all()

    if request.method == "POST":
        form = AdminGeneralReportForm(request.POST)
        if form.is_valid():
            form.save()
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AdminGeneralReportForm()

    context = {
        "page_heading": "General Reports Management",
        "table_headers": ["Category", "Sub Category", "Question", "Actions"],
        "reports": reports,
        "form": form,
        "action": "/adminmaster/add_general_white_papers/",
        "edit_url": "/adminmaster/edit_general_white_papers",
        "delete_url": "/adminmaster/delete_general_white_papers",
        "modal_title": "General Reports Overview",
        "modal_body_content": "This section contains general reports management.",
    }
    return render(
        request, "AdminMaster/WhitePaper/GeneralWhitePaperEditForm.html", context
    )


@login_required(login_url="/adminmaster/login/")
def add_general_white_papers(request):
    if request.method == "POST":
        try:
            form = AdminGeneralReportForm(request.POST)
            if form.is_valid():
                form.save()
            else:
                messages.error(
                    request, "Form validation failed. Please check your inputs."
                )
        except Exception as e:
            messages.error(request, f"Error saving report: {str(e)}")
    return redirect("/adminmaster/show_general_white_papers_table")


@login_required(login_url="/adminmaster/login/")
def edit_general_white_papers(request, id):
    try:
        report = GeneralReportQuestions.objects.get(id=id)
        if request.method == "POST":
            form = AdminGeneralReportForm(request.POST, instance=report)
            if form.is_valid():
                form.save()
            else:
                messages.error(request, "Please correct the errors below.")
    except GeneralReportQuestions.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error updating report: {str(e)}")
    return redirect("/adminmaster/show_general_white_papers_table")


@login_required(login_url="/adminmaster/login/")
def delete_general_white_papers(request, id):
    try:
        report = GeneralReportQuestions.objects.get(id=id)
        report.delete()
    except GeneralReportQuestions.DoesNotExist:
        messages.error(request, "Report not found!")
    return redirect("/adminmaster/show_general_white_papers_table")
