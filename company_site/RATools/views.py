from django.shortcuts import render, redirect, get_object_or_404,reverse
from .models import *
from django.db import transaction
from django.db import IntegrityError
from .forms import *
import json
from datetime import datetime, timedelta, timezone as py_timezone
from html import escape
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib import messages
from django.http import JsonResponse, FileResponse, Http404, HttpResponse
from django.views.decorators.http import require_http_methods
import os
from django.conf import settings
from AdminMaster.models import *
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
import zipfile
from django.utils.encoding import smart_str
import pandas as pd
from collections import Counter
from .ics_builder import IcsInput, build_ics
from .graph_email import (
    send_graph_email, create_meeting_url, create_calendar_event,
    update_calendar_event, cancel_calendar_event, get_busy_intervals,
    GraphNotConfigured,
)
import pytz


# from AdminMaster.models import *

# Create your views here.


# Authentication Models Should be below this line
# @login_required(login_url='/adminmaster/login/')
from django.shortcuts import render
from django.http import FileResponse, Http404
import re

def natural_key(text):
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r'(\d+)', text)]
BASE_DIR = os.path.join(settings.MEDIA_ROOT, "Module_Simplification")


import re

def file_priority(name):
    name_lower = name.lower()

    # ✅ intro always top
    if "intro" in name_lower:
        return (-1, 0)

    # ✅ Match patterns like:
    # 32p1, 32s1, 32p10, 32s7
    m = re.search(r'(\d+)\s*([a-z])\s*(\d+)', name_lower.replace("-", "").replace("_", ""))
    if m:
        major = int(m.group(1))        # 32
        mid_char = m.group(2)          # p / s / etc
        minor = int(m.group(3))        # 1,2,3...

        # ✅ Ensure P comes before S (if both exist)
        char_order = ord(mid_char) - ord('a')

        return (0, major * 10000 + char_order * 100 + minor)

    # ✅ other keyword priorities
    if "drug-prod" in name_lower:
        return (1, 1)
    if "drug-sub" in name_lower:
        return (1, 2)
    if "sterility-aseptic" in name_lower:
        return (1, 3)
    if "sterility-terminal" in name_lower:
        return (1, 4)

    return (99, 999999)

def module_view(request):
    path = request.GET.get("path", "")  # relative path
    current_path = os.path.normpath(os.path.join(BASE_DIR, path))
    first_folder = ""  # represents root (Module_Simplification)

    # Security
    if not current_path.startswith(BASE_DIR):
        raise Http404("Invalid path")

    if os.path.isfile(current_path):
        raise Http404("Not a directory")

    # -------- FLAGS --------
    osd_flag = False
    inj_flag = False

    if request.user.is_authenticated:
        assignment = AssignChecker.objects.get(user=request.user)
        assigned_reports = assignment.assigned_report
        osd_flag = "Solid Oral Dosage Form" in assigned_reports
        inj_flag = "Sterile Dosage Form" in assigned_reports

    # -------- PARENT PATH (for Back button) --------
    parent_path = ""
    if path:
        parent_path = path.rsplit("/", 1)[0] if "/" in path else ""

    files = []
    items = sorted(
    os.listdir(current_path),
    key=lambda x: (
        not os.path.isdir(os.path.join(current_path, x)),  # folders first
        file_priority(x),                                   # tuple priority
        natural_key(x)                                      # natural sort
    )
    )


    for item in items:

        full_path = os.path.join(current_path, item)

        if item == "Solid Oral Dosage Form":
            flag = osd_flag
        elif item == "Sterile Dosage Form":
            flag = inj_flag
        else:
            flag = True

        files.append({
            "name": item,
            "is_folder": os.path.isdir(full_path),
            "path": f"{path}/{item}" if path else item,
            "flag": flag
        })

    return render(request, "RATools/Module.html", {
        "files": files,
        "path": path,
        "parent_path": parent_path,
        "first_folder": first_folder,
    })





def open_file(request):
    file_path = request.GET.get("file", "")
    full_path = os.path.join(BASE_DIR, file_path)


    if not full_path.startswith(BASE_DIR) or not os.path.isfile(full_path):
        raise Http404("File not found")

    return FileResponse(open(full_path, "rb"), as_attachment=False)

def download_folder_zip(request):
    folder_path = request.GET.get("path", "")
    full_folder_path = os.path.normpath(os.path.join(BASE_DIR, folder_path))

    # ✅ Security check
    if not full_folder_path.startswith(BASE_DIR):
        raise Http404("Invalid path")

    if not os.path.isdir(full_folder_path):
        raise Http404("Folder not found")

    zip_name = os.path.basename(full_folder_path) + ".zip"
    zip_path = os.path.join(settings.MEDIA_ROOT, "temp_zip", zip_name)

    # ✅ create temp folder if not exists
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)

    # ✅ Make ZIP
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(full_folder_path):
            for file in files:
                abs_file_path = os.path.join(root, file)

                # ✅ relative path inside zip
                rel_path = os.path.relpath(abs_file_path, full_folder_path)
                zipf.write(abs_file_path, arcname=rel_path)

    # ✅ Send zip as response
    response = FileResponse(open(zip_path, "rb"), as_attachment=True, filename=zip_name)
    return response
def basetemplate(request):
    context = {"user_name": request.user, "page_heading": "Home Page"}
    return render(request, "RATools/RAToolsBase.html", context)

def moduletemplate(request):
    user = request.user
    context = {}
    if request.user.is_authenticated:
        assignment = AssignChecker.objects.get(user=user)
        context = {"flag":"Module Simplifiacation" in assignment.assigned_report}
    return render(request, "RATools/ModuleHome.html",context)


def home(request):
    from AIDatabase.views import get_cached_df, get_unique_investigators_count,get_cached_warning_letter_df;  AssignChecker

    context = {}

    try:
        # Get data from form483_dashboard logic
        df = get_cached_df()
        df = df.where(pd.notnull(df), None)
        df = df.rename(columns={"Year of Inspection": "Year"})
        df = df.dropna(subset=["Year", "System"])
        df["Year"] = df["Year"].astype(int)

        context["Total_observations"] = len(df)
        context["Total_Companies"] = df["Company Name"].nunique()

        years = sorted(df["Year"].dropna().unique().tolist())
        context["chart1labels"] = years

        system_sequence = [
            "Quality System",
            "Laboratory Control System",
            "Material System",
            "Packaging and Labelling System",
            "Production System",
            "Facilites & Equipment System",
        ]
        context["system_sequence"] = system_sequence

        system_labels_map = {
            "quality system": "Quality System",
            "laboratory control system": "Laboratory Control System",
            "production system": "Production System",
            "material system": "Material System",
            "packaging and labeling system": "Packaging and Labelling System",
            "packaging and labelling system": "Packaging and Labelling System",
            "facilities and equipment system": "Facilites & Equipment System",
            "facilities & equipment system": "Facilites & Equipment System",
            "facility & equipment system": "Facilites & Equipment System",
        }

        df["System"] = df["System"].astype(str).str.strip().str.lower()
        df["System"] = df["System"].map(system_labels_map)
        df = df[df["System"].notna()]

        pivot = df.groupby(["System", "Year"]).size().unstack(fill_value=0)
        final_data = {}
        for system in system_sequence:
            final_data[system] = [
                int(pivot.at[system, y]) if (system in pivot.index and y in pivot.columns) else 0
                for y in years
            ]

        context["chart1data"] = final_data

        system_counts = df["System"].value_counts()
        context["system_labels"] = system_sequence
        context["system_data"] = [int(system_counts.get(system, 0)) for system in system_sequence]

        investigator_series = (
            df['FDA Investigator(s) name']
            .dropna()
            .astype(str)
            .str.rstrip(', ')
            .str.split(',')
            .explode()
            .str.strip()
            .str.lower()
            .replace('', pd.NA)
            .dropna()
        )
        investigator_counts = Counter(investigator_series)
        top_10 = investigator_counts.most_common(10)

        top_10_df = pd.DataFrame(top_10, columns=["Investigator", "Count"])

        context["top_investigators"] = [
            {"name": name, "count": int(count)}
            for name, count in top_10_df[["Investigator", "Count"]].itertuples(index=False, name=None)
        ]

        df["Type of establishment"] = df["Type of establishment"].str.strip()

        establishment_labels = [
            "API Manufacturer",
            "Contract Drug Manufacturer",
            "Prescription (Rx) Drug Manufacturer",
        ]

        establishment_data = [
            int(df[df["Type of establishment"] == label].shape[0])
            for label in establishment_labels
        ]

        context["establishment_labels"] = establishment_labels
        context["establishment_data"] = establishment_data
        context["Total_observations"]=len(df)
        warningletters=get_cached_warning_letter_df()
        context["total_warning"]=int(len(warningletters))
        user = request.user
        if request.user.is_authenticated:
            assignment = AssignChecker.objects.get(user=user)
            context["flag"] = "Form 483" in assignment.assigned_report
        else:
            context["flag"] = False
        context["Total_Investigators"] = get_unique_investigators_count(df)

    except Exception as e:
        # Fallback if data loading fails
        context["error"] = str(e)

    return render(request, "HomePage.html", context)


def terms_of_use(request):
    return render(request, "terms_of_use.html")
def privacy_policy(request):
    return render(request, "Privacypolicy.html")
def about_alpesh(request):
    return render(request, "about_alpesh.html")


def baseShow(request):
    context = {
        "page_heading": "Dynamic Page Heading",
        "anda_facility_template_active": True,
    }
    return render(request, "RATools/baseShow.html", context)


# ANDA Views Function Should be below this line
# View Sample ANDA Checklist
@login_required(login_url='/adminmaster/login/')
def view_sample_anda_checklist(request,report_name):
    organized_data = {}
    grouped_data = {}
    questions = ANDAReportQuestions.objects.filter(
        report_name=report_name
    )
    if report_name == "Metered Dose Inhaler (MDI) and Dry Powder Inhaler (DPI) Dosage Form":
        html = "RATools/ANDA/MDIAndDPIReport.html"
        heading = "ANDA MDI and DPI Report"
    elif report_name == "Nasal Spray  & Inhalation Dosage":
        html = "RATools/ANDA/NasalSprayAndInhalation.html"
        heading = "Nasal Spray & Inhalation Dosage"
    elif report_name == "Parenteral Dosage":
        html = "RATools/ANDA/ParenteralDosage.html"
        heading = "Parenteral Dosage FORM"
    elif report_name == "Transdermal":
        html = "RATools/ANDA/TransdermalDosage.html"
        heading = "TRANSDERMAL DOSAGE"
    elif report_name == "General ANDA":
        html = "RATools/ANDA/GeneralAnda.html"
        heading = "General ANDA"
    elif report_name == "Ophthalmic Dosage":
        html = "RATools/ANDA/OphthalmicDosage.html"
        heading = "OPHTHALMIC DOSAGE FORM"
    elif report_name == "Semi Solid Dosage Form":
        html = "RATools/ANDA/SemiSolidTopicalDosage.html"
        heading = "SEMI SOLID TOPICAL DOSAGE FORM"
    elif report_name == "Solid Oral Dosage":
        html = "RATools/ANDA/SolidOralDosage.html"
        heading = "SOLID ORAL DOSAGE FORM"

    elif report_name == "Liposome Dosage Form":
        html = "RATools/ANDA/LiposomeReport.html"
        heading = "LIPOSOME DOSAGE FORM"

    elif report_name == "Microsphere Dosage Form":
        html = "RATools/ANDA/MicrosphereReport.html"
        heading = "MICROSPHERE DOSAGE FORM"

    for question in questions:
        if question.module_name not in organized_data:
            organized_data[question.module_name] = {}
            grouped_data[question.module_name] = []

        if question.chapter_name not in organized_data[question.module_name]:
            organized_data[question.module_name][question.chapter_name] = {}

        category = question.category_name
        if category not in organized_data[question.module_name][question.chapter_name]:
            organized_data[question.module_name][question.chapter_name][category] = []

        # Add a checklist_answers attribute with a null answer
        question.checklist_answers = type("Answer", (), {"answer": None})()

        organized_data[question.module_name][question.chapter_name][category].append(
            question
        )

        if category not in grouped_data[question.module_name]:
            grouped_data[question.module_name].append(category)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": heading,
        "report_name": (
            questions.first().report_name if questions.exists() else "ANDA Report"
        ),
        "complete_flag": False,
        "show_flag": True,
        "flag": False,
    }
    return render(request, html, context)





# @login_required(login_url='/adminmaster/login/')
def show_anda_microsphere_table(request):
    user = request.user

    if not request.user.is_authenticated:
        return render(
            request,
            "RATools/ANDA/MicrosphereReport.html",
            {
                "page_flag" :True,
                "show_flag": False,
                "heading": "Microsphere Dosage Form",
                "report_name": "Microsphere Dosage Form",
            },
        )
    assigns = AssignChecker.objects.get(user=user)
    report_name = "Microsphere Dosage Form"

    if user.role == "company_user":
        view_sample = False
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False

    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = ANDAForm(
            user=user,
            report_name=ANDAReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )

        return render(
            request,
            "RATools/baseShow.html",
            {
                "main_folder":"ANDA Review Checklist",
                "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
                "page_heading": 'Microsphere',
                "reports": reports,
                "form": form,
                "action": "../../ratools/anda/add_anda_microsphere_checklist/",
                "edit_url": "/ratools/anda/show_anda_microsphere_report",
                "delete_url": "/ratools/anda/delete_anda_microsphere_checklist",
                "modal_body_content": "Microsphere...",
                "modal_title": "Microsphere Overview",
                "anda_checklist_active": False,
                "view_sample":view_sample,
                "sample_url":"/ratools/view_sample_anda_checklist/Microsphere Dosage Form"
            },
        )
    else:
        return render(
            request,
            "RATools/ANDA/MicrosphereReport.html",
            {
                "show_flag": False,
                "heading": "ANDA Microsphere Report",
                "report_name": report_name,
            },
        )

@login_required(login_url='/adminmaster/login/')
def show_anda_microsphere_report(request, id):
    report_type = request.GET.get(
        "report_type",
        "Microsphere Dosage Form",
    )

    # Get the current user
    current_user = request.user
    # Get or create user report
    user_report = ANDAUserReports.objects.get(
        report_name__report_name=report_type,id=id
    )
    review_task_url = request.build_absolute_uri(
        reverse("show_anda_microsphere_report", args=[user_report.id])
    )

    # Handle form submission
    if current_user.role == "company_user":
        flag = False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            # Check if the form is being completed
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = ANDAReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)

                if answer_value:
                    # Update or create answer
                    answer, created = ANDAUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name_id=user_report.id,
                        report_question_id=question.id,
                        defaults={"answer": answer_value},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send personalized email to each checker
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            return redirect("/ratools/show_anda_microsphere_table")

    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_10
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level, review_task_url)
                user_report.save()
            return redirect("/ratools/show_anda_microsphere_table")

        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    # Rest of your existing view code for GET requests
    questions = ANDAReportQuestions.objects.filter(
        report_name="Microsphere Dosage Form"
    )

    if report_type:
        questions = questions.filter(report_name=report_type)

    user_answers = {}
    if user_report:
        answers = ANDAUserAnswers.objects.filter(
            report_name=user_report
        )
        user_answers = {answer.report_question_id: answer.answer for answer in answers}

    # Your existing organization code
    organized_data = {}
    grouped_data = {}

    for question in questions:
        if question.module_name not in organized_data:
            organized_data[question.module_name] = {}
            grouped_data[question.module_name] = []

        if question.chapter_name not in organized_data[question.module_name]:
            organized_data[question.module_name][question.chapter_name] = {}

        category = question.category_name
        if category not in organized_data[question.module_name][question.chapter_name]:
            organized_data[question.module_name][question.chapter_name][category] = []

        if question.id in user_answers:
            question.checklist_answers = type(
                "Answer", (), {"answer": user_answers[question.id]}
            )()

        organized_data[question.module_name][question.chapter_name][category].append(
            question
        )

        if category not in grouped_data[question.module_name]:
            grouped_data[question.module_name].append(category)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "ANDA Microsphere Report",
        "report_name": (
            questions.first().report_name if questions.exists() else "ANDA Report"
        ),
        "substance": request.GET.get("substance", ""),
        "report_type": report_type,
        "available_reports": [
            "Microsphere Dosage Form"
        ],
        "product_name": user_report.product_name if user_report else "N/A",
        "complete_flag": user_report.show_buttons_doer,
        "show_flag": True,
        "flag":flag
    }

    return render(request, "RATools/ANDA/MicrosphereReport.html", context)

@login_required(login_url='/adminmaster/login/')
def add_anda_microsphere_checklist(request):
    report_name = "Microsphere Dosage Form"
    if request.method == "POST":
        form = ANDAForm(
            request.POST,
            user=request.user,
            report_name=ANDAReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_anda_microsphere_table")

@login_required(login_url='/adminmaster/login/')
def delete_anda_microsphere_checklist(request, id):
    try:
        report = ANDAUserReports.objects.get(id=id)
        ANDAUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except ANDAUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")

    return redirect("/ratools/show_anda_microsphere_table")


# @login_required(login_url='/adminmaster/login/')
def show_anda_liposome_table(request):
    user = request.user

    if not request.user.is_authenticated:
        return render(
            request,
            "RATools/ANDA/LiposomeReport.html",
            {
                "page_flag" :True,
                "show_flag": False,
                "heading": "ANDA Liposome Report",
                "report_name": "Liposome Dosage Form",
            },
        )

    assigns = AssignChecker.objects.get(user=user)
    report_name = "Liposome Dosage Form"

    if user.role == "company_user":
        view_sample = False
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False

    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = ANDAForm(
            user=user,
            report_name=ANDAReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )

        return render(
            request,
            "RATools/baseShow.html",
            {
                "main_folder":"ANDA Review Checklist",
                "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
                "page_heading": 'Liposome',
                "reports": reports,
                "form": form,
                "action": "../../ratools/anda/add_anda_liposome_checklist/",
                "edit_url": "/ratools/anda/show_anda_liposome_report",
                "delete_url": "/ratools/anda/delete_anda_liposome_checklist",
                "modal_body_content": "Liposome..",
                "modal_title": "Liposome Overview",
                "anda_checklist_active": False,
                "view_sample":view_sample,
                "sample_url":"/ratools/view_sample_anda_checklist/Liposome Dosage Form"
            },
        )
    else:
        return render(
            request,
            "RATools/ANDA/LiposomeReport.html",
            {
                "show_flag": False,
                "heading": "ANDA Liposome Report",
                "report_name": report_name,
            },
        )

@login_required(login_url='/adminmaster/login/')
def show_anda_liposome_report(request, id):
    report_type = request.GET.get(
        "report_type",
        "Liposome Dosage Form",
    )

    # Get the current user
    current_user = request.user
    # Get or create user report
    user_report = ANDAUserReports.objects.get(
        report_name__report_name=report_type,id=id
    )
    review_task_url = request.build_absolute_uri(
        reverse("show_anda_liposome_report", args=[user_report.id])
    )

    # Handle form submission
    if current_user.role == "company_user":
        flag = False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            # Check if the form is being completed
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = ANDAReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)

                if answer_value:
                    # Update or create answer
                    answer, created = ANDAUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name_id=user_report.id,
                        report_question_id=question.id,
                        defaults={"answer": answer_value},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send personalized email to each checker
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            return redirect("/ratools/show_anda_liposome_table")

    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_9
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level,review_task_url)
                user_report.save()
            return redirect("/ratools/show_anda_liposome_table")

        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    # Rest of your existing view code for GET requests
    questions = ANDAReportQuestions.objects.filter(
        report_name="Liposome Dosage Form"
    )

    if report_type:
        questions = questions.filter(report_name=report_type)

    user_answers = {}
    if user_report:
        answers = ANDAUserAnswers.objects.filter(
            report_name=user_report
        )
        user_answers = {answer.report_question_id: answer.answer for answer in answers}

    # Your existing organization code
    organized_data = {}
    grouped_data = {}

    for question in questions:
        if question.module_name not in organized_data:
            organized_data[question.module_name] = {}
            grouped_data[question.module_name] = []

        if question.chapter_name not in organized_data[question.module_name]:
            organized_data[question.module_name][question.chapter_name] = {}

        category = question.category_name
        if category not in organized_data[question.module_name][question.chapter_name]:
            organized_data[question.module_name][question.chapter_name][category] = []

        if question.id in user_answers:
            question.checklist_answers = type(
                "Answer", (), {"answer": user_answers[question.id]}
            )()

        organized_data[question.module_name][question.chapter_name][category].append(
            question
        )

        if category not in grouped_data[question.module_name]:
            grouped_data[question.module_name].append(category)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "ANDA Liposome Report",
        "report_name": (
            questions.first().report_name if questions.exists() else "ANDA Report"
        ),
        "substance": request.GET.get("substance", ""),
        "report_type": report_type,
        "available_reports": [
            "Liposome Dosage Form"
        ],
        "product_name": user_report.product_name if user_report else "N/A",
        "complete_flag": user_report.show_buttons_doer,
        "show_flag": True,
        "flag":flag
    }

    return render(request, "RATools/ANDA/LiposomeReport.html", context)

@login_required(login_url='/adminmaster/login/')
def add_anda_liposome_checklist(request):
    report_name = "Liposome Dosage Form"
    if request.method == "POST":
        form = ANDAForm(
            request.POST,
            user=request.user,
            report_name=ANDAReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_anda_liposome_table")

@login_required(login_url='/adminmaster/login/')
def delete_anda_liposome_checklist(request, id):
    try:
        report = ANDAUserReports.objects.get(id=id)
        ANDAUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except ANDAUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")

    return redirect("/ratools/show_anda_liposome_table")

# MDI DIP Report
# @login_required(login_url='/adminmaster/login/')
def show_anda_mdi_and_dpi_table(request):
    user = request.user

    if not request.user.is_authenticated:
        return render(
            request,
            "RATools/ANDA/MDIAndDPIReport.html",
            {
                "page_flag" :True,
                "show_flag": False,
                "heading": "ANDA MDI and DPI Report",
                "report_name": "Metered Dose Inhaler (MDI) and Dry Powder Inhaler (DPI) Dosage Form",
            },
        )
    user = request.user
    assigns = AssignChecker.objects.get(user=user)
    report_name = "Metered Dose Inhaler (MDI) and Dry Powder Inhaler (DPI) Dosage Form"

    if user.role == "company_user":
        view_sample = False
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False

    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = ANDAForm(
            user=user,
            report_name=ANDAReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )

        return render(
            request,
            "RATools/baseShow.html",
            {
                "main_folder":"ANDA Review Checklist",
                "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
                "page_heading": "MDI & DPI",
                "reports": reports,
                "form": form,
                "action": "../../ratools/anda/add_anda_mdi_and_dpi_checklist/",
                "edit_url": "/ratools/anda/show_anda_mdi_and_dpi_report",
                "delete_url": "/ratools/anda/delete_anda_mdi_and_dpi_checklist",
                "modal_body_content": "MDI & DPI...",
                "modal_title": "MDI & DPI Overview",
                "anda_checklist_active": False,
                "view_sample":view_sample,
                "sample_url":"/ratools/view_sample_anda_checklist/Metered Dose Inhaler (MDI) and Dry Powder Inhaler (DPI) Dosage Form"
            },
        )
    else:
        return render(
            request,
            "RATools/ANDA/MDIAndDPIReport.html",
            {
                "show_flag": False,
                "heading": "ANDA MDI and DPI Report",
                "report_name": report_name,
            },
        )

@login_required(login_url='/adminmaster/login/')
def show_anda_mdi_and_dpi_report(request, id):
    report_type = request.GET.get(
        "report_type",
        "Metered Dose Inhaler (MDI) and Dry Powder Inhaler (DPI) Dosage Form",
    )

    # Get the current user
    current_user = request.user
    # Get or create user report
    user_report = ANDAUserReports.objects.get(
        report_name__report_name=report_type,id=id
    )
    review_task_url = request.build_absolute_uri(
        reverse("show_anda_mdi_and_dpi_report", args=[user_report.id])
    )

    # Handle form submission
    if current_user.role == "company_user":
        flag = False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            # Check if the form is being completed
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = ANDAReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)

                if answer_value:
                    # Update or create answer
                    answer, created = ANDAUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name_id=user_report.id,
                        report_question_id=question.id,
                        defaults={"answer": answer_value},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send personalized email to each checker
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            return redirect("/ratools/show_anda_mdi_and_dpi_table")

    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_1
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level, review_task_url)
                user_report.save()
            return redirect("/ratools/show_anda_mdi_and_dpi_table")

        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    # Rest of your existing view code for GET requests
    questions = ANDAReportQuestions.objects.filter(
        report_name="Metered Dose Inhaler (MDI) and Dry Powder Inhaler (DPI) Dosage Form"
    )

    if report_type:
        questions = questions.filter(report_name=report_type)

    user_answers = {}
    if user_report:
        answers = ANDAUserAnswers.objects.filter(
            report_name=user_report
        )
        user_answers = {answer.report_question_id: answer.answer for answer in answers}

    # Your existing organization code
    organized_data = {}
    grouped_data = {}

    for question in questions:
        if question.module_name not in organized_data:
            organized_data[question.module_name] = {}
            grouped_data[question.module_name] = []

        if question.chapter_name not in organized_data[question.module_name]:
            organized_data[question.module_name][question.chapter_name] = {}

        category = question.category_name
        if category not in organized_data[question.module_name][question.chapter_name]:
            organized_data[question.module_name][question.chapter_name][category] = []

        if question.id in user_answers:
            question.checklist_answers = type(
                "Answer", (), {"answer": user_answers[question.id]}
            )()

        organized_data[question.module_name][question.chapter_name][category].append(
            question
        )

        if category not in grouped_data[question.module_name]:
            grouped_data[question.module_name].append(category)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "ANDA MDI and DPI Report",
        "report_name": (
            questions.first().report_name if questions.exists() else "ANDA Report"
        ),
        "substance": request.GET.get("substance", ""),
        "report_type": report_type,
        "available_reports": [
            "Metered Dose Inhaler (MDI) and Dry Powder Inhaler (DPI) Dosage Form"
        ],
        "product_name": user_report.product_name if user_report else "N/A",
        "complete_flag": user_report.show_buttons_doer,
        "show_flag": True,
        "flag":flag
    }

    return render(request, "RATools/ANDA/MDIAndDPIReport.html", context)

@login_required(login_url='/adminmaster/login/')
def add_anda_mdi_and_dpi_checklist(request):
    report_name = "Metered Dose Inhaler (MDI) and Dry Powder Inhaler (DPI) Dosage Form"
    if request.method == "POST":
        form = ANDAForm(
            request.POST,
            user=request.user,
            report_name=ANDAReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_anda_mdi_and_dpi_table")

@login_required(login_url='/adminmaster/login/')
def delete_anda_mdi_and_dpi_checklist(request, id):
    try:
        report = ANDAUserReports.objects.get(id=id)
        ANDAUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except ANDAUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")

    return redirect("/ratools/show_anda_mdi_and_dpi_table")


# Nasalspray Inhalation Report
# @login_required(login_url='/adminmaster/login/')
def show_anda_nasalspray_inhalation_table(request):
    user = request.user

    if not request.user.is_authenticated:
        return render(
            request,
            "RATools/ANDA/NasalSprayAndInhalation.html",
            {
                "page_flag" :True,
                "show_flag": False,
                "heading": "Nasal Spray  & Inhalation Dosage",
                "report_name": "Nasal Spray  & Inhalation Dosage",
            },
        )
    assigns = AssignChecker.objects.get(user=user)
    report_name = "Nasal Spray  & Inhalation Dosage"

    if user.role == "company_user":
        view_sample = False
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False

        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False

    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = ANDAForm(
            user=request.user,
            report_name=ANDAReportQuestions.objects.filter(report_name=report_name).first(),
        )

        context = {
            "main_folder":"ANDA Review Checklist",
            "reports": reports,
            "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
            "page_heading": report_name,
            "form": form,
            "action": "../../ratools/anda/add_anda_nasalspray_inhalation_checklist/",
            "edit_url": "/ratools/anda/show_anda_nasalspray_inhalation_report",
            "delete_url": "/ratools/anda/delete_anda_nasalspray_inhalation_checklist",
            "modal_body_content": "Nasal Spray & Inhalation Dosage...",
            "modal_title": "Nasal Spray & Inhalation Dosage Overview",
            "view_sample":view_sample,
            "sample_url":f"/ratools/view_sample_anda_checklist/{report_name}"
        }
        return render(request, "RATools/baseShow.html", context)
    else:
        return render(
            request,
            "RATools/ANDA/NasalSprayAndInhalation.html",
            {
                "show_flag": False,
                "heading": "Nasal Spray & Inhalation Dosage",
                "report_name": report_name,
            },
        )

@login_required(login_url='/adminmaster/login/')
def show_anda_nasalspray_inhalation_report(request, id):
    report_type = request.GET.get("report_type", "Nasal Spray  & Inhalation Dosage")
    current_user = request.user

    user_report = ANDAUserReports.objects.get(
        report_name__report_name=report_type, id=id
    )
    review_task_url = request.build_absolute_uri(
        reverse("show_anda_nasalspray_inhalation_report", args=[user_report.id])
    )

    if current_user.role == "company_user":
        flag = False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            # Check if the form is being completed
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = ANDAReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)

                if answer_value:
                    # Update or create answer
                    answer, created = ANDAUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name_id=user_report.id,
                        report_question_id=question.id,
                        defaults={"answer": answer_value},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send personalized email to each checker
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            return redirect("/ratools/show_anda_nasalspray_inhalation_table")
    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_2
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level,review_task_url)
                user_report.save()
            return redirect("/ratools/show_anda_nasalspray_inhalation_table")

        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    questions = ANDAReportQuestions.objects.filter(
        report_name="Nasal Spray  & Inhalation Dosage"
    )

    if report_type:
        questions = questions.filter(report_name=report_type)

    user_answers = {}
    if user_report:
        answers = ANDAUserAnswers.objects.filter(
           report_name=user_report
        )
        user_answers = {answer.report_question_id: answer.answer for answer in answers}

    organized_data = {}
    grouped_data = {}

    for question in questions:
        if question.module_name not in organized_data:
            organized_data[question.module_name] = {}
            grouped_data[question.module_name] = []

        if question.chapter_name not in organized_data[question.module_name]:
            organized_data[question.module_name][question.chapter_name] = {}

        category = question.category_name
        if category not in organized_data[question.module_name][question.chapter_name]:
            organized_data[question.module_name][question.chapter_name][category] = []

        if question.id in user_answers:
            question.checklist_answers = type(
                "Answer", (), {"answer": user_answers[question.id]}
            )

        organized_data[question.module_name][question.chapter_name][category].append(
            question
        )

        if category not in grouped_data[question.module_name]:
            grouped_data[question.module_name].append(category)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "Nasal Spray & Inhalation Dosage",
        "report_name": (
            questions.first().report_name
            if questions.exists()
            else "Nasal Spray & Inhalation Dosage"
        ),
        "substance": request.GET.get("substance", ""),
        "report_type": report_type,
        "available_reports": ["Nasal Spray  & Inhalation Dosage"],
        "product_name": user_report.product_name if user_report else "N/A",
        "complete_flag": user_report.show_buttons_doer,
        "show_flag":True,
        "flag":flag,
    }

    return render(request, "RATools/ANDA/NasalSprayAndInhalation.html", context)

@login_required(login_url='/adminmaster/login/')
def add_anda_nasalspray_inhalation_checklist(request):
    report_name = "Nasal Spray  & Inhalation Dosage"
    if request.method == "POST":
        form = ANDAForm(
            request.POST,
            user=request.user,
            report_name=ANDAReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_anda_nasalspray_inhalation_table")

@login_required(login_url='/adminmaster/login/')
def delete_anda_nasalspray_inhalation_checklist(request, id):
    try:
        report = ANDAUserReports.objects.get(id=id)
        ANDAUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except ANDAUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")

    return redirect("/ratools/show_anda_nasalspray_inhalation_table")


# Parenteral Dosage Report

# @login_required(login_url='/adminmaster/login/')
def show_anda_parenteral_dosage_table(request):
    user = request.user

    if not request.user.is_authenticated:
        return render(
            request,
            "RATools/ANDA/ParenteralDosage.html",
            {
                "page_flag" :True,
                "show_flag": False,
                "heading": "Parenteral Dosage FORM",
                "report_name": "Parenteral Dosage",
            },
        )
    assigns = AssignChecker.objects.get(user=user)
    report_name = "Parenteral Dosage"
    if user.role == "company_user":
        view_sample = False
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False

    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = ANDAForm(
            user=request.user,
            report_name=ANDAReportQuestions.objects.filter(report_name=report_name).first(),
        )

        context = {
            "main_folder":"ANDA Review Checklist",
            "reports": reports,
            "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
            "page_heading": report_name,
            "form": form,
            "action": "../../ratools/anda/add_anda_parenteral_dosage_checklist/",
            "edit_url": "/ratools/anda/show_anda_parenteral_dosage_report",
            "delete_url": "/ratools/anda/delete_anda_parenteral_dosage_checklist",
            "modal_body_content": "Parenteral Dosage...",
            "modal_title": "Parenteral Dosage Overview",
            "view_sample":view_sample,
            "sample_url":f"/ratools/view_sample_anda_checklist/{report_name}"
        }
        return render(request, "RATools/baseShow.html", context)
    else:
        return render(
            request,
            "RATools/ANDA/ParenteralDosage.html",
            {
                "show_flag": False,
                "heading": "Parenteral Dosage FORM",
                "report_name": report_name,
            },
        )

@login_required(login_url='/adminmaster/login/')
def show_anda_parenteral_dosage_report(request, id):
    report_type = request.GET.get("report_type", "Parenteral Dosage")
    current_user = request.user

    user_report = ANDAUserReports.objects.get(
        report_name__report_name=report_type, id=id
    )
    review_task_url = request.build_absolute_uri(
        reverse("show_anda_parenteral_dosage_report", args=[user_report.id])
    )

    if current_user.role == "company_user":
        flag = False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            # Check if the form is being completed
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = ANDAReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)

                if answer_value:
                    # Update or create answer
                    answer, created = ANDAUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name_id=user_report.id,
                        report_question_id=question.id,
                        defaults={"answer": answer_value},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send personalized email to each checker
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            return redirect("/ratools/show_anda_parenteral_dosage_table")
    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_3
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level, review_task_url)
                user_report.save()
            return redirect("/ratools/show_anda_parenteral_dosage_table")

        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False


    questions = ANDAReportQuestions.objects.filter(
        report_name="Parenteral Dosage"
    )

    if report_type:
        questions = questions.filter(report_name=report_type)

    user_answers = {}
    if user_report:
        answers = ANDAUserAnswers.objects.filter(
            report_name=user_report
        )
        user_answers = {answer.report_question_id: answer.answer for answer in answers}

    organized_data = {}
    grouped_data = {}

    for question in questions:
        if question.module_name not in organized_data:
            organized_data[question.module_name] = {}
            grouped_data[question.module_name] = []

        if question.chapter_name not in organized_data[question.module_name]:
            organized_data[question.module_name][question.chapter_name] = {}

        category = question.category_name
        if category not in organized_data[question.module_name][question.chapter_name]:
            organized_data[question.module_name][question.chapter_name][category] = []

        if question.id in user_answers:
            question.checklist_answers = type(
                "Answer", (), {"answer": user_answers[question.id]}
            )()

        organized_data[question.module_name][question.chapter_name][category].append(
            question
        )

        if category not in grouped_data[question.module_name]:
            grouped_data[question.module_name].append(category)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "Parenteral Dosage FORM",
        "report_name": (
            questions.first().report_name if questions.exists() else "Parenteral Dosage"
        ),
        "substance": request.GET.get("substance", ""),
        "report_type": report_type,
        "available_reports": ["Parenteral Dosage"],
        "product_name": user_report.product_name if user_report else "N/A",
        "complete_flag": user_report.show_buttons_doer,
        "show_flag":True,
        "flag":flag,
    }

    return render(request, "RATools/ANDA/ParenteralDosage.html", context)

@login_required(login_url='/adminmaster/login/')
def add_anda_parenteral_dosage_checklist(request):
    report_name = "Parenteral Dosage"
    if request.method == "POST":
        form = ANDAForm(
            request.POST,
            user=request.user,
            report_name=ANDAReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_anda_parenteral_dosage_table")

@login_required(login_url='/adminmaster/login/')
def delete_anda_parenteral_dosage_checklist(request, id):
    try:
        report = ANDAUserReports.objects.get(id=id)
        ANDAUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except ANDAUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")

    return redirect("/ratools/show_anda_parenteral_dosage_table")


# TRANSDERMAL DOSAGE FORM
# @login_required(login_url='/adminmaster/login/')
def show_anda_transdermal_dosage_table(request):
    user = request.user

    if not request.user.is_authenticated:
        return render(
            request,
            "RATools/ANDA/TransdermalDosage.html",
            {
                "page_flag" :True,
                "show_flag": False,
                "heading": "Transdermal ANDA",
                "report_name": "TRANSDERMAL DOSAGE",
            },
        )
    assigns = AssignChecker.objects.get(user=user)
    report_name = "Transdermal"
    if user.role == "company_user":
        view_sample = False
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False

    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = ANDAForm(
            user=request.user,
            report_name=ANDAReportQuestions.objects.filter(report_name=report_name).first(),
        )

        context = {
            "main_folder":"ANDA Review Checklist",
            "reports": reports,
            "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
            "page_heading": "Transdermal",
            "form": form,
            "action": "../../ratools/anda/add_anda_transdermal_dosage_checklist/",
            "edit_url": "/ratools/anda/show_anda_transdermal_dosage_report",
            "delete_url": "/ratools/anda/delete_anda_transdermal_dosage_checklist",
            "modal_body_content": "Transdermal ...",
            "modal_title": "Transdermal Overview",
            "view_sample":view_sample,
                "sample_url":"/ratools/view_sample_anda_checklist/Transdermal"
        }
        return render(request, "RATools/baseShow.html", context)
    else:
        return render(
            request,
            "RATools/ANDA/TransdermalDosage.html",
            {
                "show_flag": False,
                "heading": "TRANSDERMAL DOSAGE",
                "report_name": report_name,
            },
        )

@login_required(login_url='/adminmaster/login/')
def show_anda_transdermal_dosage_report(request, id):
    report_type = request.GET.get("report_type", "Transdermal")
    current_user = request.user

    user_report = ANDAUserReports.objects.get(
        report_name__report_name=report_type, id=id
    )
    review_task_url = request.build_absolute_uri(
        reverse("show_anda_transdermal_dosage_report", args=[user_report.id])
    )

    if current_user.role == "company_user":
        flag = False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            # Check if the form is being completed
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = ANDAReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)

                if answer_value:
                    # Update or create answer
                    answer, created = ANDAUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name_id=user_report.id,
                        report_question_id=question.id,
                        defaults={"answer": answer_value},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send personalized email to each checker
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            return redirect("/ratools/show_anda_transdermal_dosage_table")

    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_4
        print("current_user.id:", current_user.id)
        print("assignment.checkers_json:", assignment.checkers_json)
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level, review_task_url)
                user_report.save()
            return redirect("/ratools/show_anda_transdermal_dosage_table")

        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    questions = ANDAReportQuestions.objects.filter(report_name="Transdermal")

    if report_type:
        questions = questions.filter(report_name=report_type)

    user_answers = {}
    if user_report:
        answers = ANDAUserAnswers.objects.filter(
            report_name=user_report
        )
        user_answers = {answer.report_question_id: answer.answer for answer in answers}

    organized_data = {}
    grouped_data = {}

    for question in questions:
        if question.module_name not in organized_data:
            organized_data[question.module_name] = {}
            grouped_data[question.module_name] = []

        if question.chapter_name not in organized_data[question.module_name]:
            organized_data[question.module_name][question.chapter_name] = {}

        category = question.category_name
        if category not in organized_data[question.module_name][question.chapter_name]:
            organized_data[question.module_name][question.chapter_name][category] = []

        if question.id in user_answers:
            question.checklist_answers = type(
                "Answer", (), {"answer": user_answers[question.id]}
            )()

        organized_data[question.module_name][question.chapter_name][category].append(
            question
        )

        if category not in grouped_data[question.module_name]:
            grouped_data[question.module_name].append(category)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "TRANSDERMAL DOSAGE",
        "report_name": (
            questions.first().report_name if questions.exists() else "Transdermal"
        ),
        "substance": request.GET.get("substance", ""),
        "report_type": report_type,
        "available_reports": ["Transdermal"],
        "product_name": user_report.product_name if user_report else "N/A",
        "complete_flag": user_report.show_buttons_doer,
        "show_flag":True,
        "flag":flag,
    }

    return render(request, "RATools/ANDA/TransdermalDosage.html", context)

@login_required(login_url='/adminmaster/login/')
def add_anda_transdermal_dosage_checklist(request):
    report_name = "Transdermal"
    if request.method == "POST":
        form = ANDAForm(
            request.POST,
            user=request.user,
            report_name=ANDAReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_anda_transdermal_dosage_table")

@login_required(login_url='/adminmaster/login/')
def delete_anda_transdermal_dosage_checklist(request, id):
    try:
        report = ANDAUserReports.objects.get(id=id)
        ANDAUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except ANDAUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")
    return redirect("/ratools/show_anda_transdermal_dosage_table")


# GENERAL ANDA
# @login_required(login_url='/adminmaster/login/')
def show_anda_general_table(request):
    user = request.user

    if not request.user.is_authenticated:
        return render(
            request,
            "RATools/ANDA/GeneralAnda.html",
            {
                "page_flag" :True,
                "show_flag": False,
                "heading": "General ANDA",
                "report_name": "General ANDA",
            },
        )
    assigns = AssignChecker.objects.get(user=user)
    report_name = "General ANDA"
    if user.role == "company_user":
        view_sample = False
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False

    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = ANDAForm(
            user=request.user,
            report_name=ANDAReportQuestions.objects.filter(report_name=report_name).first(),
        )

        context = {
            "main_folder":"ANDA Review Checklist",
            "reports": reports,
            "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
            "page_heading": "General ANDA",
            "form": form,
            "action": "../../ratools/anda/add_anda_general_checklist/",
            "edit_url": "/ratools/anda/show_anda_general_report",
            "delete_url": "/ratools/anda/delete_anda_general_checklist",
            "modal_body_content": "General ANDA..",
            "modal_title": "General ANDA Overview",
            "view_sample":view_sample,
            "sample_url":"/ratools/view_sample_anda_checklist/General ANDA"
        }
        return render(request, "RATools/baseShow.html", context)
    else:
        return render(
            request,
            "RATools/ANDA/GeneralAnda.html",
            {
                "show_flag": False,
                "heading": "General ANDA",
                "report_name": report_name,
            },
        )

@login_required(login_url='/adminmaster/login/')
def show_anda_general_report(request, id):
    report_type = request.GET.get("report_type", "General ANDA")
    current_user = request.user

    user_report = ANDAUserReports.objects.get(
        report_name__report_name=report_type, id=id
    )

    review_task_url = request.build_absolute_uri(
        reverse("show_anda_general_report", args=[user_report.id])
    )

    if current_user.role == "company_user":
        flag = False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            # Check if the form is being completed
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = ANDAReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)

                if answer_value:
                    # Update or create answer
                    answer, created = ANDAUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name_id=user_report.id,
                        report_question_id=question.id,
                        defaults={"answer": answer_value},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        # The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send personalized email to each checker
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        # from_email=user_report.user.email,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )

                    # print("email sent to user>>>>>>")
            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            return redirect("/ratools/show_anda_general_table")

    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_5
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        # print("current_level",current_level)
        # if not current_level:
            # print("company current level not found")

        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level, review_task_url)
                user_report.save()
            return redirect("/ratools/show_anda_general_table")

        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    questions = ANDAReportQuestions.objects.filter(report_name="General ANDA")


    if report_type:
        questions = questions.filter(report_name=report_type)

    user_answers = {}
    if user_report:
        answers = ANDAUserAnswers.objects.filter(
            report_name=user_report
        )
        user_answers = {answer.report_question_id: answer.answer for answer in answers}

    organized_data = {}
    grouped_data = {}

    for question in questions:
        if question.module_name not in organized_data:
            organized_data[question.module_name] = {}
            grouped_data[question.module_name] = {}

        if question.chapter_name not in organized_data[question.module_name]:
            organized_data[question.module_name][question.chapter_name] = {}
            grouped_data[question.module_name][question.chapter_name] = []

        category = question.category_name
        if category not in organized_data[question.module_name][question.chapter_name]:
            organized_data[question.module_name][question.chapter_name][category] = []



        if question.id in user_answers:
            question.checklist_answers = type(
                "Answer", (), {"answer": user_answers[question.id]}
            )()

        organized_data[question.module_name][question.chapter_name][category].append(
            question
        )

        # Append the category to the list if it doesn't already exist
        if category not in grouped_data[question.module_name][question.chapter_name]:
            grouped_data[question.module_name][question.chapter_name].append(category)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "General ANDA",
        "report_name": (
            questions.first().report_name if questions.exists() else "General ANDA"
        ),
        "substance": request.GET.get("substance", ""),
        "report_type": report_type,
        "available_reports": ["General ANDA"],
        "product_name": user_report.product_name if user_report else "N/A",
        "complete_flag": user_report.show_buttons_doer,
        "show_flag":True,
        "flag":flag,
    }

    return render(request, "RATools/ANDA/GeneralAnda.html", context)

@login_required(login_url='/adminmaster/login/')
def add_anda_general_checklist(request):
    report_name = "General ANDA"
    if request.method == "POST":
        form = ANDAForm(
            request.POST,
            user=request.user,
            report_name=ANDAReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_anda_general_table")

@login_required(login_url='/adminmaster/login/')
def delete_anda_general_checklist(request, id):
    try:
        report = ANDAUserReports.objects.get(id=id)
        ANDAUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except ANDAUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")
    return redirect("/ratools/show_anda_general_table")


# OPHTHALMIC DOSAGE FORM
# @login_required(login_url='/adminmaster/login/')
def show_anda_ophthalmic_dosage_table(request):
    user = request.user
    if not request.user.is_authenticated:
        return render(
            request,
            "RATools/ANDA/OphthalmicDosage.html",
            {
                "page_flag" :True,
                "show_flag": False,
                "heading": "Ophthalmic Dosage",
                "report_name": "Ophthalmic Dosage",
            },
        )
    user = request.user
    assigns = AssignChecker.objects.get(user=user)
    report_name = "Ophthalmic Dosage"
    if user.role == "company_user":
        view_sample = False
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False

    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = ANDAForm(
            user=request.user,
            report_name=ANDAReportQuestions.objects.filter(report_name=report_name).first(),
        )

        context = {
            "main_folder":"ANDA Review Checklist",
            "reports": reports,
            "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
            "page_heading": "Ophthalmic Dosage",
            "form": form,
            "action": "../../ratools/anda/add_anda_ophthalmic_dosage_checklist/",
            "edit_url": "/ratools/anda/show_anda_ophthalmic_dosage_report",
            "delete_url": "/ratools/anda/delete_anda_ophthalmic_dosage_checklist",
            "modal_body_content": "Ophthalmic Dosage...",
            "modal_title": "Ophthalmic Dosage Overview",
            "view_sample":view_sample,
            "sample_url":f"/ratools/view_sample_anda_checklist/{report_name}",
        }
        return render(request, "RATools/baseShow.html", context)
    else:
        return render(
            request,
            "RATools/ANDA/OphthalmicDosage.html",
            {
                "show_flag": False,
                "heading": "OPHTHALMIC DOSAGE FORM",
                "report_name": report_name,
            },
        )

@login_required(login_url='/adminmaster/login/')
def show_anda_ophthalmic_dosage_report(request, id):
    report_type = request.GET.get("report_type", "Ophthalmic Dosage")
    current_user = request.user

    user_report = ANDAUserReports.objects.get(
        report_name__report_name=report_type, id=id
    )
    review_task_url = request.build_absolute_uri(
        reverse("show_anda_ophthalmic_dosage_report", args=[user_report.id])
    )

    if current_user.role == "company_user":
        flag = False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            # Check if the form is being completed
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = ANDAReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)

                if answer_value:
                    # Update or create answer
                    answer, created = ANDAUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name_id=user_report.id,
                        report_question_id=question.id,
                        defaults={"answer": answer_value},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send personalized email to each checker
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            return redirect("/ratools/show_anda_ophthalmic_dosage_table")
    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_6
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level, review_task_url)
                user_report.save()
            return redirect("/ratools/show_anda_ophthalmic_dosage_table")

        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    questions = ANDAReportQuestions.objects.filter(
        report_name="Ophthalmic Dosage"
    )

    if report_type:
        questions = questions.filter(report_name=report_type)

    user_answers = {}
    if user_report:
        answers = ANDAUserAnswers.objects.filter(
            report_name=user_report
        )
        user_answers = {answer.report_question_id: answer.answer for answer in answers}

    organized_data = {}
    grouped_data = {}

    for question in questions:
        if question.module_name not in organized_data:
            organized_data[question.module_name] = {}
            grouped_data[question.module_name] = []

        if question.chapter_name not in organized_data[question.module_name]:
            organized_data[question.module_name][question.chapter_name] = {}

        category = question.category_name
        if category not in organized_data[question.module_name][question.chapter_name]:
            organized_data[question.module_name][question.chapter_name][category] = []

        if question.id in user_answers:
            question.checklist_answers = type(
                "Answer", (), {"answer": user_answers[question.id]}
            )()

        organized_data[question.module_name][question.chapter_name][category].append(
            question
        )

        if category not in grouped_data[question.module_name]:
            grouped_data[question.module_name].append(category)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "OPHTHALMIC DOSAGE FORM",
        "report_name": (
            questions.first().report_name if questions.exists() else "Ophthalmic Dosage"
        ),
        "substance": request.GET.get("substance", ""),
        "report_type": report_type,
        "available_reports": ["Ophthalmic Dosage"],
        "product_name": user_report.product_name if user_report else "N/A",
        "complete_flag": user_report.show_buttons_doer,
        "show_flag":True,
        "flag":flag,
    }

    return render(request, "RATools/ANDA/OphthalmicDosage.html", context)

@login_required(login_url='/adminmaster/login/')
def add_anda_ophthalmic_dosage_checklist(request):
    report_name = "Ophthalmic Dosage"
    if request.method == "POST":
        form = ANDAForm(
            request.POST,
            user=request.user,
            report_name=ANDAReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_anda_ophthalmic_dosage_table")

@login_required(login_url='/adminmaster/login/')
def delete_anda_ophthalmic_dosage_checklist(request, id):
    try:
        report = ANDAUserReports.objects.get(id=id)
        ANDAUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except ANDAUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")
    return redirect("/ratools/show_anda_ophthalmic_dosage_table")


# Semi Solid Topical Dosage
# @login_required(login_url='/adminmaster/login/')
def show_anda_semi_solid_topical_dosage_table(request):
    user = request.user
    if not request.user.is_authenticated:
        return render(
            request,
            "RATools/ANDA/SemiSolidTopicalDosage.html",
            {
                "page_flag" :True,
                "show_flag": False,
                "heading": "SEMI SOLID TOPICAL DOSAGE FORM",
                "report_name": "SEMI SOLID TOPICAL DOSAGE FORM",
            },
        )
    assigns = AssignChecker.objects.get(user=user)
    report_name = "Semi Solid Dosage Form"
    if user.role == "company_user":
        view_sample = False
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False

    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = ANDAForm(
            user=request.user,
            report_name=ANDAReportQuestions.objects.filter(report_name=report_name).first(),
        )

        context = {
            "main_folder":"ANDA Review Checklist",
            "reports": reports,
            "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
            "page_heading": "Semi Solid Topical Dosage",
            "form": form,
            "action": "../../ratools/anda/add_anda_semi_solid_topical_dosage_checklist/",
            "edit_url": "/ratools/anda/show_anda_semi_solid_topical_dosage_report",
            "delete_url": "/ratools/anda/delete_anda_semi_solid_topical_dosage_checklist",
            "modal_body_content": "Semi Solid Topical Dosage...",
            "modal_title": "Semi Solid Topical Dosage Overview",
            "view_sample":view_sample,
            "sample_url":f"/ratools/view_sample_anda_checklist/{report_name}",
        }
        return render(request, "RATools/baseShow.html", context)
    else:
        return render(
            request,
            "RATools/ANDA/SemiSolidTopicalDosage.html",
            {
                "show_flag": False,
                "heading": "SEMI SOLID TOPICAL DOSAGE FORM",
                "report_name": report_name,
            },
        )

@login_required(login_url='/adminmaster/login/')
def show_anda_semi_solid_topical_dosage_report(request, id):
    report_type = request.GET.get("report_type", "Semi Solid Dosage Form")
    current_user = request.user

    user_report = ANDAUserReports.objects.get(
        report_name__report_name=report_type, id=id
    )
    review_task_url = request.build_absolute_uri(
        reverse("show_anda_semi_solid_topical_dosage_report", args=[user_report.id])
    )

    if current_user.role == "company_user":
        flag = False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            # Check if the form is being completed
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = ANDAReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)

                if answer_value:
                    # Update or create answer
                    answer, created = ANDAUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name_id=user_report.id,
                        report_question_id=question.id,
                        defaults={"answer": answer_value},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send personalized email to each checker
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            return redirect("/ratools/show_anda_semi_solid_topical_dosage_table")
    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_7
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level, review_task_url)
                user_report.save()
            return redirect("/ratools/show_anda_semi_solid_topical_dosage_table")

        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False


    questions = ANDAReportQuestions.objects.filter(
        report_name="Semi Solid Dosage Form"
    )

    if report_type:
        questions = questions.filter(report_name=report_type)

    user_answers = {}
    if user_report:
        answers = ANDAUserAnswers.objects.filter(
           report_name=user_report
        )
        user_answers = {answer.report_question_id: answer.answer for answer in answers}

    organized_data = {}
    grouped_data = {}

    for question in questions:
        if question.module_name not in organized_data:
            organized_data[question.module_name] = {}
            grouped_data[question.module_name] = []

        if question.chapter_name not in organized_data[question.module_name]:
            organized_data[question.module_name][question.chapter_name] = {}

        category = question.category_name
        if category not in organized_data[question.module_name][question.chapter_name]:
            organized_data[question.module_name][question.chapter_name][category] = []

        if question.id in user_answers:
            question.checklist_answers = type(
                "Answer", (), {"answer": user_answers[question.id]}
            )()

        organized_data[question.module_name][question.chapter_name][category].append(
            question
        )

        if category not in grouped_data[question.module_name]:
            grouped_data[question.module_name].append(category)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "Semi Solid Dosage Form",
        "report_name": (
            questions.first().report_name
            if questions.exists()
            else "Semi Solid Dosage Form"
        ),
        "substance": request.GET.get("substance", ""),
        "report_type": report_type,
        "available_reports": ["Semi Solid Dosage Form"],
        "product_name": user_report.product_name if user_report else "N/A",
        "complete_flag": user_report.show_buttons_doer,
        "show_flag":True,
        "flag":flag,
    }

    return render(request, "RATools/ANDA/SemiSolidTopicalDosage.html", context)

@login_required(login_url='/adminmaster/login/')
def add_anda_semi_solid_topical_dosage_checklist(request):
    report_name = "Semi Solid Dosage Form"
    if request.method == "POST":
        form = ANDAForm(
            request.POST,
            user=request.user,
            report_name=ANDAReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_anda_semi_solid_topical_dosage_table")

@login_required(login_url='/adminmaster/login/')
def delete_anda_semi_solid_topical_dosage_checklist(request, id):
    try:
        report = ANDAUserReports.objects.get(id=id)
        ANDAUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except ANDAUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")
    return redirect("/ratools/show_anda_semi_solid_topical_dosage_table")


# Solid Oral Dosage
# @login_required(login_url='/adminmaster/login/')
def show_anda_solid_oral_dosage_table(request):
    user = request.user
    if not request.user.is_authenticated:
        return render(
            request,
            "RATools/ANDA/SolidOralDosage.html",
            {
                "page_flag" :True,
                "show_flag": False,
                "heading": "SOLID ORAL DOSAGE FORM",
                "report_name": "SOLID ORAL DOSAGE FORM",
            },
        )
    assigns = AssignChecker.objects.get(user=user)
    report_name = "Solid Oral Dosage"
    if user.role == "company_user":
        view_sample = False
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = ANDAUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = ANDAUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False

    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = ANDAForm(
            user=request.user,
            report_name=ANDAReportQuestions.objects.filter(report_name=report_name).first(),
        )

        context = {
            "main_folder":"ANDA Review Checklist",
            "reports": reports,
            "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
            "page_heading": "Solid Oral Dosage",
            "form": form,
            "action": "../../ratools/anda/add_anda_solid_oral_dosage_checklist/",
            "edit_url": "/ratools/anda/show_anda_solid_oral_report",
            "delete_url": "/ratools/anda/delete_anda_solid_oral_dosage_checklist",
            "modal_body_content": "Solid Oral Dosage...",
            "modal_title": "Solid Oral Dosage Overview",
            "view_sample":view_sample,
            "sample_url":f"/ratools/view_sample_anda_checklist/{report_name}",
        }
        return render(request, "RATools/baseShow.html", context)
    else:
        return render(
            request,
            "RATools/ANDA/SolidOralDosage.html",
            {
                "show_flag": False,
                "heading": "SOLID ORAL DOSAGE FORM",
                "report_name": report_name,
            },
        )

@login_required(login_url='/adminmaster/login/')
def show_anda_solid_oral_report(request, id):
    report_type = request.GET.get("report_type", "Solid Oral Dosage")

    current_user = request.user
    user_report = ANDAUserReports.objects.get(
        report_name__report_name=report_type,id=id
    )
    review_task_url = request.build_absolute_uri(
        reverse("show_anda_solid_oral_report", args=[user_report.id])
    )

    # Handle form submission
    if current_user.role == "company_user":
        flag = False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            # Check if the form is being completed
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = ANDAReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)

                if answer_value:
                    # Update or create answer
                    answer, created = ANDAUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name_id=user_report.id,
                        report_question_id=question.id,
                        defaults={"answer": answer_value},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send personalized email to each checker
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            return redirect("/ratools/show_anda_solid_oral_dosage_table")
    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_8
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level, review_task_url)
                user_report.save()
            return redirect("/ratools/show_anda_solid_oral_dosage_table")

        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    # Rest of your existing view code for GET requests
    questions = ANDAReportQuestions.objects.filter(
        report_name="Solid Oral Dosage"
    )
    if report_type:
        questions = questions.filter(report_name=report_type)

    user_answers = {}
    if user_report:
        answers = ANDAUserAnswers.objects.filter(
            report_name=user_report
        )
        user_answers = {answer.report_question_id: answer.answer for answer in answers}

    # Your existing organization code
    organized_data = {}
    grouped_data = {}

    for question in questions:
        if question.module_name not in organized_data:
            organized_data[question.module_name] = {}
            grouped_data[question.module_name] = []

        if question.chapter_name not in organized_data[question.module_name]:
            organized_data[question.module_name][question.chapter_name] = {}

        category = question.category_name
        if category not in organized_data[question.module_name][question.chapter_name]:
            organized_data[question.module_name][question.chapter_name][category] = []

        if question.id in user_answers:
            question.checklist_answers = type(
                "Answer", (), {"answer": user_answers[question.id]}
            )()

        organized_data[question.module_name][question.chapter_name][category].append(
            question
        )

        if category not in grouped_data[question.module_name]:
            grouped_data[question.module_name].append(category)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "Solid Oral Dosage",
        "report_name": (
            questions.first().report_name if questions.exists() else "Solid Oral Dosage"
        ),
        "substance": request.GET.get("substance", ""),
        "report_type": report_type,
        "available_reports": ["Solid Oral Dosage"],
        "product_name": user_report.product_name if user_report else "N/A",
        "complete_flag": user_report.show_buttons_doer,
        "flag":flag,
        "show_flag":True,
    }

    return render(request, "RATools/ANDA/SolidOralDosage.html", context)

@login_required(login_url='/adminmaster/login/')
def add_anda_solid_oral_dosage_checklist(request):
    report_name = "Solid Oral Dosage"
    if request.method == "POST":
        form = ANDAForm(
            request.POST,
            user=request.user,
            report_name=ANDAReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_anda_solid_oral_dosage_table")

@login_required(login_url='/adminmaster/login/')
def delete_anda_solid_oral_dosage_checklist(request, id):
    try:
        report = ANDAUserReports.objects.get(id=id)
        ANDAUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except ANDAUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")
    return redirect("/ratools/show_anda_solid_oral_dosage_table")


# ANDA Facility Tamplate Views Function Should be below this line

from itertools import groupby
# Controlled Correspondences Views Function Should be below this line
# @login_required(login_url='/adminmaster/login/')
def show_controlled_correspondences_bestpractice(request):
    user = request.user
    if not request.user.is_authenticated:
        return render(
            request,
            "RATools/ControlledCorrespondences/BestPractice.html",
            {
                "page_flag" :True,
                "show_flag": False,
                "report_name": "Controlled Correspondence Best Practices",
            },
        )

    report_name = "Controlled Correspondence Best Practices"

    # Get all data ordered by category and sub_category
    data = CCBestPractice.objects.all()

    if report_name in AssignChecker.objects.get(user=user).assigned_report:
        show_flag = True
    else:
        show_flag = False

    # Initialize the grouped data structure
    grouped_data = {}
    category_counter = 1

    for category, category_group in groupby(data, key=lambda x: x.category):
        subcategory_data = {}
        subcategory_counter = 1

        for subcategory, subcategory_group in groupby(category_group, key=lambda x: x.sub_category):
            questions = list(subcategory_group)

            # Numbered questions
            numbered_questions = []
            for i, question in enumerate(questions, 1):
                question.numbered_key = f"{category_counter}.{subcategory_counter}.{i}"
                numbered_questions.append(question)

            subcategory_data[f"{category_counter}.{subcategory_counter} {subcategory}"] = numbered_questions
            subcategory_counter += 1

        grouped_data[f"{category_counter}. {category}"] = subcategory_data
        category_counter += 1

    context = {"grouped_data": grouped_data, "report_name": report_name, "show_flag":show_flag}

    return render(
        request, "RATools/ControlledCorrespondences/BestPractice.html", context
    )

# @login_required(login_url='/adminmaster/login/')
def show_controlled_correspondences_template(request):
    user = request.user
    if not request.user.is_authenticated:
        return render(
            request,
            "RATools/baseShow.html",
            {
                "table_headers":["Reports","Action"],
            },
        )

    report_name = "Controlled Correspondences Templates"
    assigns = AssignChecker.objects.get(user=user)
    if report_name in assigns.assigned_report:
        reports = ["Controlled Correspondences Templates"]
        context = {
            "table_headers": ["Reports","Action"],
            "reports":reports,
            "controlled_reports":True,
            "modal_body_content": "CC Templates...",
            "modal_title": "CC Templates Overview",
        }
    else:
        context = {
            "table_headers":["Reports","Action"],

        }
    return render(request, "RATools/baseShow.html",context)

# @login_required(login_url='/adminmaster/login/')
# def show_controlled_correspondences_template(request):
#     user = request.user
#     cctemplate, created = CCTemplate.objects.get_or_create(user=user)
#     report_name = "Controlled Correspondences Template for Q1Q2"
#     if report_name in AssignChecker.objects.get(user=user).assigned_report:
#         show_flag =True
#     else:
#         show_flag = False
#     if request.method == "POST":
#         try:
#             data = {
#                 "user": user,
#                 "proposed_drug_product_name": request.POST.get("drugName"),
#                 "date": request.POST.get("date") or timezone.now().date(),
#                 "anda_applicant_name": request.POST.get("andaApplicant"),
#                 "brand_name_generic_name": request.POST.get("brandName"),
#                 "strength": request.POST.get("strength"),
#                 "nda_applicant_name": request.POST.get("ndaApplicant"),
#                 "nda_number": request.POST.get("ndax"),
#                 "company_name": request.POST.get("companyName"),
#                 "responsible_person_name": request.POST.get("responsiblePerson"),
#                 "email_address": request.POST.get("email"),
#                 "telephone": request.POST.get("telephone"),
#                 "mobile": request.POST.get("mobile"),
#                 "fax": request.POST.get("fax"),
#                 "us_agent_company_name": request.POST.get("usAgentCompany"),
#                 "designation": request.POST.get("designation"),
#                 "us_regulatory_agent_company_name": request.POST.get(
#                     "usRegulatoryAgent"
#                 ),
#             }
#             if request.FILES.get("logo"):
#                 cctemplate.company_logo = request.FILES.get("logo")
#             if request.FILES.get("signature"):
#                 cctemplate.signature = request.FILES.get("signature")

#             for field, value in data.items():
#                 setattr(cctemplate, field, value)
#             cctemplate.save()

#             success_message = (
#                 "Template saved successfully"
#                 if created
#                 else "Template updated successfully"
#             )
#             return render(
#                 request,
#                 "RATools/ControlledCorrespondences/CCTemplate.html",
#                 {"success": success_message, "cctemplate": cctemplate, "show_flag":show_flag},
#             )

#         except Exception as e:
#             return render(
#                 request,
#                 "RATools/ControlledCorrespondences/CCTemplate.html",
#                 {"error": str(e)},
#             )

#     return render(
#         request,
#         "RATools/ControlledCorrespondences/CCTemplate.html",
#         {"cctemplate": cctemplate, "show_flag":show_flag},
#     )

@login_required(login_url='/adminmaster/login/')
def add_dmf_checklist(request):
    if request.method == "POST":
        form = DMFForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
        else:
            print(form.errors)
    return redirect("/ratools/show_dmf_table")


# def show_dmf_report(request, id):
#     checklist = DMFChecklistUser.objects.get(id=id)
#     comments = DMFModuleComment.objects.filter(checklist=checklist)
#     if request.method == "POST":
#         dmf_review = DMFReviewTableQuestion.objects.all()
#         comment_section = json.loads(request.POST.get("comment_section", "[]"))
#         DMFModuleComment.objects.filter(checklist=checklist).delete()

#         # Save new comments
#         for module_data in comment_section:
#             module_name = module_data["module"]
#             remarks = module_data["remarks"]
#             statuses = module_data["statuses"]

#             # Create a comment for each remark/status pair
#             for remark, status in zip(remarks, statuses):
#                 if remark or status:  # Only save if there's content
#                     DMFModuleComment.objects.create(
#                         checklist=checklist,
#                         module=module_name,
#                         comment=remark,
#                         status=status,
#                     )

#         for question in dmf_review:
#             drf_key = f"drf_{question.id}"
#             drf_value = bool(request.POST.get(drf_key))
#             ra_key = f"ra_{question.id}"
#             ra_value = bool(request.POST.get(ra_key))
#             ard_key = f"ard_{question.id}"
#             ard_value = bool(request.POST.get(ard_key))

#             if drf_value or ra_value or ard_value:
#                 # Update or create answer
#                 answer, created = DMFReviewAnswer.objects.update_or_create(
#                     checklist=checklist,
#                     dmf_review_id=question.id,
#                     defaults={"drf": drf_value, "ra": ra_value, "ard": ard_value},
#                 )

#         dmf_ca = DMFCATableQuestion.objects.all()

#         for que in dmf_ca:
#             answer_key = f"answer_{que.id}"
#             answer_value = request.POST.get(answer_key)

#             if answer_value:
#                 answer, created = DMFCAAnswer.objects.update_or_create(
#                     checklist=checklist,
#                     dmf_ca_id=que.id,
#                     defaults={"answer": answer_value,},
#                 )

#         # messages.success(request, 'Answers saved successfully!')
#         return redirect(request.path)

#     # Get all questions
#     dmf_review = DMFReviewTableQuestion.objects.all()
#     dmf_ca = DMFCATableQuestion.objects.all()

#     dmf_ca_answers = {}
#     # Get existing user answers
#     user_answers = {}
#     if checklist:
#         # Change this line to include both answer and comment
#         ca_answers = DMFCAAnswer.objects.filter(checklist=checklist)
#         answers = DMFReviewAnswer.objects.filter(checklist=checklist)
#         dmf_ca_answers = {
#             ca_answer.dmf_ca_id: {
#                 "answer": ca_answer.answer,
#             }
#             for ca_answer in ca_answers
#         }
#         user_answers = {
#             answer.dmf_review_id: {
#                 "drf": answer.drf,
#                 "ra": answer.ra,
#                 "ard": answer.ard,
#             }
#             for answer in answers
#         }

#     organized_data = {}
#     ca_organized_data = {}

#     for que in dmf_ca:
#         module = que.module
#         category = None if que.category == "None" else que.category
#         sub_category = None if que.sub_category == "None" else que.sub_category
#         ectd_no = None if que.ectd_no == "None" else que.ectd_no
#         ectd_sub_category = None if que.ectd_sub_category == "None" else que.ectd_sub_category

#         if module not in ca_organized_data:
#             ca_organized_data[module] = {}
#         if category not in ca_organized_data[module]:
#             ca_organized_data[module][category] = {}
#         if sub_category not in ca_organized_data[module][category]:
#             ca_organized_data[module][category][sub_category] = {}
#         if ectd_no not in ca_organized_data[module][category][sub_category]:
#             ca_organized_data[module][category][sub_category][ectd_no] = {}
#         if (
#             ectd_sub_category
#             not in ca_organized_data[module][category][sub_category][ectd_no]
#         ):
#             ca_organized_data[module][category][sub_category][ectd_no][
#                 ectd_sub_category
#             ] = []

#         ca_organized_data[module][category][sub_category][ectd_no][
#             ectd_sub_category
#         ].append(que)
#         if module:
#             if que.id in dmf_ca_answers:
#                 que.checklist_answers = type(
#                     "Answer",
#                     (),
#                     {
#                         "answer": dmf_ca_answers[que.id]["answer"],
#                     },
#                 )()

#     for question in dmf_review:
#         module = question.module
#         category = question.category

#         if module not in organized_data:
#             organized_data[module] = {}

#         if category not in organized_data[module]:
#             organized_data[module][category] = []

#         if category:
#             if question.id in user_answers:
#                 question.checklist_answers = type(
#                     "Answer",
#                     (),
#                     {
#                         "drf": user_answers[question.id]["drf"],
#                         "ra": user_answers[question.id]["ra"],
#                         "ard": user_answers[question.id]["ard"],
#                     },
#                 )()

#             organized_data[module][category].append(question)
#     existing_comments = {}
#     for comment in comments:
#         if comment.module not in existing_comments:
#             existing_comments[comment.module] = {"remarks": [], "statuses": []}
#         existing_comments[comment.module]["remarks"].append(comment.comment or "")
#         existing_comments[comment.module]["statuses"].append(comment.status or "")

#     return render(
#         request,
#         "RATools/DMF/DMFChecklist.html",
#         {
#             "checklist": checklist,
#             "dmf_review": dmf_review,
#             "dmf_ca": dmf_ca,
#             "organized_data": organized_data,
#             "ca_organized_data": ca_organized_data,
#             "existing_comments": json.dumps(existing_comments),
#         },
#     )

@login_required(login_url='/adminmaster/login/')
def view_sample_dmf(request):
    # Get all questions
    dmf_review = DMFReviewTableQuestion.objects.all()
    dmf_ca = DMFCATableQuestion.objects.all()

    # Organize DMF CA questions
    ca_organized_data = {}
    ca_grouped_data = {}

    for que in dmf_ca:
        module = que.module
        category = None if que.category == "None" else que.category
        sub_category = None if que.sub_category == "None" else que.sub_category
        ectd_no = None if que.ectd_no == "None" else que.ectd_no
        ectd_sub_category = None if que.ectd_sub_category == "None" else que.ectd_sub_category

        if module not in ca_grouped_data:
            ca_grouped_data[module] = {}

        if ectd_no not in ca_grouped_data[module]:
            ca_grouped_data[module][ectd_no] = []

        if module not in ca_organized_data:
            ca_organized_data[module] = {}
        if category not in ca_organized_data[module]:
            ca_organized_data[module][category] = {}
        if sub_category not in ca_organized_data[module][category]:
            ca_organized_data[module][category][sub_category] = {}
        if ectd_no not in ca_organized_data[module][category][sub_category]:
            ca_organized_data[module][category][sub_category][ectd_no] = {}
        if (
            ectd_sub_category
            not in ca_organized_data[module][category][sub_category][ectd_no]
        ):
            ca_organized_data[module][category][sub_category][ectd_no][
                ectd_sub_category
            ] = []

        # Add a checklist_answers attribute with null values
        que.checklist_answers = type(
            "Answer",
            (),
            {
                "answer": None,
            },
        )()

        ca_organized_data[module][category][sub_category][ectd_no][
            ectd_sub_category
        ].append(que)

    # Organize DMF Review questions
    organized_data = {}

    for question in dmf_review:
        module = question.module
        category = question.category

        if module not in organized_data:
            organized_data[module] = {}

        if category not in organized_data[module]:
            organized_data[module][category] = []

        # Add a checklist_answers attribute with null values
        question.checklist_answers = type(
            "Answer",
            (),
            {
                "drf": None,
                "ra": None,
                "ard": None,
            },
        )()

        organized_data[module][category].append(question)

    # Prepare context
    context = {
        "checklist": None,  # No checklist for sample view
        "dmf_review": dmf_review,
        "dmf_ca": dmf_ca,
        "organized_data": organized_data,
        "ca_organized_data": ca_organized_data,
        "ca_grouped_data": ca_grouped_data,
        "existing_comments": json.dumps({}),  # No comments for sample view
        "show_flag": True,
        "flag": False,  # No checker functionality for sample view
        "complete_flag": False,  # No completion for sample view
    }

    return render(request, "RATools/DMF/DMFChecklist.html", context)

@login_required(login_url='/adminmaster/login/')
def show_dmf_report(request, id):
    checklist = DMFChecklistUser.objects.get(id=id)
    comments = DMFModuleComment.objects.filter(checklist=checklist)
    user = request.user
    # Get all questions
    dmf_review = DMFReviewTableQuestion.objects.all()
    dmf_ca = DMFCATableQuestion.objects.all()

    review_task_url = request.build_absolute_uri(
        reverse("show_dmf_report", args=[checklist.id])
    )
    if user.role == "company_user":
        flag = False
        assignment = AssignChecker.objects.get(user=user)
        if request.method == "POST":
            # dmf_review = DMFReviewTableQuestion.objects.all()
            comment_section = json.loads(request.POST.get("comment_section", "[]"))
            DMFModuleComment.objects.filter(checklist=checklist).delete()
            completed_by_user = bool(request.POST.get("completed"))
            # Save new comments
            for module_data in comment_section:
                module_name = module_data["module"]
                remarks = module_data["remarks"]
                statuses = module_data["statuses"]

                # Create a comment for each remark/status pair
                for remark, status in zip(remarks, statuses):
                    if remark or status:  # Only save if there's content
                        DMFModuleComment.objects.create(
                            checklist=checklist,
                            module=module_name,
                            comment=remark,
                            status=status,
                        )

            for question in dmf_review:
                drf_key = f"drf_{question.id}"
                drf_value = bool(request.POST.get(drf_key))
                ra_key = f"ra_{question.id}"
                ra_value = bool(request.POST.get(ra_key))
                ard_key = f"ard_{question.id}"
                ard_value = bool(request.POST.get(ard_key))

                if drf_value or ra_value or ard_value:
                    # Update or create answer
                    answer, created = DMFReviewAnswer.objects.update_or_create(
                        checklist=checklist,
                        dmf_review_id=question.id,
                        defaults={"drf": drf_value, "ra": ra_value, "ard": ard_value},
                    )

            # dmf_ca = DMFCATableQuestion.objects.all()

            for que in dmf_ca:
                answer_key = f"answer_{que.id}"
                answer_value = request.POST.get(answer_key)

                if answer_value:
                    answer, created = DMFCAAnswer.objects.update_or_create(
                        checklist=checklist,
                        dmf_ca_id=que.id,
                        defaults={"answer": answer_value,},
                    )

            if completed_by_user and checklist:
                checklist.is_completed_by_doer = True
                checklist.show_buttons_doer = False
                if checklist.statues is None:
                    checklist.statues = {}
                if "Your Status" not in checklist.statues:
                    checklist.statues["Your Status"] = {}
                if user.id not in checklist.statues["Your Status"]:
                    checklist.statues["Your Status"][user.id] = {}
                checklist.statues["Your Status"][user.id][user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in checklist.statues:
                        checklist.statues["Checker Level 1 Status"] = {}
                    if i.id not in checklist.statues["Checker Level 1 Status"]:
                        checklist.statues["Checker Level 1 Status"][i.id] = {}
                    checklist.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{checklist.name_of_api}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{checklist.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {checklist.name_of_api}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {checklist.name_of_api} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {checklist.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send personalized email to each checker
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {checklist.name_of_api}",
                        message=plain_message,
                        from_email=checklist.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if checklist.statues is None:
                    checklist.statues = {}
                if "Your Status" not in checklist.statues:
                    checklist.statues["Your Status"] = {}
                if user.id not in checklist.statues["Your Status"]:
                    checklist.statues["Your Status"] = {}
                    checklist.statues["Your Status"][user.id] = {}
                checklist.statues["Your Status"][user.id][user.first_name] = "Pending"
            checklist.save()

            # messages.success(request, 'Answers saved successfully!')
            return redirect("/ratools/show_dmf_table")
    elif user.role == "company_checker":
        assigned_user = checklist.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_11
        current_level =  get_checker_level(user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            print("action",action)
            if action in ["Approve", "Reject"]:
                update_checker_status(checklist, user, assignment, action, current_level, last_level, review_task_url)
                checklist.save()
            return redirect("/ratools/show_dmf_table")

        if checklist.statues[f"Checker Level {current_level} Status"][str(user.id)][user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False
    # --------------------------------

    dmf_ca_answers = {}
    # Get existing user answers
    user_answers = {}
    if checklist:
        # Change this line to include both answer and comment
        ca_answers = DMFCAAnswer.objects.filter(checklist=checklist)
        answers = DMFReviewAnswer.objects.filter(checklist=checklist)
        dmf_ca_answers = {
            ca_answer.dmf_ca_id: {
                "answer": ca_answer.answer,
            }
            for ca_answer in ca_answers
        }
        user_answers = {
            answer.dmf_review_id: {
                "drf": answer.drf,
                "ra": answer.ra,
                "ard": answer.ard,
            }
            for answer in answers
        }

    organized_data = {}
    ca_organized_data = {}
    ca_grouped_data ={}

    for que in dmf_ca:
        module = que.module
        category = None if que.category == "None" else que.category
        sub_category = None if que.sub_category == "None" else que.sub_category
        ectd_no = None if que.ectd_no == "None" else que.ectd_no
        ectd_sub_category = None if que.ectd_sub_category == "None" else que.ectd_sub_category

        if module not in ca_grouped_data:
            ca_grouped_data[module] = {}

        if ectd_no not in ca_grouped_data[module]:
            ca_grouped_data[module][ectd_no] = []


        if module not in ca_organized_data:
            ca_organized_data[module] = {}
        if category not in ca_organized_data[module]:
            ca_organized_data[module][category] = {}
        if sub_category not in ca_organized_data[module][category]:
            ca_organized_data[module][category][sub_category] = {}
        if ectd_no not in ca_organized_data[module][category][sub_category]:
            ca_organized_data[module][category][sub_category][ectd_no] = {}
            # ca_grouped_data[module][ectd_no] = {}
        if (
            ectd_sub_category
            not in ca_organized_data[module][category][sub_category][ectd_no]
        ):
            ca_organized_data[module][category][sub_category][ectd_no][
                ectd_sub_category
            ] = []

        ca_organized_data[module][category][sub_category][ectd_no][
            ectd_sub_category
        ].append(que)

        if module:
            if que.id in dmf_ca_answers:
                que.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": dmf_ca_answers[que.id]["answer"],
                    },
                )()

    for question in dmf_review:
        module = question.module
        category = question.category

        if module not in organized_data:
            organized_data[module] = {}

        if category not in organized_data[module]:
            organized_data[module][category] = []

        if category:
            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "drf": user_answers[question.id]["drf"],
                        "ra": user_answers[question.id]["ra"],
                        "ard": user_answers[question.id]["ard"],
                    },
                )()

            organized_data[module][category].append(question)
    existing_comments = {}
    for comment in comments:
        if comment.module not in existing_comments:
            existing_comments[comment.module] = {"remarks": [], "statuses": []}
        existing_comments[comment.module]["remarks"].append(comment.comment or "")
        existing_comments[comment.module]["statuses"].append(comment.status or "")

    return render(
        request,
        "RATools/DMF/DMFChecklist.html",
        {
            "checklist": checklist,
            "dmf_review": dmf_review,
            "dmf_ca": dmf_ca,
            "organized_data": organized_data,
            "ca_organized_data": ca_organized_data,
            "ca_grouped_data":ca_grouped_data,
            "existing_comments": json.dumps(existing_comments),
            "show_flag":True,
            "flag":flag,
            "complete_flag":checklist.show_buttons_doer,
        },
    )

# @login_required(login_url='/adminmaster/login/')
def show_dmf_table(request):
    user = request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/DMF/DMFChecklist.html",{"page_flag" :True,"show_flag":False,"report_name": "DMFChecklist"})

    report_name = "DMFChecklist"
    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = DMFChecklistUser.objects.filter(
            user=request.user,
        )
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = DMFChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = DMFChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = DMFChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = DMFChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = DMFChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = DMFChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = DMFChecklistUser.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = DMFChecklistUser.objects.all()
        view_sample = False

    if report_name in assigns.assigned_report or user.role == "company_checker":
        context = {
            "main_folder":"DMF Checklist",
            "table_headers": ["Sr. No.", "Name of API", "Name of API Vendor", "DMF Status","DMF No.","DMF Version","Status", "Actions"],
            "form": DMFForm(user=request.user),
            "action": "../../ratools/add_dmf_checklist/",
            "reports": reports,
            "edit_url": "/ratools/show_dmf_report",
            # "page_heading": "DMF Checklist",
            "dmf_checklist_active": True,
            "modal_body_content": "DMF...",
            "modal_title": "DMF Overview",
            "view_sample":view_sample,
            "sample_url":"/ratools/view_sample_dmf",
             "delete_url": "/ratools/dmf/delete_dmf_checklist",
        }
        return render(request, "RATools/baseShow.html", context)
    else:
        return render(request, "RATools/DMF/DMFChecklist.html",{"show_flag":False})


@login_required(login_url='/adminmaster/login/')
def delete_dmf_checklist(request, id):
    try:
        report = DMFChecklistUser.objects.get(id=id)
        # Delete any related answers/data if applicable
        # For example, if you have a model like DMFUserAnswers:
        # DMFUserAnswers.objects.filter(report=report).delete()
        report.delete()
        messages.success(request, "DMF Checklist deleted successfully!")
    except DMFChecklistUser.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")
    return redirect("/ratools/show_dmf_table")

@login_required(login_url='/adminmaster/login/')
def show_iig_proportionality_clearance_report(request, id):
    user = request.user
    checklist = get_object_or_404(IIGChecklistUser, id=id)
    static_data = get_object_or_404(IIGAnswers, checklist_id=checklist)

    if static_data.checklist_id.report == "IIG Proportionality Clearance - DPIs":
        html = "IIGDPI.html"
        back_to_list = "/ratools/show_iig_dpi"
    elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Inhalation"):
        html = "IIGInhalation.html"
        back_to_list = "/ratools/show_iig_inhalation_table"
    elif ( static_data.checklist_id.report == "IIG Proportionality Clearance - Liquid Orals"):
        html = "IIGCLiquidOrals.html"
        back_to_list = "/ratools/show_iig_liquidoral_table"
    elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Injection-Otic-Ophthalmic"):
        html = "IIGCInjectionOticOphthalmic.html"
        back_to_list = "/ratools/show_iig_injection_table"
    elif static_data.checklist_id.report == "IIG Proportionality Clearance - MDIs":
        html = "IIGMDI.html"
        back_to_list = "/ratools/show_iig_mdi_table"
    elif static_data.checklist_id.report == "IIG Proportionality Clearance - Nasals":
        html = "IIGNasals.html"
        back_to_list = "/ratools/show_iig_nasal_table"
    elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Semisolids"):
        html = "IIGSemiSolids.html"
        back_to_list = "/ratools/show_iig_semisolid_table"
    elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Tablets & Capsules"):
        html = "IIGTabletsAndCapsules.html"
        back_to_list = "/ratools/show_iig_tablet_table"
    elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Topical Solutions & Lotions"):
        html = "IIGTopicalSolutionsAndLotions.html"
        back_to_list = "/ratools/show_iig_topical_table"
    elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Transdermal"):
        html = "IIGTransdermal.html"
        back_to_list = "/ratools/show_iig_transdermal_table"

    elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Liposomes"):
        html = "IIGLiposome.html"
        back_to_list = "/ratools/show_iig_liposome"

    elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Microspheres"):
        html = "IIGMicrosphere.html"
        back_to_list = "/ratools/show_iig_microsphere"


    review_task_url = request.build_absolute_uri(
        reverse("show_iig_proportionality_clearance_report", args=[checklist.id])
    )

    if user.role == "company_user":
        flag = False
        assignment = AssignChecker.objects.get(user=user)
        if request.method == "POST":
            print(request.POST)
            completed_by_user = bool(request.POST.get("completed"))

            # Process the form data
            static_data.project_initiation_phase = bool(
                request.POST.get("project_initiation_phase")
            )
            static_data.frozen_formulation_phase = bool(
                request.POST.get("frozen_formulation_phase")
            )
            static_data.final_iig_clearance = bool(request.POST.get("final_iig_clearance"))
            static_data.date = request.POST.get("date")
            static_data.max_daily_dose_rld = request.POST.get("max_daily_dose_rld")
            static_data.max_daily_dose_rs = request.POST.get("max_daily_dose_rs")
            static_data.brand_name_rld = request.POST.get("brand_name_rld")
            static_data.strength_rld = request.POST.get("strength_rld")
            static_data.nda_anda_rld = request.POST.get("nda_anda_rld")
            static_data.brand_name_rs = request.POST.get("brand_name_rs")
            static_data.strength_rs = request.POST.get("strength_rs")
            static_data.nda_anda_rs = request.POST.get("nda_anda_rs")
            static_data.total_dose = request.POST.get("total_dose")
            static_data.density = request.POST.get("density")
            static_data.cmc_1 = request.POST.get("cmc_1")
            static_data.cmc_1_1 = request.POST.get("cmc_1_1")
            static_data.cmc_2 = request.POST.get("cmc_2")
            static_data.cmc_3 = request.POST.get("cmc_3")
            static_data.clinical_1 = request.POST.get("clinical_1")
            static_data.clinical_2 = request.POST.get("clinical_2")
            static_data.clinical_3 = request.POST.get("clinical_3")
            static_data.save()
            rld_insert_snapshot={
                "iig_answer":static_data,
                "snapshot": request.FILES.get("rld_insert_snapshot"),
            }
            IIGAnswerSnapshot.objects.create(**rld_insert_snapshot)

            # Process table data if present
            table_data = request.POST.get("tableData")
            print("table data", table_data)
            if table_data:
                try:
                    table_data = json.loads(table_data)
                    print("Parsed table data:", table_data)  # Debugging

                    # Get existing rows for this static_data
                    existing_rows = IIGTableRowsAnswers.objects.filter(static_rel=static_data)
                    existing_row_ids = set(existing_rows.values_list('id', flat=True))

                    # Track new row IDs from the submitted data
                    new_row_ids = set()
                    if (
                        static_data.checklist_id.report
                        == "IIG Proportionality Clearance - Tablets & Capsules"
                        or static_data.checklist_id.report
                        == "IIG Proportionality Clearance - Transdermal"
                       ):
                        for row in table_data:
                            print("Processing row:", row)  # Debugging
                            row_id = row.get("id")
                            print("Row id",row_id)
                            #  not row_id.startswith("row_")
                            if not row_id.startswith("row_"):
                                # Update existing row
                                iig_table_object = existing_rows.filter(id=row_id).first()
                                if iig_table_object:
                                    print("Updating existing row:", iig_table_object.id)  # Debugging
                                    for field in [
                                        "rm_code", "ingredients", "func_of_excpt", "all_strength_dose",
                                        "all_strength_w", "max_amount","molar_ratio","route",
                                        "max_potency", "max_dailyexp"
                                    ]:
                                        setattr(iig_table_object, field, row[field])
                                    iig_table_object.save()
                                    new_row_ids.add(iig_table_object.id)
                                    snap_shot_data={
                                        "iig_table":iig_table_object,
                                        "snapshot":row['snapshot']
                                    }
                                    IIGSnapshot.objects.create(**snap_shot_data)
                            else:
                                # Create new row
                                print("Creating new row")  # Debugging
                                iig_table_object = IIGTableRowsAnswers.objects.create(
                                    static_rel=static_data,
                                    rm_code=row["rm_code"],
                                    ingredients=row["ingredients"],
                                    func_of_excpt=row["func_of_excpt"],
                                    all_strength_dose=row["all_strength_dose"],
                                    all_strength_w=row["all_strength_w"],
                                    max_amount=row["max_amount"],
                                    route=row["route"],
                                    max_potency=row["max_potency"],
                                    max_dailyexp=row["max_dailyexp"],
                                    molar_ratio=row["molar_ratio"]# new
                                )
                                new_row_ids.add(iig_table_object.id)
                                snap_shot_data={
                                        "iig_table":iig_table_object,
                                        "snapshot":row['snapshot']
                                    }
                                IIGSnapshot.objects.create(**snap_shot_data)

                            # Handle snapshots
                            # snapshots = request.FILES.getlist(f'data[{row.get("row_id")}][snapshot]')
                            # for snapshot in snapshots:
                            #     if snapshot:
                            #         print("Creating snapshot for row:", iig_table_object.id)  # Debugging
                            #         IIGSnapshot.objects.create(iig_table=iig_table_object, snapshot=snapshot)

                    else:
                        for row in table_data:
                            print("Processing row:", row)  # Debugging
                            row_id = row.get("id")
                            print("Row id",row_id)
                            #  not row_id.startswith("row_")
                            if not row_id.startswith("row_"):
                                # Update existing row
                                iig_table_object = existing_rows.filter(id=row_id).first()
                                if iig_table_object:
                                    print("Updating existing row:", iig_table_object.id)  # Debugging
                                    for field in [
                                        "rm_code", "ingredients", "func_of_excpt", "all_strength_dose",
                                        "all_strength_amount", "all_strength_w", "max_amount", "route",
                                        "max_potency", "max_dailyexp","molar_ratio" ,
                                    ]:
                                        setattr(iig_table_object, field, row[field])
                                    iig_table_object.save()
                                    new_row_ids.add(iig_table_object.id)
                                    snap_shot_data={
                                        "iig_table":iig_table_object,
                                        "snapshot":row['snapshot']
                                    }
                                    IIGSnapshot.objects.create(**snap_shot_data)
                            else:
                                # Create new row
                                print("Creating new row")  # Debugging
                                iig_table_object = IIGTableRowsAnswers.objects.create(
                                    static_rel=static_data,
                                    rm_code=row["rm_code"],
                                    ingredients=row["ingredients"],
                                    func_of_excpt=row["func_of_excpt"],
                                    all_strength_dose=row["all_strength_dose"],
                                    all_strength_amount=row["all_strength_amount"],
                                    all_strength_w=row["all_strength_w"],
                                    max_amount=row["max_amount"],
                                    route=row["route"],
                                    max_potency=row["max_potency"],
                                    max_dailyexp=row["max_dailyexp"],
                                    molar_ratio=row["molar_ratio"] ,#new
                                )
                                new_row_ids.add(iig_table_object.id)
                                snap_shot_data={
                                        "iig_table":iig_table_object,
                                        "snapshot":row['snapshot']
                                    }
                                IIGSnapshot.objects.create(**snap_shot_data)

                            # Handle snapshots
                            # snapshots = request.FILES.getlist(f'data[{row.get("row_id")}][snapshot]')
                            # for snapshot in snapshots:
                            #     if snapshot:
                            #         print("Creating snapshot for row:", iig_table_object.id)  # Debugging
                            #         IIGSnapshot.objects.create(iig_table=iig_table_object, snapshot=snapshot)

                    # Delete rows that are no longer in the submitted data
                    # rows_to_delete = existing_row_ids - new_row_ids
                    # if rows_to_delete:
                    #     print("Deleting rows:", rows_to_delete)  # Debugging
                    #     IIGTableRowsAnswers.objects.filter(id__in=rows_to_delete).delete()

                except json.JSONDecodeError:
                    print("Error decoding table data")
                except Exception as e:
                    print(f"Error saving table data: {str(e)}")
            # if table_data:
            #     try:
            #         table_data = json.loads(table_data)

            #         # Get existing rows for this static_data
            #         existing_rows = IIGTableRowsAnswers.objects.filter(static_rel=static_data)
            #         existing_row_ids = set(existing_rows.values_list('id', flat=True))

            #         # Track new row IDs from the submitted data
            #         new_row_ids = set()

            #         for row in table_data:
            #             row_id = row.get("id")
            #             if row_id:
            #                 # Update existing row
            #                 iig_table_object = existing_rows.filter(id=row_id).first()
            #                 if iig_table_object:
            #                     for field in [
            #                         "rm_code", "ingredients", "func_of_excpt", "all_strength_dose",
            #                         "all_strength_amount", "all_strength_w", "max_amount", "route",
            #                         "max_potency", "max_dailyexp"
            #                     ]:
            #                         setattr(iig_table_object, field, row[field])
            #                     iig_table_object.save()
            #                     new_row_ids.add(iig_table_object.id)
            #             else:
            #                 # Create new row
            #                 iig_table_object = IIGTableRowsAnswers.objects.create(
            #                     static_rel=static_data,
            #                     rm_code=row["rm_code"],
            #                     ingredients=row["ingredients"],
            #                     func_of_excpt=row["func_of_excpt"],
            #                     all_strength_dose=row["all_strength_dose"],
            #                     all_strength_amount=row["all_strength_amount"],
            #                     all_strength_w=row["all_strength_w"],
            #                     max_amount=row["max_amount"],
            #                     route=row["route"],
            #                     max_potency=row["max_potency"],
            #                     max_dailyexp=row["max_dailyexp"],
            #                 )
            #                 new_row_ids.add(iig_table_object.id)

            #             # Handle snapshots
            #             snapshots = request.FILES.getlist(f'data[{row.get("row_id")}][snapshot]')
            #             for snapshot in snapshots:
            #                 if snapshot:
            #                     IIGSnapshot.objects.create(iig_table=iig_table_object, snapshot=snapshot)

            #         # Delete rows that are no longer in the submitted data
            #         rows_to_delete = existing_row_ids - new_row_ids
            #         if rows_to_delete:
            #             IIGTableRowsAnswers.objects.filter(id__in=rows_to_delete).delete()

            #     except json.JSONDecodeError:
            #         print("Error decoding table data")
            #     except Exception as e:
            #         print(f"Error saving table data: {str(e)}")

            # Update checklist status
            if completed_by_user and checklist:
                checklist.is_completed_by_doer = True
                checklist.show_buttons_doer = False
                if checklist.statues is None:
                    checklist.statues = {}
                if "Your Status" not in checklist.statues:
                    checklist.statues["Your Status"] = {}
                checklist.statues["Your Status"][user.id] = {user.first_name: "Submitted"}

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in checklist.statues:
                        checklist.statues["Checker Level 1 Status"] = {}
                    checklist.statues["Checker Level 1 Status"][i.id] = {i.first_name: "In Review"}

                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{checklist.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{checklist.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {checklist.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {checklist.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {checklist.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send personalized email to each checker
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {checklist.product_name}",
                        message=plain_message,
                        from_email=checklist.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if checklist.statues is None:
                    checklist.statues = {}
                if "Your Status" not in checklist.statues:
                    checklist.statues["Your Status"] = {}
                checklist.statues["Your Status"][user.id] = {user.first_name: "Pending"}
            checklist.save()

            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {"status": "success", "message": "Data saved successfully", "redirect": back_to_list}
                )

    elif user.role == "company_checker":
        assigned_user = checklist.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        if static_data.checklist_id.report == "IIG Proportionality Clearance - DPIs":
            last_level = assignment.level_report_12
        elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Inhalation"):
            last_level = assignment.level_report_13
        elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Liquid Orals"):
            last_level = assignment.level_report_14
        elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Injection-Otic-Ophthalmic"):
            last_level = assignment.level_report_15
        elif static_data.checklist_id.report == "IIG Proportionality Clearance - MDIs":
            last_level = assignment.level_report_16
        elif static_data.checklist_id.report == "IIG Proportionality Clearance - Nasals":
            last_level = assignment.level_report_17
        elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Semisolids"):
            last_level = assignment.level_report_18
        elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Tablets & Capsules"):
            last_level = assignment.level_report_19
        elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Topical Solutions & Lotions"):
            last_level = assignment.level_report_20
        elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Transdermal"):
            last_level = assignment.level_report_21

        elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Liposomes"):
            last_level = assignment.level_report_22

        elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Microspheres"):
            last_level = assignment.level_report_23


        current_level = get_checker_level(user.id, assignment.checkers_json)

        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(checklist, user, assignment, action, current_level, last_level, review_task_url)
                checklist.save()
            return redirect(back_to_list)

        flag = checklist.statues.get(f"Checker Level {current_level} Status", {}).get(str(user.id), {}).get(user.first_name) == "In Review"
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    multi_data = IIGTableRowsAnswers.objects.filter(static_rel=static_data).prefetch_related('snapshots')
    static_snapshots = IIGAnswerSnapshot.objects.filter(iig_answer=static_data)
    return render(
        request,
        f"RATools/IIG/{html}",
        {
            "checklist": checklist,
            "static_data": static_data,
            "multi_data": multi_data,
            "back_to_list": back_to_list,
            "show_flag": True,
            "flag": flag,
            "complete_flag": checklist.show_buttons_doer,
            "static_snapshots":static_snapshots,
        },
    )

# # IIG Views Function Should be below this line
# @login_required(login_url='/adminmaster/login/')
# def show_iig_proportionality_clearance_report(request, id):
#     user = request.user
#     checklist = get_object_or_404(IIGChecklistUser, id=id)
#     static_data = get_object_or_404(IIGAnswers, checklist_id=checklist)
#     if static_data.checklist_id.report == "IIG Proportionality Clearance - DPIs":
#         html = "IIGDPI.html"
#         back_to_list = "/ratools/show_iig_dpi"
#     elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Inhalation"):
#         html = "IIGInhalation.html"
#         back_to_list = "/ratools/show_iig_inhalation_table"
#     elif ( static_data.checklist_id.report == "IIG Proportionality Clearance - Liquid Orals"):
#         html = "IIGCLiquidOrals.html"
#         back_to_list = "/ratools/show_iig_liquidoral_table"
#     elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Injection-Otic-Ophthalmic"):
#         html = "IIGCInjectionOticOphthalmic.html"
#         back_to_list = "/ratools/show_iig_injection_table"
#     elif static_data.checklist_id.report == "IIG Proportionality Clearance - MDIs":
#         html = "IIGMDI.html"
#         back_to_list = "/ratools/show_iig_mdi_table"
#     elif static_data.checklist_id.report == "IIG Proportionality Clearance - Nasals":
#         html = "IIGNasals.html"
#         back_to_list = "/ratools/show_iig_nasal_table"
#     elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Semisolids"):
#         html = "IIGSemiSolids.html"
#         back_to_list = "/ratools/show_iig_semisolid_table"
#     elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Tablets & Capsules"):
#         html = "IIGTabletsAndCapsules.html"
#         back_to_list = "/ratools/show_iig_tablet_table"
#     elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Topical Solutions & Lotions"):
#         html = "IIGTopicalSolutionsAndLotions.html"
#         back_to_list = "/ratools/show_iig_topical_table"
#     elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Transdermal"):
#         html = "IIGTransdermal.html"
#         back_to_list = "/ratools/show_iig_transdermal_table"

#     if user.role == "company_user":
#         flag=False
#         assignment = AssignChecker.objects.get(user=user)
#         if request.method == "POST":
#             print(request.POST)
#             completed_by_user = bool(request.POST.get("completed"))
#             # Process the form data
#             static_data.project_initiation_phase = bool(
#                 request.POST.get("project_initiation_phase")
#             )
#             static_data.frozen_formulation_phase = bool(
#                 request.POST.get("frozen_formulation_phase")
#             )
#             static_data.final_iig_clearance = bool(request.POST.get("final_iig_clearance"))
#             static_data.date = request.POST.get("date")
#             static_data.max_daily_dose_rld = request.POST.get("max_daily_dose_rld")
#             static_data.max_daily_dose_rs = request.POST.get("max_daily_dose_rs")
#             static_data.brand_name_rld = request.POST.get("brand_name_rld")
#             static_data.strength_rld = request.POST.get("strength_rld")
#             static_data.nda_anda_rld = request.POST.get("nda_anda_rld")
#             static_data.brand_name_rs = request.POST.get("brand_name_rs")
#             static_data.strength_rs = request.POST.get("strength_rs")
#             static_data.nda_anda_rs = request.POST.get("nda_anda_rs")
#             static_data.rld_insert_snapshot = request.POST.get("rld_insert_snapshot")
#             static_data.total_dose = request.POST.get("total_dose")
#             static_data.density = request.POST.get("density")
#             static_data.cmc_1 = request.POST.get("cmc_1")
#             static_data.cmc_1_1 = request.POST.get("cmc_1_1")
#             static_data.cmc_2 = request.POST.get("cmc_2")
#             static_data.cmc_3 = request.POST.get("cmc_3")
#             static_data.clinical_1 = request.POST.get("clinical_1")
#             static_data.clinical_2 = request.POST.get("clinical_2")
#             static_data.clinical_3 = request.POST.get("clinical_3")
#             static_data.save()
#             # Process table data if present
#             table_data = request.POST.get("tableData")
#             print("table data",table_data)
#             if table_data:
#                 try:
#                     table_data = json.loads(table_data)

#                     # First, delete existing instances for this static_data
#                     IIGTableRowsAnswers.objects.filter(static_rel=static_data).delete()

#                     if (
#                         static_data.checklist_id.report
#                         == "IIG Proportionality Clearance - Tablets & Capsules"
#                         and static_data.checklist_id.report
#                         == "IIG Proportionality Clearance - Tablets & Capsules"
#                        ):
#                         # Create new instances for each row
#                         for row in table_data:
#                             iig_table_object = IIGTableRowsAnswers.objects.create(
#                                 static_rel=static_data,
#                                 rm_code=row["rm_code"],
#                                 ingredients=row["ingredients"],
#                                 func_of_excpt=row["func_of_excpt"],
#                                 all_strength_dose=row["all_strength_dose"],
#                                 all_strength_w=row["all_strength_w"],
#                                 max_amount=row["max_amount"],
#                                 route=row["route"],
#                                 max_potency=row["max_potency"],
#                                 max_dailyexp=row["max_dailyexp"],
#                                 # snapshot=row["snapshot"],
#                             )
#                             snap_shot_data={
#                                 "iig_table":iig_table_object,
#                                 "snapshot":row['snapshot']
#                             }
#                             IIGSnapshot.objects.create(**snap_shot_data)
#                     else:
#                         for row in table_data:
#                             data = {
#                                 'static_rel':static_data,
#                                 'rm_code':row["rm_code"],
#                                 'ingredients':row["ingredients"],
#                                 'func_of_excpt':row["func_of_excpt"],
#                                 'all_strength_dose':row["all_strength_dose"],
#                                 'all_strength_amount':row["all_strength_amount"],
#                                 'all_strength_w':row["all_strength_w"],
#                                 'max_amount':row["max_amount"],
#                                 'route':row["route"],
#                                 'max_potency':row["max_potency"],
#                                 'max_dailyexp':row["max_dailyexp"],
#                                 # 'snapshot' : row['snapshot']
#                             }
#                             iig_table_object = IIGTableRowsAnswers.objects.create(**data)
#                             snap_shot_data={
#                                 "iig_table":iig_table_object,
#                                 "snapshot":row['snapshot']
#                             }
#                             IIGSnapshot.objects.create(**snap_shot_data)

#                 except json.JSONDecodeError:
#                     print("Error decoding table data")
#                 except Exception as e:
#                     print(f"Error saving table data: {str(e)}")

#             # If it's an AJAX request, return JSON response
#             if completed_by_user and checklist:
#                 checklist.is_completed_by_doer = True
#                 checklist.show_buttons_doer = False
#                 if checklist.statues is None:
#                     checklist.statues = {}
#                 if "Your Status" not in checklist.statues:
#                     checklist.statues["Your Status"] = {}
#                 if user.id not in checklist.statues["Your Status"]:
#                     checklist.statues["Your Status"][user.id] = {}
#                 checklist.statues["Your Status"][user.id][user.first_name] = "Submitted"

#                 for i in assignment.assigned_checker_level_1.all():
#                     if "Checker Level 1 Status" not in checklist.statues:
#                         checklist.statues["Checker Level 1 Status"] = {}
#                     if i.id not in checklist.statues["Checker Level 1 Status"]:
#                         checklist.statues["Checker Level 1 Status"][i.id] = {}
#                     checklist.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"
#             else:
#                 if checklist.statues is None:
#                     checklist.statues = {}
#                 if "Your Status" not in checklist.statues:
#                     checklist.statues["Your Status"] = {}
#                 if user.id not in checklist.statues["Your Status"]:
#                     checklist.statues["Your Status"] = {}
#                     checklist.statues["Your Status"][user.id] = {}
#                 checklist.statues["Your Status"][user.id][user.first_name] = "Pending"
#             checklist.save()

#             if request.headers.get("X-Requested-With") == "XMLHttpRequest":
#                 return JsonResponse(
#                     {"status": "success", "message": "Data saved successfully", "redirect":back_to_list}
#                 )
#             # For regular form submissions, continue with the normal render
#     elif user.role == "company_checker":
#         assigned_user = checklist.user
#         assignment = AssignChecker.objects.get(user=assigned_user)
#         if static_data.checklist_id.report == "IIG Proportionality Clearance - DPIs":
#             last_level = assignment.level_report_10
#         elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Inhalation"):
#             last_level = assignment.level_report_11
#         elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Liquid Orals"):
#             last_level = assignment.level_report_12
#         elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Injection-Otic-Ophthalmic"):
#             last_level = assignment.level_report_13
#         elif static_data.checklist_id.report == "IIG Proportionality Clearance - MDIs":
#             last_level = assignment.level_report_14
#         elif static_data.checklist_id.report == "IIG Proportionality Clearance - Nasals":
#             last_level = assignment.level_report_15
#         elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Semisolids"):
#             last_level = assignment.level_report_16
#         elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Tablets & Capsules"):
#             last_level = assignment.level_report_17
#         elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Topical Solutions & Lotions"):
#             last_level = assignment.level_report_18
#         elif (static_data.checklist_id.report == "IIG Proportionality Clearance - Transdermal"):
#             last_level = assignment.level_report_19

#         current_level =  get_checker_level(user.id, assignment.checkers_json)
#         if request.method == "POST":
#             action = request.POST.get("checker_action")
#             if action in ["Approve", "Reject"]:
#                 update_checker_status(checklist, user, assignment, action, current_level, last_level)
#                 checklist.save()
#             return redirect(back_to_list)

#         if checklist.statues[f"Checker Level {current_level} Status"][str(user.id)][user.first_name] == "In Review":
#             flag = True
#         else:
#             flag = False
#     multi_data = IIGTableRowsAnswers.objects.filter(static_rel=static_data).prefetch_related('snapshots')
#     return render(
#         request,
#         f"RATools/IIG/{html}",
#         {
#             "checklist": checklist,
#             "static_data": static_data,
#             "multi_data": multi_data,
#             "back_to_list": back_to_list,
#             "show_flag":True,
#             "flag":flag,
#             "complete_flag":checklist.show_buttons_doer,
#         },
#     )

@login_required(login_url='/adminmaster/login/')
def view_sample_iig_reports(request, report_name):
    if report_name == "IIG Proportionality Clearance - DPIs":
        html = "RATools/IIG/IIGDPI.html"
        back_to_list = "/ratools/show_iig_dpi"
    elif report_name == "IIG Proportionality Clearance - Inhalation":
        html = "RATools/IIG/IIGInhalation.html"
        back_to_list = "/ratools/show_iig_inhalation_table"
    elif report_name == "IIG Proportionality Clearance - Liquid Orals":
        html = "RATools/IIG/IIGCLiquidOrals.html"
        back_to_list = "/ratools/show_iig_liquidoral_table"
    elif report_name == "IIG Proportionality Clearance - Injection-Otic-Ophthalmic":
        html = "RATools/IIG/IIGCInjectionOticOphthalmic.html"
        back_to_list = "/ratools/show_iig_injection_table"
    elif report_name == "IIG Proportionality Clearance - MDIs":
        html = "RATools/IIG/IIGMDI.html"
        back_to_list = "/ratools/show_iig_mdi_table"
    elif report_name == "IIG Proportionality Clearance - Semisolids":
        html = "RATools/IIG/IIGSemiSolids.html"
        back_to_list = "/ratools/show_iig_semisolid_table"
    elif report_name == "IIG Proportionality Clearance - Nasals":
        html = "RATools/IIG/IIGNasals.html"
        back_to_list = "/ratools/show_iig_nasal_table"
    elif report_name == "IIG Proportionality Clearance - Tablets & Capsules":
        html = "RATools/IIG/IIGTabletsAndCapsules.html"
        back_to_list = "/ratools/show_iig_tablet_table"
    elif report_name == "IIG Proportionality Clearance - Topical Solutions & Lotions":
        html = "RATools/IIG/IIGTopicalSolutionsAndLotions.html"
        back_to_list = "/ratools/show_iig_topical_table"
    elif report_name == "IIG Proportionality Clearance - Transdermal":
        html = "RATools/IIG/IIGTransdermal.html"
        back_to_list = "/ratools/show_iig_transdermal_table"

    elif report_name == "IIG Proportionality Clearance - Liposomes":
        html = "RATools/IIG/IIGLiposome.html"
        back_to_list = "/ratools/show_iig_liposome"


    elif report_name == "IIG Proportionality Clearance - Microspheres":
        html = "RATools/IIG/IIGMicrosphere.html"
        back_to_list = "/ratools/show_iig_microsphere"



    context = {"back_to_list":back_to_list,"show_flag":True,
               "flag":False, "complete_flag":False
               }
    return render(request, html, context)

#


#LIPOSOME
def show_iig_liposome(request):
    user = request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/IIG/IIGLiposome.html", {"page_flag" :True,"show_flag":False})

    report_name = "IIG Proportionality Clearance - Liposomes"
    form = IIGForm(user=user, report=report_name)
    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = IIGChecklistUser.objects.filter(
            user=request.user,report=report_name
        )
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            is_completed_by_doer=True,
            report=report_name
        )
        checklists_as_checker_2 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            approved_by_checkers_level_1="True",
            report=report_name
        )
        checklists_as_checker_3 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            approved_by_checkers_level_2="True",
            report=report_name
        )
        checklists_as_checker_4 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            approved_by_checkers_level_3="True",
            report=report_name
        )
        checklists_as_checker_5 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            approved_by_checkers_level_4="True",
            report=report_name
        )
        checklists_as_checker_6 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            approved_by_checkers_level_5="True",
            report=report_name
        )
        checklists_as_checker_7 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            approved_by_checkers_level_6="True",
            report=report_name
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = IIGChecklistUser.objects.filter(report=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        return render(
            request,
            "RATools/baseShow.html",
            {
                "main_folder": "IIG Proportionality Clearance Checklist",
                "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
                "page_heading": "Liposomes",
                "reports": reports,
                "form": form,
                "action": "../../ratools/add_iig_liposome_checklist/",
                "edit_url": "/ratools/show_iig_proportionality_clearance_report",
                "delete_url": "/ratools/delete_iig_checklist_liposome",
                "proportionality_clearance_liposomes": True,
                "iig_checklist_active": True,
                "modal_body_content": "Liposomes...",
                "modal_title": "Liposomes Overview",
                "view_sample": view_sample,
                "sample_url": f"/ratools/view_sample_iig_reports/{report_name}"
            },
        )
    else:
        return render(request, "RATools/IIG/IIGLiposome.html", {"show_flag":False})

@login_required(login_url='/adminmaster/login/')
def add_iig_liposome_checklist(request):
    report_name = "IIG Proportionality Clearance - Liposomes"
    if request.method == "POST":
        form = IIGForm(
            request.POST,
            user=request.user,
            report=report_name,
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("../../ratools/show_iig_liposome")

@login_required(login_url='/adminmaster/login/')
def delete_iig_checklist_liposome(request, id):
    report_name = "IIG Proportionality Clearance - Liposomes"
    checklist = IIGChecklistUser.objects.get(report=report_name, id=id)
    checklist.delete()
    return redirect("../../ratools/show_iig_liposome")


def show_iig_microsphere(request):
    user = request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/IIG/IIGMicrosphere.html", {"page_flag" :True,"show_flag": False})

    report_name = "IIG Proportionality Clearance - Microspheres"
    form = IIGForm(user=user, report=report_name)
    assigns = AssignChecker.objects.get(user=user)

    if user.role == "company_user":
        view_sample = False
        reports = IIGChecklistUser.objects.filter(
            user=request.user,
            report=report_name
        )
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False

        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            is_completed_by_doer=True,
            report=report_name
        )
        checklists_as_checker_2 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            approved_by_checkers_level_1="True",
            report=report_name
        )
        checklists_as_checker_3 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            approved_by_checkers_level_2="True",
            report=report_name
        )
        checklists_as_checker_4 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            approved_by_checkers_level_3="True",
            report=report_name
        )
        checklists_as_checker_5 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            approved_by_checkers_level_4="True",
            report=report_name
        )
        checklists_as_checker_6 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            approved_by_checkers_level_5="True",
            report=report_name
        )
        checklists_as_checker_7 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_7
            ],
            approved_by_checkers_level_6="True",
            report=report_name
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = IIGChecklistUser.objects.filter(report=report_name)
        view_sample = False

    if report_name in assigns.assigned_report or user.role == "company_checker":
        return render(
            request,
            "RATools/baseShow.html",
            {
                "main_folder": "IIG Proportionality Clearance Checklist",
                "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
                "page_heading": "Microspheres",
                "reports": reports,
                "form": form,
                "action": "../../ratools/add_iig_microsphere_checklist/",
                "edit_url": "/ratools/show_iig_proportionality_clearance_report",
                "delete_url": "/ratools/delete_iig_checklist_microsphere",
                "proportionality_clearance_microspheres": True,
                "iig_checklist_active": True,
                "modal_body_content": "Microspheres...",
                "modal_title": "Microspheres Overview",
                "view_sample": view_sample,
                "sample_url": f"/ratools/view_sample_iig_reports/{report_name}"
            },
        )
    else:
        return render(request, "RATools/IIG/IIGMicrosphere.html", {"show_flag": False})

@login_required(login_url='/adminmaster/login/')
def add_iig_microsphere_checklist(request):
    report_name = "IIG Proportionality Clearance - Microspheres"
    if request.method == "POST":
        form = IIGForm(
            request.POST,
            user=request.user,
            report=report_name,
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("../../ratools/show_iig_microsphere")

@login_required(login_url='/adminmaster/login/')
def delete_iig_checklist_microsphere(request, id):
    report_name = "IIG Proportionality Clearance - Microspheres"
    checklist = IIGChecklistUser.objects.get(report=report_name, id=id)
    checklist.delete()
    return redirect("../../ratools/show_iig_microsphere")

#  for DPI Report
# @login_required(login_url='/adminmaster/login/')
def show_iig_dpi(request):
    user = request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/IIG/IIGDPI.html", {"page_flag" :True,"show_flag":False})

    report_name = "IIG Proportionality Clearance - DPIs"
    form = IIGForm(user=user, report=report_name)
    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = IIGChecklistUser.objects.filter(
            user=request.user,report=report_name
        )
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            is_completed_by_doer=True,
            report=report_name
        )
        checklists_as_checker_2 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            approved_by_checkers_level_1="True",
            report=report_name
        )
        checklists_as_checker_3 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            approved_by_checkers_level_2="True",
            report=report_name
        )
        checklists_as_checker_4 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            approved_by_checkers_level_3="True",
            report=report_name
        )
        checklists_as_checker_5 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            approved_by_checkers_level_4="True",
            report=report_name
        )
        checklists_as_checker_6 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            approved_by_checkers_level_5="True",
            report=report_name
        )
        checklists_as_checker_7 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            approved_by_checkers_level_6="True",
            report=report_name
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = IIGChecklistUser.objects.filter(report=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        return render(
            request,
            "RATools/baseShow.html",
            {
                "main_folder":"IIG Proportionality Clearance Checklist",
                "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
                "page_heading": "DPIs",
                "reports": reports,
                "form": form,
                "action": "../../ratools/add_iig_dpi_checklist/",
                "edit_url": "/ratools/show_iig_proportionality_clearance_report",
                "delete_url": "/ratools/delete_iig_checklist_dpi",
                "proportionality_clearance_dpis": True,
                "iig_checklist_active": True,
                "modal_body_content": "DPIs....",
                "modal_title": "DPIs Overview",
                "view_sample":view_sample,
                "sample_url":f"/ratools/view_sample_iig_reports/{report_name}"
            },
        )
    else:
        return render(request, "RATools/IIG/IIGDPI.html", {"show_flag":False})

@login_required(login_url='/adminmaster/login/')
def add_iig_dpi_checklist(request):
    report_name = "IIG Proportionality Clearance - DPIs"
    if request.method == "POST":
        form = IIGForm(
            request.POST,
            user=request.user,
            report=report_name,
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("../../ratools/show_iig_dpi")

@login_required(login_url='/adminmaster/login/')
def delete_iig_checklist_dpi(request, id):
    report_name = "IIG Proportionality Clearance - DPIs"
    checklist = IIGChecklistUser.objects.get(report=report_name, id=id)
    checklist.delete()
    return redirect("../../ratools/show_iig_dpi")


# for Inhalation
# @login_required(login_url='/adminmaster/login/')
def show_iig_inhalation_table(request):
    user = request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/IIG/IIGInhalation.html", {"page_flag" :True,"show_flag":False})

    report_name = "IIG Proportionality Clearance - Inhalation"
    form = IIGForm(user=user, report=report_name)
    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = IIGChecklistUser.objects.filter(
            user=request.user, report=report_name
        )
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            is_completed_by_doer=True,
            report=report_name
        )
        checklists_as_checker_2 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            approved_by_checkers_level_1="True",
            report=report_name
        )
        checklists_as_checker_3 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            approved_by_checkers_level_2="True",
            report=report_name
        )
        checklists_as_checker_4 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            approved_by_checkers_level_3="True",
            report=report_name
        )
        checklists_as_checker_5 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            approved_by_checkers_level_4="True",
            report=report_name
        )
        checklists_as_checker_6 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            approved_by_checkers_level_5="True",
            report=report_name
        )
        checklists_as_checker_7 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            approved_by_checkers_level_6="True",
            report=report_name
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = IIGChecklistUser.objects.filter(report=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        return render(
            request,
            "RATools/baseShow.html",
            {
                "main_folder":"IIG Proportionality Clearance Checklist",
                "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
                "page_heading": "Inhalation",
                "reports": reports,
                "form": form,
                "action": "../../ratools/add_iig_inhalation_checklist/",
                "edit_url": "/ratools/show_iig_proportionality_clearance_report",
                "delete_url": "/ratools/delete_iig_checklist_inhalation",
                "Proportionality_clearance_inhalation": True,
                "modal_body_content": "Inhalation ...",
                "modal_title": "Inhalation Overview",
                "view_sample":view_sample,
                "sample_url":f"/ratools/view_sample_iig_reports/{report_name}",
            },
        )
    else:
        return render(request, "RATools/IIG/IIGInhalation.html", {"show_flag":False})


@login_required(login_url='/adminmaster/login/')
def add_iig_inhalation_checklist(request):
    report_name = "IIG Proportionality Clearance - Inhalation"
    if request.method == "POST":
        form = IIGForm(
            request.POST,
            user=request.user,
            report=report_name,
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("../../ratools/show_iig_inhalation_table")

@login_required(login_url='/adminmaster/login/')
def delete_iig_checklist_inhalation(request, id):
    report_name = "IIG Proportionality Clearance - Inhalation"
    checklist = IIGChecklistUser.objects.get(report=report_name, id=id)
    checklist.delete()
    return redirect("../../ratools/show_iig_inhalation_table")

# @login_required(login_url='/adminmaster/login/')
def show_iig_liquidoral_table(request):
    user = request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/IIG/IIGCLiquidOrals.html", {"page_flag" :True,"show_flag":False})

    report_name = "IIG Proportionality Clearance - Liquid Orals"
    form = IIGForm(user=user, report=report_name)
    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = IIGChecklistUser.objects.filter(
            user=request.user,report=report_name
        )
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            is_completed_by_doer=True,
            report=report_name
        )
        checklists_as_checker_2 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            approved_by_checkers_level_1="True",
            report=report_name
        )
        checklists_as_checker_3 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            approved_by_checkers_level_2="True",
            report=report_name
        )
        checklists_as_checker_4 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            approved_by_checkers_level_3="True",
            report=report_name
        )
        checklists_as_checker_5 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            approved_by_checkers_level_4="True",
            report=report_name
        )
        checklists_as_checker_6 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            approved_by_checkers_level_5="True",
            report=report_name
        )
        checklists_as_checker_7 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            approved_by_checkers_level_6="True",
            report=report_name
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = IIGChecklistUser.objects.filter(report=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        return render(
            request,
            "RATools/baseShow.html",
            {
                "main_folder":"IIG Proportionality Clearance Checklist",
                "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
                "page_heading": "Liquid Orals",
                "reports": reports,
                "form": form,
                "action": "../../ratools/add_iig_liquidoral_checklist/",
                "edit_url": "/ratools/show_iig_proportionality_clearance_report",
                "delete_url": "/ratools/delete_iig_checklist_liquidoral",
                "Proportionality_clearance_liquid_orals": True,
                "modal_body_content": "Liquid Orals....",
                "modal_title": "Liquid Orals Overview",
                "view_sample":view_sample,
                "sample_url":f"/ratools/view_sample_iig_reports/{report_name}"
            },
        )
    else:
        return render(request, "RATools/IIG/IIGCLiquidOrals.html", {"show_flag":False})


@login_required(login_url='/adminmaster/login/')
def add_iig_liquidoral_checklist(request):
    report_name = "IIG Proportionality Clearance - Liquid Orals"
    if request.method == "POST":
        form = IIGForm(
            request.POST,
            user=request.user,
            report=report_name,
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("../../ratools/show_iig_liquidoral_table")

@login_required(login_url='/adminmaster/login/')
def delete_iig_checklist_liquidoral(request, id):
    report_name = "IIG Proportionality Clearance - Liquid Orals"
    checklist = IIGChecklistUser.objects.get(report=report_name, id=id)
    checklist.delete()
    return redirect("../../ratools/show_iig_liquidoral_table")

# @login_required(login_url='/adminmaster/login/')
def show_iig_injection_table(request):
    user = request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/IIG/IIGCInjectionOticOphthalmic.html", {"page_flag" :True,"show_flag":False})

    report_name = "IIG Proportionality Clearance - Injection-Otic-Ophthalmic"
    form = IIGForm(user=user, report=report_name)
    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = IIGChecklistUser.objects.filter(
            user=request.user,report=report_name
        )
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            is_completed_by_doer=True,
            report=report_name
        )
        checklists_as_checker_2 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            approved_by_checkers_level_1="True",
            report=report_name
        )
        checklists_as_checker_3 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            approved_by_checkers_level_2="True",
            report=report_name
        )
        checklists_as_checker_4 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            approved_by_checkers_level_3="True",
            report=report_name
        )
        checklists_as_checker_5 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            approved_by_checkers_level_4="True",
            report=report_name
        )
        checklists_as_checker_6 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            approved_by_checkers_level_5="True",
            report=report_name
        )
        checklists_as_checker_7 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            approved_by_checkers_level_6="True",
            report=report_name
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = IIGChecklistUser.objects.filter(report=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        return render(
            request,
            "RATools/baseShow.html",
            {
                "main_folder":"IIG Proportionality Clearance Checklist",
                "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
                "page_heading": "Injection-Otic-Ophthalmic",
                "reports": reports,
                "form": form,
                "action": "../../ratools/add_iig_injection_checklist/",
                "edit_url": "/ratools/show_iig_proportionality_clearance_report",
                "delete_url": "/ratools/delete_iig_checklist_injection",
                "Proportionality_clearance_injection_otic_ophthalmic": True,
                "modal_body_content": "Injection-Otic-Ophthalmic....",
                "modal_title": "Injection-Otic-Ophthalmic Overview",
                "view_sample":view_sample,
                "sample_url":f"/ratools/view_sample_iig_reports/{report_name}"
            },
        )
    else:
        return render(request, "RATools/IIG/IIGCInjectionOticOphthalmic.html", {"show_flag":False})


@login_required(login_url='/adminmaster/login/')
def add_iig_injection_checklist(request):
    report_name = "IIG Proportionality Clearance - Injection-Otic-Ophthalmic"
    if request.method == "POST":
        form = IIGForm(
            request.POST,
            user=request.user,
            report=report_name,
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("../../ratools/show_iig_injection_table")

@login_required(login_url='/adminmaster/login/')
def delete_iig_checklist_injection(request, id):
    report_name = "IIG Proportionality Clearance - Injection-Otic-Ophthalmic"
    checklist = IIGChecklistUser.objects.get(report=report_name, id=id)
    checklist.delete()
    return redirect("../../ratools/show_iig_injection_table")

# @login_required(login_url='/adminmaster/login/')
def show_iig_mdi_table(request):
    user = request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/IIG/IIGMDI.html", {"page_flag" :True,"show_flag":False})

    report_name = "IIG Proportionality Clearance - MDIs"
    form = IIGForm(user=user, report=report_name)
    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = IIGChecklistUser.objects.filter(
            user=request.user,report=report_name
        )
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            is_completed_by_doer=True,
            report=report_name
        )
        checklists_as_checker_2 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            approved_by_checkers_level_1="True",
            report=report_name
        )
        checklists_as_checker_3 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            approved_by_checkers_level_2="True",
            report=report_name
        )
        checklists_as_checker_4 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            approved_by_checkers_level_3="True",
            report=report_name
        )
        checklists_as_checker_5 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            approved_by_checkers_level_4="True",
            report=report_name
        )
        checklists_as_checker_6 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            approved_by_checkers_level_5="True",
            report=report_name
        )
        checklists_as_checker_7 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            approved_by_checkers_level_6="True",
            report=report_name
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = IIGChecklistUser.objects.filter(report=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        return render(
            request,
            "RATools/baseShow.html",
            {
                "main_folder":"IIG Proportionality Clearance Checklist",
                "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
                "page_heading": "MDIs",
                "reports": reports,
                "form": form,
                "action": "../../ratools/add_iig_mdi_checklist/",
                "edit_url": "/ratools/show_iig_proportionality_clearance_report",
                "delete_url": "/ratools/delete_iig_checklist_mdi",
                "Proportionality_clearance_mdis": True,
                "modal_body_content": "MDIs...",
                "modal_title": "MDIs Overview",
                "view_sample":view_sample,
                "sample_url":f"/ratools/view_sample_iig_reports/{report_name}"
            },
        )
    else:
        return render(request, "RATools/IIG/IIGMDI.html", {"show_flag":False})


@login_required(login_url='/adminmaster/login/')
def add_iig_mdi_checklist(request):
    report_name = "IIG Proportionality Clearance - MDIs"
    if request.method == "POST":
        form = IIGForm(
            request.POST,
            user=request.user,
            report=report_name,
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("../../ratools/show_iig_mdi_table")

@login_required(login_url='/adminmaster/login/')
def delete_iig_checklist_mdi(request, id):
    report_name = "IIG Proportionality Clearance - MDIs"
    checklist = IIGChecklistUser.objects.get(report=report_name, id=id)
    checklist.delete()
    return redirect("../../ratools/show_iig_mdi_table")

# @login_required(login_url='/adminmaster/login/')
def show_iig_semisolid_table(request):
    user=request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/IIG/IIGSemiSolids.html", {"page_flag" :True,"show_flag":False})

    report_name = "IIG Proportionality Clearance - Semisolids"
    form = IIGForm(user=user, report=report_name)
    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = IIGChecklistUser.objects.filter(
            user=request.user,report=report_name
        )
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            is_completed_by_doer=True,
            report=report_name
        )
        checklists_as_checker_2 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            approved_by_checkers_level_1="True",
            report=report_name
        )
        checklists_as_checker_3 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            approved_by_checkers_level_2="True",
            report=report_name
        )
        checklists_as_checker_4 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            approved_by_checkers_level_3="True",
            report=report_name
        )
        checklists_as_checker_5 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            approved_by_checkers_level_4="True",
            report=report_name
        )
        checklists_as_checker_6 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            approved_by_checkers_level_5="True",
            report=report_name
        )
        checklists_as_checker_7 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            approved_by_checkers_level_6="True",
            report=report_name
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = IIGChecklistUser.objects.filter(report=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        return render(
            request,
            "RATools/baseShow.html",
            {
                "main_folder":"IIG Proportionality Clearance Checklist",
                "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
                "page_heading": "Semisolids",
                "reports": reports,
                "form": form,
                "action": "../../ratools/add_iig_semisolid_checklist/",
                "edit_url": "/ratools/show_iig_proportionality_clearance_report",
                "delete_url": "/ratools/delete_iig_checklist_semisolid",
                "Proportionality_clearance_semisolids": True,
                "modal_body_content": "Semisolids...",
                "modal_title": "Semisolids Overview",
                "view_sample":view_sample,
                "sample_url":f"/ratools/view_sample_iig_reports/{report_name}"
            },
        )
    else:
        return render(request, "RATools/IIG/IIGSemiSolids.html", {"show_flag":False})


@login_required(login_url='/adminmaster/login/')
def add_iig_semisolid_checklist(request):
    report_name = "IIG Proportionality Clearance - Semisolids"
    if request.method == "POST":
        form = IIGForm(
            request.POST,
            user=request.user,
            report=report_name,
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("../../ratools/show_iig_semisolid_table")

@login_required(login_url='/adminmaster/login/')
def delete_iig_checklist_semisolid(request, id):
    report_name = "IIG Proportionality Clearance - Semisolids"
    checklist = IIGChecklistUser.objects.get(report=report_name, id=id)
    checklist.delete()
    return redirect("../../ratools/show_iig_semisolid_table")

# @login_required(login_url='/adminmaster/login/')
def show_iig_nasal_table(request):
    user=request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/IIG/IIGNasals.html", {"page_flag" :True,"show_flag":False})


    report_name = "IIG Proportionality Clearance - Nasals"
    form = IIGForm(user=user, report=report_name)
    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = IIGChecklistUser.objects.filter(
            user=request.user,report=report_name
        )
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            is_completed_by_doer=True,
            report=report_name
        )
        checklists_as_checker_2 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            approved_by_checkers_level_1="True",
            report=report_name
        )
        checklists_as_checker_3 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            approved_by_checkers_level_2="True",
            report=report_name
        )
        checklists_as_checker_4 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            approved_by_checkers_level_3="True",
            report=report_name
        )
        checklists_as_checker_5 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            approved_by_checkers_level_4="True",
            report=report_name
        )
        checklists_as_checker_6 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            approved_by_checkers_level_5="True",
            report=report_name
        )
        checklists_as_checker_7 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            approved_by_checkers_level_6="True",
            report=report_name
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = IIGChecklistUser.objects.filter(report=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        return render(
            request,
            "RATools/baseShow.html",
            {
                "main_folder":"IIG Proportionality Clearance Checklist",
                "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
                "page_heading": "Nasals",
                "reports": reports,
                "form": form,
                "action": "../../ratools/add_iig_nasal_checklist/",
                "edit_url": "/ratools/show_iig_proportionality_clearance_report",
                "delete_url": "/ratools/delete_iig_checklist_nasal",
                "Proportionality_clearance_nasals": True,
                "modal_body_content":"Nasals....",
                "modal_title":"Nasals Overview",
                "view_sample":view_sample,
                "sample_url":f"/ratools/view_sample_iig_reports/{report_name}"
            },
        )
    else:
        return render(request, "RATools/IIG/IIGNasals.html", {"show_flag":False})


@login_required(login_url='/adminmaster/login/')
def add_iig_nasal_checklist(request):
    report_name = "IIG Proportionality Clearance - Nasals"
    if request.method == "POST":
        form = IIGForm(
            request.POST,
            user=request.user,
            report=report_name,
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("../../ratools/show_iig_nasal_table")

@login_required(login_url='/adminmaster/login/')
def delete_iig_checklist_nasal(request, id):
    report_name = "IIG Proportionality Clearance - Nasals"
    checklist = IIGChecklistUser.objects.get(report=report_name, id=id)
    checklist.delete()
    return redirect("../../ratools/show_iig_nasal_table")

# @login_required(login_url='/adminmaster/login/')
def show_iig_tablet_table(request):
    user=request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/IIG/IIGTabletsAndCapsules.html", {"page_flag" :True,"show_flag":False})

    report_name = "IIG Proportionality Clearance - Tablets & Capsules"
    form = IIGForm(user=user, report=report_name)
    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = IIGChecklistUser.objects.filter(
            user=request.user,report=report_name
        )
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            is_completed_by_doer=True,
            report=report_name
        )
        checklists_as_checker_2 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            approved_by_checkers_level_1="True",
            report=report_name
        )
        checklists_as_checker_3 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            approved_by_checkers_level_2="True",
            report=report_name
        )
        checklists_as_checker_4 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            approved_by_checkers_level_3="True",
            report=report_name
        )
        checklists_as_checker_5 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            approved_by_checkers_level_4="True",
            report=report_name
        )
        checklists_as_checker_6 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            approved_by_checkers_level_5="True",
            report=report_name
        )
        checklists_as_checker_7 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            approved_by_checkers_level_6="True",
            report=report_name
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = IIGChecklistUser.objects.filter(report=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        return render(
            request,
            "RATools/baseShow.html",
            {
                "main_folder":"IIG Proportionality Clearance Checklist",
                "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
                "page_heading": "Tablets & Capsules",
                "reports": reports,
                "form": form,
                "action": "../../ratools/add_iig_tablet_checklist/",
                "edit_url": "/ratools/show_iig_proportionality_clearance_report",
                "delete_url": "/ratools/delete_iig_checklist_tablet",
                "Proportionality_clearance_tablets_capsules": True,
                "modal_body_content": "Tablets & Capsules....",
                "modal_title": "Tablets & Capsules Overview",
                "view_sample":view_sample,
                "sample_url":f"/ratools/view_sample_iig_reports/{report_name}"
            },
        )
    else:
        return render(request, "RATools/IIG/IIGTabletsAndCapsules.html", {"show_flag":False})


@login_required(login_url='/adminmaster/login/')
def add_iig_tablet_checklist(request):
    report_name = "IIG Proportionality Clearance - Tablets & Capsules"
    if request.method == "POST":
        form = IIGForm(
            request.POST,
            user=request.user,
            report=report_name,
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("../../ratools/show_iig_tablet_table")

@login_required(login_url='/adminmaster/login/')
def delete_iig_checklist_tablet(request, id):
    report_name = "IIG Proportionality Clearance - Tablets & Capsules"
    checklist = IIGChecklistUser.objects.get(report=report_name, id=id)
    checklist.delete()
    return redirect("../../ratools/show_iig_tablet_table")

# @login_required(login_url='/adminmaster/login/')
def show_iig_topical_table(request):
    user=request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/IIG/IIGTopicalSolutionsAndLotions.html", {"page_flag" :True,"show_flag":False})

    report_name = "IIG Proportionality Clearance - Topical Solutions & Lotions"
    form = IIGForm(user=user, report=report_name)
    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = IIGChecklistUser.objects.filter(
            user=request.user,report=report_name
        )
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            is_completed_by_doer=True,
            report=report_name
        )
        checklists_as_checker_2 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            approved_by_checkers_level_1="True",
            report=report_name
        )
        checklists_as_checker_3 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            approved_by_checkers_level_2="True",
            report=report_name
        )
        checklists_as_checker_4 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            approved_by_checkers_level_3="True",
            report=report_name
        )
        checklists_as_checker_5 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            approved_by_checkers_level_4="True",
            report=report_name
        )
        checklists_as_checker_6 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            approved_by_checkers_level_5="True",
            report=report_name
        )
        checklists_as_checker_7 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            approved_by_checkers_level_6="True",
            report=report_name
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = IIGChecklistUser.objects.filter(report=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        return render(
            request,
            "RATools/baseShow.html",
            {
                "main_folder":"IIG Proportionality Clearance Checklist",
                "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
                "page_heading": "Topical Solutions & Lotions",
                "reports": reports,
                "form": form,
                "action": "../../ratools/add_iig_topical_checklist/",
                "edit_url": "/ratools/show_iig_proportionality_clearance_report",
                "delete_url": "/ratools/delete_iig_checklist_topical",
                "Proportionality_clearance_topical_solutions": True,
                "modal_body_content": "Topical Solutions & Lotions...",
                "modal_title": "Topical Solutions & Lotions Overview",
                "view_sample":view_sample,
                "sample_url":f"/ratools/view_sample_iig_reports/{report_name}"
            },
        )
    else:
        return render(request, "RATools/IIG/IIGTopicalSolutionsAndLotions.html", {"show_flag":False})


@login_required(login_url='/adminmaster/login/')
def add_iig_topical_checklist(request):
    report_name = "IIG Proportionality Clearance - Topical Solutions & Lotions"
    if request.method == "POST":
        form = IIGForm(
            request.POST,
            user=request.user,
            report=report_name,
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("../../ratools/show_iig_topical_table")

@login_required(login_url='/adminmaster/login/')
def delete_iig_checklist_topical(request, id):
    report_name = "IIG Proportionality Clearance - Topical Solutions & Lotions"
    checklist = IIGChecklistUser.objects.get(report=report_name, id=id)
    checklist.delete()
    return redirect("../../ratools/show_iig_topical_table")

# @login_required(login_url='/adminmaster/login/')
def show_iig_transdermal_table(request):
    user=request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/IIG/IIGTransdermal.html", {"page_flag" :True,"show_flag":False})

    report_name = "IIG Proportionality Clearance - Transdermal"
    form = IIGForm(user=user, report=report_name)
    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = IIGChecklistUser.objects.filter(
            user=request.user,report=report_name
        )
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            is_completed_by_doer=True,
            report=report_name
        )
        checklists_as_checker_2 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            approved_by_checkers_level_1="True",
            report=report_name
        )
        checklists_as_checker_3 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            approved_by_checkers_level_2="True",
            report=report_name
        )
        checklists_as_checker_4 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            approved_by_checkers_level_3="True",
            report=report_name
        )
        checklists_as_checker_5 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            approved_by_checkers_level_4="True",
            report=report_name
        )
        checklists_as_checker_6 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            approved_by_checkers_level_5="True",
            report=report_name
        )
        checklists_as_checker_7 = IIGChecklistUser.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            approved_by_checkers_level_6="True",
            report=report_name
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = IIGChecklistUser.objects.filter(report=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        return render(
            request,
            "RATools/baseShow.html",
            {
                "main_folder":"IIG Proportionality Clearance Checklist",
                "table_headers": ["Sr. No.", "Product Name", "Status", "Action"],
                "page_heading": "Transdermal",
                "reports": reports,
                "form": form,
                "action": "../../ratools/add_iig_transdermal_checklist/",
                "edit_url": "/ratools/show_iig_proportionality_clearance_report",
                "delete_url": "/ratools/delete_iig_checklist_transdermal",
                "Proportionality_clearance_transdermal": True,
                "modal_body_content": "Transdermal...",
                "modal_title": "Transdermal Overview",
                "view_sample":view_sample,
                "sample_url":f"/ratools/view_sample_iig_reports/{report_name}"
            },
        )
    else:
        return render(request, "RATools/IIG/IIGTransdermal.html", {"show_flag":False})


@login_required(login_url='/adminmaster/login/')
def add_iig_transdermal_checklist(request):
    report_name = "IIG Proportionality Clearance - Transdermal"
    if request.method == "POST":
        form = IIGForm(
            request.POST,
            user=request.user,
            report=report_name,
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("../../ratools/show_iig_transdermal_table")

@login_required(login_url='/adminmaster/login/')
def delete_iig_checklist_transdermal(request, id):
    report_name = "IIG Proportionality Clearance - Transdermal"
    checklist = IIGChecklistUser.objects.get(report=report_name, id=id)
    checklist.delete()
    return redirect("../../ratools/show_iig_transdermal_table")


# Size, Shape & Score Views Function Should be below this line
@login_required(login_url='/adminmaster/login/')
def view_sample_sss(request):
    context = {
        "show_flag":True,
        "flag":False,
        "complete_flag":False,
        "show_table":True,
    }
    return render(request,"RATools/SizeShapeScore/SizeShapeScore.html",context)


@login_required(login_url='/adminmaster/login/')
def add_sss_checklist(request):
    if request.method == "POST":
        form = SizeShapeScoreForm(
            request.POST, user=request.user
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_sss")

@login_required(login_url='/adminmaster/login/')
def size_shape_score_report(request, id):
    user = request.user
    comparison = get_object_or_404(ProductComparison, id=id)
    company_name = comparison.user.company_name
    tablet = None
    capsule = None

    review_task_url = request.build_absolute_uri(
        reverse("size_shape_score_report", args=[comparison.id])
    )

    if user.role == "company_user":
        flag = False
        assignment = AssignChecker.objects.get(user=user)
        if request.method == "POST":
            completed_by_user = bool(request.POST.get("completed"))
            print("completed by user", completed_by_user)
            try:
                with transaction.atomic():
                    if comparison.product_type == "tablet":
                        # Try to get existing tablet comparison or create new one
                        tablet, created = TabletComparison.objects.get_or_create(
                            comparison=comparison
                        )

                        fields = [
                            "shape",
                            "color",
                            "scoring",
                            "score_depth",
                            "avg_thickness",
                            "avg_width",
                            "avg_length",
                            "largest_dimension",
                            "volume",
                            "surface_area",
                            "cross_sectional_area",
                            "picture",
                        ]
                        for field in fields:
                            for suffix in ["trld", "tcompany", "tdiff", "tfda"]:
                                field_name = f"{field}_{suffix}"
                                if (
                                    field_name in request.POST
                                    or field_name == f"picture_{suffix}"
                                ):
                                    value = request.POST.get(
                                        field_name
                                    ) or request.FILES.get(field_name)
                                    if (
                                        value is not None
                                    ):  # Only update if value is provided
                                        setattr(tablet, field_name, value)
                        tablet.save()

                        if completed_by_user and comparison:
                            comparison.is_completed_by_doer = True
                            comparison.show_buttons_doer = False
                            if comparison.statues is None:
                                comparison.statues = {}
                            if "Your Status" not in comparison.statues:
                                comparison.statues["Your Status"] = {}
                            if user.id not in comparison.statues["Your Status"]:
                                comparison.statues["Your Status"][user.id] = {}
                            comparison.statues["Your Status"][user.id][user.first_name] = "Submitted"

                            for i in assignment.assigned_checker_level_1.all():
                                if "Checker Level 1 Status" not in comparison.statues:
                                    comparison.statues["Checker Level 1 Status"] = {}
                                if i.id not in comparison.statues["Checker Level 1 Status"]:
                                    comparison.statues["Checker Level 1 Status"][i.id] = {}
                                comparison.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"
                        else:
                            if comparison.statues is None:
                                comparison.statues = {}
                            if "Your Status" not in comparison.statues:
                                comparison.statues["Your Status"] = {}
                            if user.id not in comparison.statues["Your Status"]:
                                comparison.statues["Your Status"] = {}
                                comparison.statues["Your Status"][user.id] = {}
                            comparison.statues["Your Status"][user.id][user.first_name] = "Pending"
                        comparison.save()

                    elif comparison.product_type == "capsule":
                        # Try to get existing capsule comparison or create new one
                        capsule, created = CapsuleComparison.objects.get_or_create(
                            comparison=comparison
                        )

                        fields = [
                            "shape",
                            "color_cap",
                            "color_body",
                            "size",
                            "tolerance_limit",
                            "dimensions",
                            "volume",
                            "bead_size",
                            "picture",
                        ]
                        for field in fields:
                            for suffix in ["crld", "company", "cdiff", "cfda"]:
                                field_name = f"{field}_{suffix}"
                                if (
                                    field_name in request.POST
                                    or field_name == f"picture_{suffix}"
                                ):
                                    value = request.POST.get(
                                        field_name
                                    ) or request.FILES.get(field_name)
                                    if (
                                        value is not None
                                    ):  # Only update if value is provided
                                        setattr(capsule, field_name, value)
                        capsule.save()

                        if completed_by_user and comparison:
                            comparison.is_completed_by_doer = True
                            comparison.show_buttons_doer = False
                            if comparison.statues is None:
                                comparison.statues = {}
                            if "Your Status" not in comparison.statues:
                                comparison.statues["Your Status"] = {}
                            if user.id not in comparison.statues["Your Status"]:
                                comparison.statues["Your Status"][user.id] = {}
                            comparison.statues["Your Status"][user.id][user.first_name] = "Submitted"

                            for i in assignment.assigned_checker_level_1.all():
                                if "Checker Level 1 Status" not in comparison.statues:
                                    comparison.statues["Checker Level 1 Status"] = {}
                                if i.id not in comparison.statues["Checker Level 1 Status"]:
                                    comparison.statues["Checker Level 1 Status"][i.id] = {}
                                comparison.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                                html_message = f"""
                                <!DOCTYPE html>
                                <html>
                                <head>
                                    <style>
                                        body {{
                                            font-family: Arial, sans-serif;
                                        }}
                                    </style>
                                </head>
                                <body>
                                    <p>Dear {i.first_name},</p>
                                    <p>Greetings !!!</p>
                                    <p>The task <strong>{comparison.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                                    <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                                    <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                                    <p>Best regards,</p>
                                    <p>{comparison.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                                </body>
                                </html>
                                """

                                plain_message = f"""
                                    Subject: Regulatory Checklist Task Submission Notification: {comparison.product_name}

                                    Dear {i.first_name},

                                    Greetings !!!

                                    The task {comparison.product_name} has been successfully submitted and is now ready for your review & inputs.

                                    You can access it here: {review_task_url}

                                    Thank you for your prompt attention to this. Please let me know if any clarification is required.

                                    Best regards,
                                    {comparison.user.first_name} via iCretegy's Regulatory Checklist Software
                                """

                                # Send personalized email to each checker
                                send_mail(
                                    subject=f"Regulatory Checklist Task Submission Notification: {comparison.product_name}",
                                    message=plain_message,
                                    from_email=comparison.user.email,
                                    recipient_list=[i.email],
                                    html_message=html_message,
                                )
                        else:
                            if comparison.statues is None:
                                comparison.statues = {}
                            if "Your Status" not in comparison.statues:
                                comparison.statues["Your Status"] = {}
                            if user.id not in comparison.statues["Your Status"]:
                                comparison.statues["Your Status"] = {}
                                comparison.statues["Your Status"][user.id] = {}
                            comparison.statues["Your Status"][user.id][user.first_name] = "Pending"
                        comparison.save()

                    else:
                        return redirect("ratools/show_sss")

            except Exception as e:
                print("error", str(e))
            return redirect("/ratools/show_sss")
        else:  # GET request
            if comparison.product_type == "tablet":
                tablet = TabletComparison.objects.filter(comparison=comparison).first()
                if not tablet:
                    tablet = TabletComparison(comparison=comparison)
            else:
                capsule = CapsuleComparison.objects.filter(comparison=comparison).first()
                if not capsule:
                    capsule = CapsuleComparison(comparison=comparison)

    elif user.role == "company_checker":
        assigned_user = comparison.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        # if request.method == "POST":
        current_level =  get_checker_level(user.id, assignment.checkers_json)
        last_level = assignment.level_report_24
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(comparison, user, assignment, action, current_level, last_level, review_task_url)
                comparison.save()
            return redirect("/ratools/show_sss")
        else:
            if comparison.product_type == "tablet":
                tablet = TabletComparison.objects.filter(comparison=comparison).first()
                if not tablet:
                    tablet = TabletComparison(comparison=comparison)
            else:
                capsule = CapsuleComparison.objects.filter(comparison=comparison).first()
                if not capsule:
                    capsule = CapsuleComparison(comparison=comparison)

        if comparison.statues[f"Checker Level {current_level} Status"][str(user.id)][user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': only `flag` is unbound (tablet/capsule are
        # pre-initialised to None above). Read-only, no approve/reject.
        flag = False

    context = {
        "comparison": comparison,
        "company_name": company_name,
        "tablet": tablet,
        "capsule": capsule,
        "flag":flag,
        "show_flag":True,
        "complete_flag":comparison.show_buttons_doer,
    }
    return render(request, "RATools/SizeShapeScore/SizeShapeScore.html", context)

# @login_required(login_url='/adminmaster/login/')
def show_sss(request):
    user = request.user
    report_name = "Size Shape and Score Comparison"
    if not request.user.is_authenticated:
        return render(request, "RATools/SizeShapeScore/SizeShapeScore.html", {"page_flag" :True,"show_flag":False})

    form = SizeShapeScoreForm(user=request.user)
    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        record = ProductComparison.objects.filter(user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = ProductComparison.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = ProductComparison.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = ProductComparison.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = ProductComparison.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = ProductComparison.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = ProductComparison.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = ProductComparison.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            approved_by_checkers_level_6="True",
        )

        record = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        record = ProductComparison.objects.all()
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        return render(
            request,
            "RATools/baseShow.html",
            {
                # "main_folder":"Size, Shape and Score",
                "table_headers": ["Sr. No.", "Product Name", "Status", "Actions"],
                "page_heading": "Size, Shape and Score Comparison",
                "reports": record,
                "edit_url": "/ratools/size_shape_score_report",
                "delete_url": "/ratools/delete_sss",
                "action": "/ratools/add_sss_checklist/",
                "form": form,
                "modal_body_content": "Size, Shape and Score Comparison..",
                "modal_title": "Size, Shape and Score Comparison Overview",
                "view_sample":view_sample,
                "sample_url":"/ratools/view_sample_sss"
            },
        )
    else:
        return render(request, "RATools/SizeShapeScore/SizeShapeScore.html", {"show_flag":False})

@login_required(login_url='/adminmaster/login/')
def delete_sss(request, id):
    comparison = get_object_or_404(ProductComparison, id=id)

    try:
        if comparison.product_type == "tablet":
            tablet = TabletComparison.objects.filter(comparison=comparison).first()
            if tablet:
                tablet.delete()

        elif comparison.product_type == "capsule":
            capsule = CapsuleComparison.objects.filter(comparison=comparison).first()
            if capsule:
                capsule.delete()

        comparison.delete()

    except Exception as e:
        print(str(e))

    return redirect("../../ratools/show_sss")


# API Facility Views Function Should be below this line
# @login_required(login_url='/adminmaster/login/')
def show_anda_faciltiy(request):
    user = request.user
    if not user.is_authenticated:
        return render(request, "RATools/ANDAFacilityTemplate.html",{"page_flag" :True,"show_flag":False})

    report_name = "ANDA Facility Template"
    if report_name in AssignChecker.objects.get(user=user).assigned_report:
        show_flag = True
    else:
        show_flag = False
    return render(request, "RATools/ANDAFacilityTemplate.html",{"show_flag":show_flag})

# @login_required(login_url='/adminmaster/login/')
def show_api_faciltiy(request):
    user = request.user
    if not user.is_authenticated:
        return render(request, "RATools/TemplateAPIFacility.html",{"page_flag" :True,"show_flag":False})
    report_name = "Template for API Facility details"
    if report_name in AssignChecker.objects.get(user=user).assigned_report:
        show_flag = True
    else:
        show_flag = False
    return render(request, "RATools/TemplateAPIFacility.html",{"show_flag":show_flag})

@login_required(login_url='/adminmaster/login/')
def download_document(request, document_name):
    # Define the file paths for your static documents
    file_mapping = {
        "ANDAFacilityTemplate": os.path.join(
            settings.STATICFILES_DIRS[0], "documents/ANDAFacilityTemplate.docx"
        ),
        "TemplateforAPIFacilitydetails": os.path.join(
            settings.STATICFILES_DIRS[0], "documents/TemplateforAPIFacilitydetails.docx"
        ),
        "Controlled Correspondences Templates":os.path.join(
            settings.STATICFILES_DIRS[0], "documents/ControlledCorrespondencesTempateforQ1Q2.doc"
        ),
    }
    file_path = file_mapping.get(document_name)
    file_extension = os.path.splitext(file_path)[1]
    if not file_path or not os.path.exists(file_path):
        raise Http404("File not found")

    return FileResponse(
        open(file_path, "rb"), as_attachment=True, filename=f"{document_name}.{file_extension}"
    )


# Validation Views Function Should be below this line
@login_required(login_url='/adminmaster/login/')
def view_sample_validation_report(request,report_name):
    questions = ValidationReportQuestions.objects.filter(report_name=report_name)

    if report_name == "API-VALIDATION":
        html = "RATools/Validation/ApiValidation.html"
        heading = "API-VALIDATION"
    elif report_name == "API-VERIFICATION":
        html = "RATools/Validation/APIVerification.html"
        heading = "API Verification"
    elif report_name == "DRUG PRODUCT VALIDATION":
        html="RATools/Validation/DrugProductValidation.html"
        heading="DRUG PRODUCT VALIDATION"


    organized_data = {}
    grouped_data = {}

    for question in questions:
        category = question.category
        sub_category = question.sub_category
        sub_sub_category = question.sub_sub_category

        if category not in organized_data:
            organized_data[category] = {}
            grouped_data[category] = []

        if sub_category not in organized_data[category]:
            organized_data[category][sub_category] = {}
            grouped_data[category].append(sub_category)

        if sub_sub_category:
            if sub_sub_category not in organized_data[category][sub_category]:
                organized_data[category][sub_category][sub_sub_category] = []

            # Add a checklist_answers attribute with null values
            question.checklist_answers = type(
                "Answer",
                (),
                {
                    "answer": None,
                    "comment": None,
                },
            )()

            organized_data[category][sub_category][sub_sub_category].append(question)
        else:
            if None not in organized_data[category][sub_category]:
                organized_data[category][sub_category][None] = []

            # Add a checklist_answers attribute with null values
            question.checklist_answers = type(
                "Answer",
                (),
                {
                    "answer": None,
                    "comment": None,
                },
            )()

            organized_data[category][sub_category][None].append(question)

    # Prepare context
    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": heading,
        "report_name": report_name,
        "complete_flag": False,
        "show_flag": True,
        "flag": False,
    }

    return render(request, html, context)

# @login_required(login_url='/adminmaster/login/')
def show_api_validation_table(request):
    user = request.user
    if not user.is_authenticated:
        return render(request, "RATools/Validation/ApiValidation.html",{"page_flag" :True,"show_flag":False, "report_name":"API-VALIDATION"}

        )
    assigns = AssignChecker.objects.get(user=user)
    report_name = "API-VALIDATION"

    if user.role == "company_user":
        view_sample = False
        reports = ValidationUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = ValidationUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = ValidationForm(
            user=user,
            report_name=ValidationReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )

        context = {
            "main_folder":"Validation Checklist",
            "reports": reports,
            "table_headers": ["Sr. No.", "API Name", "Status", "Action"],
            "page_heading": "API-Validation",
            "form": form,
            "action": "../../ratools/validation/add_api_validation_checklist/",
            "edit_url": "/ratools/validation/show_api_validation_report",
            "delete_url": "/ratools/validation/delete_api_validation_checklist",
            "modal_body_content": "API-Validation...",
            "modal_title": "API-Validation Overview",
            "view_sample":view_sample,
            "sample_url":f"/ratools/view_sample_validation_report/{report_name}"
        }
        return render(request, "RATools/baseShow.html", context)
    else:
        return render(request, "RATools/Validation/ApiValidation.html",{"show_flag":False, "report_name":"API-VALIDATION"})

@login_required(login_url='/adminmaster/login/')
def show_api_validation_report(request, id):
    report_type = "API-VALIDATION"
    current_user = request.user
    user_report = ValidationUserReports.objects.get(
        report_name__report_name=report_type, id=id
    )

    review_task_url = request.build_absolute_uri(
        reverse("show_api_validation_report", args=[user_report.id])
    )

    # Handle form submission
    if current_user.role == "company_user":
        flag = False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = ValidationReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)
                comment = request.POST.get(f"comment_{question.id}", "")

                if answer_value:
                    # Update or create answer
                    answer, created = ValidationUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name=user_report,
                        report_question=question,
                        defaults={"answer": answer_value, "comment": comment},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send personalized email to each checker
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            return redirect("/ratools/show_api_validation_table")

    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_25
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level, review_task_url)
                user_report.save()
            return redirect("/ratools/show_api_validation_table")

        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    # Get all questions
    questions = ValidationReportQuestions.objects.filter(
        report_name=report_type
    )

    # Get existing user answers
    user_answers = {}
    if user_report:
        answers = ValidationUserAnswers.objects.filter(
            report_name=user_report
        )
        for answer in answers:
            user_answers[answer.report_question_id] = {
                "answer": answer.answer,
                "comment": answer.comment,
            }

    # Organize data
    organized_data = {}
    grouped_data = {}

    for question in questions:
        category = question.category
        sub_category = question.sub_category
        sub_sub_category = question.sub_sub_category

        if category not in organized_data:
            organized_data[category] = {}
            grouped_data[question.category] = []

        if sub_category not in organized_data[category]:
            organized_data[category][sub_category] = {}
            grouped_data[question.category].append(question.sub_category)

        if sub_sub_category:
            if sub_sub_category not in organized_data[category][sub_category]:
                organized_data[category][sub_category][sub_sub_category] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][sub_sub_category].append(question)
        else:
            if None not in organized_data[category][sub_category]:
                organized_data[category][sub_category][None] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][None].append(question)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "API-VALIDATION",
        "report_name": report_type,
        "user_report": user_report,
        "complete_flag": user_report.show_buttons_doer,
        "show_flag":True,
        "flag":flag,
    }

    return render(request, "RATools/Validation/ApiValidation.html", context)

@login_required(login_url='/adminmaster/login/')
def add_api_validation_checklist(request):
    report_name = "API-VALIDATION"
    if request.method == "POST":
        form = ValidationForm(
            request.POST,
            user=request.user,
            report_name=ValidationReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
    return redirect("/ratools/show_api_validation_table")

@login_required(login_url='/adminmaster/login/')
def delete_api_validation_checklist(request, id):
    try:
        report = ValidationUserReports.objects.get(id=id)
        ValidationUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except ValidationUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")
    return redirect("/ratools/show_api_validation_table")

# @login_required(login_url='/adminmaster/login/')
def show_api_verification_table(request):
    user = request.user
    if not user.is_authenticated:
        return render(request, "RATools/Validation/APIVerification.html",{"page_flag" :True,"show_flag":False,"report_name":"API-VERIFICATION"})

    report_name = "API-VERIFICATION"
    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = ValidationUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = ValidationUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = ValidationForm(
            user=user,
            report_name=ValidationReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )

        context = {
            "main_folder":"Validation Checklist",
            "reports": reports,
            "table_headers": ["Sr. No.", "API Name", "Status", "Action"],
            "page_heading": "API-Verification",
            "form": form,
            "action": "../../ratools/validation/add_api_verification_checklist/",
            "edit_url": "/ratools/validation/show_api_verification_report",
            "delete_url": "/ratools/validation/delete_api_verification_checklist",
            "modal_body_content": "API Verification...",
            "modal_title": "API Verification Overview",
            "view_sample":view_sample,
            "sample_url":f"/ratools/view_sample_validation_report/{report_name}"
        }
        return render(request, "RATools/baseShow.html", context)
    else:
        return render(request, "RATools/Validation/APIVerification.html",{"show_flag":False,"report_name":"API-VERIFICATION"})

@login_required(login_url='/adminmaster/login/')
def show_api_verification_report(request, id):
    report_type = "API-VERIFICATION"
    current_user = request.user
    user_report = ValidationUserReports.objects.get(
        report_name__report_name=report_type, id=id
    )
    review_task_url = request.build_absolute_uri(
        reverse("show_api_verification_report", args=[user_report.id])
    )

    # Handle form submission
    if current_user.role == "company_user":
        flag = False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            # Check if the form is being completed
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = ValidationReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)
                comment = request.POST.get(f"comment_{question.id}", "")

                if answer_value:
                    # Update or create answer
                    answer, created = ValidationUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name=user_report,
                        report_question=question,
                        defaults={"answer": answer_value, "comment": comment},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send personalized email to each checker
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            return redirect("/ratools/show_api_verification_table")
    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_26
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level, review_task_url)
                user_report.save()
            return redirect("/ratools/show_api_verification_table")
        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    # Get all questions
    questions = ValidationReportQuestions.objects.filter(
        report_name=report_type
    )

    # Get existing user answers
    user_answers = {}
    if user_report:
        answers = ValidationUserAnswers.objects.filter(
            report_name=user_report
        )
        for answer in answers:
            user_answers[answer.report_question_id] = {
                "answer": answer.answer,
                "comment": answer.comment,
            }

    # Organize data
    organized_data = {}
    grouped_data = {}

    for question in questions:
        category = question.category
        sub_category = question.sub_category
        sub_sub_category = question.sub_sub_category

        if category not in organized_data:
            organized_data[category] = {}
            grouped_data[question.category] = []

        if sub_category not in organized_data[category]:
            organized_data[category][sub_category] = {}
            grouped_data[question.category].append(question.sub_category)

        if sub_sub_category:
            if sub_sub_category not in organized_data[category][sub_category]:
                organized_data[category][sub_category][sub_sub_category] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][sub_sub_category].append(question)
        else:
            if None not in organized_data[category][sub_category]:
                organized_data[category][sub_category][None] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][None].append(question)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "API Verification",
        "report_name": report_type,
        "user_report": user_report,
        "complete_flag": user_report.show_buttons_doer,
        "show_flag":True,
        "flag":flag,
    }

    return render(request, "RATools/Validation/APIVerification.html", context)

@login_required(login_url='/adminmaster/login/')
def add_api_verification_checklist(request):
    report_name = "API-VERIFICATION"
    if request.method == "POST":
        form = ValidationForm(
            request.POST,
            user=request.user,
            report_name=ValidationReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
    return redirect("/ratools/show_api_verification_table")

@login_required(login_url='/adminmaster/login/')
def delete_api_verification_checklist(request, id):
    try:
        report = ValidationUserReports.objects.get(id=id)
        ValidationUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except ValidationUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")
    return redirect("/ratools/show_api_verification_table")


# DRUG PRODUCT VALIDATION
# @login_required(login_url='/adminmaster/login/')
def show_drug_product_validation_table(request):
    report_name = "DRUG PRODUCT VALIDATION"
    user = request.user
    if not user.is_authenticated:
        return render(request, "RATools/Validation/DrugProductValidation.html",{"page_flag" :True,"show_flag":False,"report_name":"DRUG PRODUCT VALIDATION"})

    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = ValidationUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = ValidationUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = ValidationUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = ValidationForm(
            user=user,
            report_name=ValidationReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        context = {
            "main_folder":"Validation Checklist",
            "reports": reports,
            "table_headers": ["Sr. No.", "API Name", "Status", "Action"],
            "page_heading": "Drug Product-Validation",
            "form": form,
            "action": "../../ratools/validation/add_drug_product_validation_checklist/",
            "edit_url": "/ratools/validation/show_drug_product_validation_report",
            "delete_url": "/ratools/validation/delete_drug_product_validation_checklist",
            "modal_body_content": "Drug Product Validation...",
            "modal_title": "Drug Product Validation Overview",
            "view_sample":view_sample,
            "sample_url":f"/ratools/view_sample_validation_report/{report_name}"
        }
        return render(request, "RATools/baseShow.html", context)
    else:
        return render(request, "RATools/Validation/DrugProductValidation.html",{"show_flag":False,"report_name":"DRUG PRODUCT VALIDATION"})

@login_required(login_url='/adminmaster/login/')
def show_drug_product_validation_report(request, id):
    report_type = "DRUG PRODUCT VALIDATION"
    current_user = request.user
    user_report = ValidationUserReports.objects.get(
        report_name__report_name=report_type, id=id
    )

    review_task_url = request.build_absolute_uri(
        reverse("show_drug_product_validation_report", args=[user_report.id])
    )

    if current_user.role == "company_user":
        flag=False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            # Check if the form is being completed
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = ValidationReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)
                comment = request.POST.get(f"comment_{question.id}", "")

                if answer_value:
                    # Update or create answer
                    answer, created = ValidationUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name=user_report,
                        report_question=question,
                        defaults={"answer": answer_value, "comment": comment},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send personalized email to each checker
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            return redirect("/ratools/show_drug_product_validation_table")
    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_27
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level, review_task_url)
                user_report.save()
            return redirect("/ratools/show_drug_product_validation_table")

        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    # Get all questions
    questions = ValidationReportQuestions.objects.filter(
        report_name=report_type
    )

    # Get existing user answers
    user_answers = {}
    if user_report:
        answers = ValidationUserAnswers.objects.filter(
            report_name=user_report
        )
        for answer in answers:
            user_answers[answer.report_question_id] = {
                "answer": answer.answer,
                "comment": answer.comment,
            }

    # Organize data
    organized_data = {}
    grouped_data = {}

    for question in questions:
        category = question.category
        sub_category = question.sub_category
        sub_sub_category = question.sub_sub_category

        if category not in organized_data:
            organized_data[category] = {}
            grouped_data[question.category] = []

        if sub_category not in organized_data[category]:
            organized_data[category][sub_category] = {}
            grouped_data[question.category].append(question.sub_category)

        if sub_sub_category:
            if sub_sub_category not in organized_data[category][sub_category]:
                organized_data[category][sub_category][sub_sub_category] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][sub_sub_category].append(question)
        else:
            if None not in organized_data[category][sub_category]:
                organized_data[category][sub_category][None] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][None].append(question)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "DRUG PRODUCT VALIDATION",
        "report_name": report_type,
        "user_report": user_report,
        "complete_flag": user_report.show_buttons_doer,
        "show_flag":True,
        "flag":flag,
    }

    return render(request, "RATools/Validation/DrugProductValidation.html", context)

@login_required(login_url='/adminmaster/login/')
def add_drug_product_validation_checklist(request):
    report_name = "DRUG PRODUCT VALIDATION"
    if request.method == "POST":
        form = ValidationForm(
            request.POST,
            user=request.user,
            report_name=ValidationReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
    return redirect("/ratools/show_drug_product_validation_table")

@login_required(login_url='/adminmaster/login/')
def delete_drug_product_validation_checklist(request, id):
    try:
        report = ValidationUserReports.objects.get(id=id)
        ValidationUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except ValidationUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")
    return redirect("/ratools/show_drug_product_validation_table")


# VP Views Function Should be below this line
@login_required(login_url='/adminmaster/login/')
def view_sample_vp_report(request,report_name):
    if report_name == "VP MDI and DPI Report":
        heading="VP MDI and DPI Checklist"
        html = "RATools/VP/MDIAndDPI.html"
    elif report_name == "VP Nasal and Inhalation Report":
        heading="VP Nasal and Inhalation Checklist"
        html = "RATools/VP/VPNasalInhalation.html"
    elif report_name == "VP Ophthalmic Report":
        heading="VP Ophthalmic Checklist"
        html = "RATools/VP/VPOphthalmic.html"
    elif report_name == "VP - Oral Liquids Report":
        heading="VP - Oral Liquids Checklist"
        html = "RATools/VP/VPLiquidOrals.html"
    elif report_name == "VP - Parenteral Report":
        heading="VP - Parenteral Checklist"
        html = "RATools/VP/VPParenteral.html"
    elif report_name == "VP - Solid Oral Report":
        heading="VP - Solid Oral Checklist"
        html = "RATools/VP/VPSolidOral.html"
    elif report_name == "VP - Topical Report":
        heading="VP - Topical Checklist"
        html = "RATools/VP/VPTopical.html"
    elif report_name == "VP - Transdermal Report":
        heading="VP - Transdermal Checklist"
        html = "RATools/VP/VPTransdermal.html"

    elif report_name == "VP Microsphere Report":
        heading = "VP Microsphere Checklist"
        html = "RATools/VP/Microsphere.html"
    elif report_name == "VP Liposome Report":
        heading = "VP Liposome Checklist"
        html = "RATools/VP/Liposome.html"

    questions = VPReportQuestions.objects.filter(report_name=report_name)
    organized_data = {}
    grouped_data = {}

    for question in questions:
        category = question.category
        sub_category = question.sub_category
        sub_sub_category = question.sub_sub_category

        if category not in organized_data:
            organized_data[category] = {}
            grouped_data[question.category] = []

        if sub_category not in organized_data[category]:
            organized_data[category][sub_category] = {}
            grouped_data[question.category].append(question.sub_category)

        if sub_sub_category:
            if sub_sub_category not in organized_data[category][sub_category]:
                organized_data[category][sub_category][sub_sub_category] = []


            question.checklist_answers = type(
                "Answer",
                (),
                {
                    "answer": None,
                    "comment": None,
                },
            )()

            organized_data[category][sub_category][sub_sub_category].append(question)
        else:
            if None not in organized_data[category][sub_category]:
                organized_data[category][sub_category][None] = []


            question.checklist_answers = type(
                "Answer",
                (),
                {
                    "answer": None,
                    "comment": None,
                },
            )()

            organized_data[category][sub_category][None].append(question)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": heading,
        "report_name": report_name,
        "complete_flag": False,
        "show_flag":True,
        "flag":False,
    }
    return render(request, html, context)



# @login_required(login_url='/adminmaster/login/')
def show_vp_microsphere_table(request):
    report_name = "VP Microsphere Report"
    user = request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/VP/Microsphere.html", {"page_flag" :True,"show_flag": False, "report_name": report_name})

    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = VPUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = VPUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = VPForm(
            user=user,
            report_name=VPReportQuestions.objects.filter(report_name=report_name).first(),
        )

        return render(
            request,
            "RATools/baseShow.html",
            {
                "main_folder": "Upper Management Review Checklist",
                "table_headers": ["Sr. No.", "Product Name","Category", "Status", "Action"],
                "page_heading": "Microsphere",
                "reports": reports,
                "form": form,
                "action": "../../ratools/vp/add_vp_microsphere_checklist/",
                "edit_url": "/ratools/vp/show_vp_microsphere_report",
                "delete_url": "/ratools/vp/delete_vp_microsphere_checklist",
                "modal_body_content": "Microsphere...",
                "modal_title": "Microsphere Overview",
                "view_sample": view_sample,
                "sample_url": f"/ratools/view_sample_vp_report/{report_name}"
            },
        )
    else:
        return render(request, "RATools/VP/Microsphere.html", {"show_flag": False, "report_name": report_name})

@login_required(login_url='/adminmaster/login/')
def show_vp_microsphere_report(request, id):
    report_type = "VP Microsphere Report"
    current_user = request.user
    user_report = VPUserReports.objects.get(
        report_name__report_name=report_type, id=id
    )

    review_task_url = request.build_absolute_uri(
        reverse("show_vp_microsphere_report", args=[user_report.id])
    )

    if current_user.role == "company_user":
        flag = False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            is_completing = bool(request.POST.get("completed"))
            questions = VPReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)
                comment = request.POST.get(f"comment_{question.id}", "")

                if answer_value:
                    answer, created = VPUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name=user_report,
                        report_question=question,
                        defaults={"answer": answer_value, "comment": comment},
                    )

            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    # Email notification setup
                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send email notification
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )

            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            return redirect("/ratools/show_vp_microsphere_table")

    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_37
        current_level = get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level,review_task_url)
                user_report.save()
            return redirect("/ratools/show_vp_microsphere_table")
        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    questions = VPReportQuestions.objects.filter(report_name=report_type)
    user_answers = {}
    if user_report:
        answers = VPUserAnswers.objects.filter(
            report_name=user_report
        )
        for answer in answers:
            user_answers[answer.report_question_id] = {
                "answer": answer.answer,
                "comment": answer.comment,
            }

    organized_data = {}
    grouped_data = {}

    for question in questions:
        category = question.category
        sub_category = question.sub_category
        sub_sub_category = question.sub_sub_category

        if category not in organized_data:
            organized_data[category] = {}
            grouped_data[question.category] = []

        if sub_category not in organized_data[category]:
            organized_data[category][sub_category] = {}
            grouped_data[question.category].append(question.sub_category)

        if sub_sub_category:
            if sub_sub_category not in organized_data[category][sub_category]:
                organized_data[category][sub_category][sub_sub_category] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][sub_sub_category].append(question)
        else:
            if None not in organized_data[category][sub_category]:
                organized_data[category][sub_category][None] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][None].append(question)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "VP Microsphere Checklist",
        "report_name": report_type,
        "user_report": user_report,
        "complete_flag": user_report.show_buttons_doer,
        "show_flag": True,
        "flag": flag,
    }

    return render(request, "RATools/VP/Microsphere.html", context)

@login_required(login_url='/adminmaster/login/')
def add_vp_microsphere_checklist(request):
    report_name = "VP Microsphere Report"
    if request.method == "POST":
        form = VPForm(
            request.POST,
            user=request.user,
            report_name=VPReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_vp_microsphere_table")

@login_required(login_url='/adminmaster/login/')
def delete_vp_microsphere_checklist(request, id):
    try:
        report = VPUserReports.objects.get(id=id)
        VPUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except VPUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")

    return redirect("/ratools/show_vp_microsphere_table")



# @login_required(login_url='/adminmaster/login/')
def show_vp_liposome_table(request):
    report_name = "VP Liposome Report"
    user = request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/VP/Liposome.html", {"page_flag" :True,"show_flag": False, "report_name": report_name})

    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = VPUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = VPUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = VPForm(
            user=user,
            report_name=VPReportQuestions.objects.filter(report_name=report_name).first(),
        )

        return render(
            request,
            "RATools/baseShow.html",
            {
                "main_folder": "Upper Management Review Checklist",
                "table_headers": ["Sr. No.", "Product Name","Category", "Status", "Action"],
                "page_heading": "Liposome",
                "reports": reports,
                "form": form,
                "action": "../../ratools/vp/add_vp_liposome_checklist/",
                "edit_url": "/ratools/vp/show_vp_liposome_report",
                "delete_url": "/ratools/vp/delete_vp_liposome_checklist",
                "modal_body_content": "Liposome...",
                "modal_title": "Liposome Overview",
                "view_sample": view_sample,
                "sample_url": f"/ratools/view_sample_vp_report/{report_name}"
            },
        )
    else:
        return render(request, "RATools/VP/Liposome.html", {"show_flag": False, "report_name": report_name})

@login_required(login_url='/adminmaster/login/')
def show_vp_liposome_report(request, id):
    report_type = "VP Liposome Report"
    current_user = request.user
    user_report = VPUserReports.objects.get(
        report_name__report_name=report_type, id=id
    )

    review_task_url = request.build_absolute_uri(
        reverse("show_vp_liposome_report", args=[user_report.id])
    )

    if current_user.role == "company_user":
        flag = False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            is_completing = bool(request.POST.get("completed"))
            questions = VPReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)
                comment = request.POST.get(f"comment_{question.id}", "")

                if answer_value:
                    answer, created = VPUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name=user_report,
                        report_question=question,
                        defaults={"answer": answer_value, "comment": comment},
                    )

            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    # Email notification setup
                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send email notification
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )

            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            return redirect("/ratools/show_vp_liposome_table")

    # Rest of the view remains unchanged
    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_36
        current_level = get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level,review_task_url)
                user_report.save()
            return redirect("/ratools/show_vp_liposome_table")
        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    questions = VPReportQuestions.objects.filter(report_name=report_type)
    user_answers = {}
    if user_report:
        answers = VPUserAnswers.objects.filter(
            report_name=user_report
        )
        for answer in answers:
            user_answers[answer.report_question_id] = {
                "answer": answer.answer,
                "comment": answer.comment,
            }

    organized_data = {}
    grouped_data = {}

    for question in questions:
        category = question.category
        sub_category = question.sub_category
        sub_sub_category = question.sub_sub_category

        if category not in organized_data:
            organized_data[category] = {}
            grouped_data[question.category] = []

        if sub_category not in organized_data[category]:
            organized_data[category][sub_category] = {}
            grouped_data[question.category].append(question.sub_category)

        if sub_sub_category:
            if sub_sub_category not in organized_data[category][sub_category]:
                organized_data[category][sub_category][sub_sub_category] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][sub_sub_category].append(question)
        else:
            if None not in organized_data[category][sub_category]:
                organized_data[category][sub_category][None] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][None].append(question)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "VP Liposome Checklist",
        "report_name": report_type,
        "user_report": user_report,
        "complete_flag": user_report.show_buttons_doer,
        "show_flag": True,
        "flag": flag,
    }

    return render(request, "RATools/VP/Liposome.html", context)
@login_required(login_url='/adminmaster/login/')
def add_vp_liposome_checklist(request):
    report_name = "VP Liposome Report"
    if request.method == "POST":
        form = VPForm(
            request.POST,
            user=request.user,
            report_name=VPReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_vp_liposome_table")

@login_required(login_url='/adminmaster/login/')
def delete_vp_liposome_checklist(request, id):
    try:
        report = VPUserReports.objects.get(id=id)
        VPUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except VPUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")

    return redirect("/ratools/show_vp_liposome_table")


# @login_required(login_url='/adminmaster/login/')
def show_vp_mdi_and_dpi_table(request):
    report_name = "VP MDI and DPI Report"
    user = request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/VP/MDIAndDPI.html",{"page_flag" :True,"show_flag":False, "report_name":report_name})

    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = VPUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = VPUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = VPForm(
            user=user,
            report_name=VPReportQuestions.objects.filter(report_name=report_name).first(),
        )

        return render(
            request,
            "RATools/baseShow.html",
            {
                "main_folder":"Upper Management Review Checklist",
                "table_headers": ["Sr. No.", "Product Name","Category", "Status", "Action"],
                "page_heading": "MDI-DPI",
                "reports": reports,
                "form": form,
                "action": "../../ratools/vp/add_vp_mdi_and_dpi_checklist/",
                "edit_url": "/ratools/vp/show_vp_mdi_and_dpi_report",
                "delete_url": "/ratools/vp/delete_vp_mdi_and_dpi_checklist",
                "modal_body_content": "MDI-DPI...",
                "modal_title": "MDI-DPI Overview",
                "view_sample":view_sample,
                "sample_url":f"/ratools/view_sample_vp_report/{report_name}"
            },
        )
    else:
        return render(request, "RATools/VP/MDIAndDPI.html",{"show_flag":False, "report_name":report_name})

@login_required(login_url='/adminmaster/login/')
def show_vp_mdi_and_dpi_report(request, id):
    report_type = "VP MDI and DPI Report"
    current_user = request.user
    user_report = VPUserReports.objects.get(
        report_name__report_name=report_type, id=id
    )

    review_task_url = request.build_absolute_uri(
        reverse("show_vp_mdi_and_dpi_report", args=[user_report.id])
    )

    # Handle form submission
    if current_user.role == "company_user":
        flag=False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            # Check if the form is being completed
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = VPReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)
                comment = request.POST.get(f"comment_{question.id}", "")

                if answer_value:
                    # Update or create answer
                    answer, created = VPUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name=user_report,
                        report_question=question,
                        defaults={"answer": answer_value, "comment": comment},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    # Email notification setup
                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send email notification
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )

            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            return redirect("/ratools/show_vp_mdi_and_dpi_table")

    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_28
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level,review_task_url)
                user_report.save()
            return redirect("/ratools/show_vp_mdi_and_dpi_table")
        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    # Rest of the view remains unchanged
    questions = VPReportQuestions.objects.filter(report_name=report_type)
    user_answers = {}
    if user_report:
        answers = VPUserAnswers.objects.filter(
            report_name=user_report
        )
        for answer in answers:
            user_answers[answer.report_question_id] = {
                "answer": answer.answer,
                "comment": answer.comment,
            }

    organized_data = {}
    grouped_data = {}

    for question in questions:
        category = question.category
        sub_category = question.sub_category
        sub_sub_category = question.sub_sub_category

        if category not in organized_data:
            organized_data[category] = {}
            grouped_data[question.category] = []

        if sub_category not in organized_data[category]:
            organized_data[category][sub_category] = {}
            grouped_data[question.category].append(question.sub_category)

        if sub_sub_category:
            if sub_sub_category not in organized_data[category][sub_category]:
                organized_data[category][sub_category][sub_sub_category] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][sub_sub_category].append(question)
        else:
            if None not in organized_data[category][sub_category]:
                organized_data[category][sub_category][None] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][None].append(question)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "VP MDI and DPI Checklist",
        "report_name": report_type,
        "user_report": user_report,
        "complete_flag": user_report.show_buttons_doer,
        "show_flag":True,
        "flag":flag,
    }

    return render(request, "RATools/VP/MDIAndDPI.html", context)

@login_required(login_url='/adminmaster/login/')
def add_vp_mdi_and_dpi_checklist(request):
    report_name = "VP MDI and DPI Report"
    if request.method == "POST":
        form = VPForm(
            request.POST,
            user=request.user,
            report_name=VPReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_vp_mdi_and_dpi_table")

@login_required(login_url='/adminmaster/login/')
def delete_vp_mdi_and_dpi_checklist(request, id):
    try:
        report = VPUserReports.objects.get(id=id)
        VPUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except VPUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")

    return redirect("/ratools/show_vp_mdi_and_dpi_table")


# @login_required(login_url='/adminmaster/login/')
def show_vp_nasal_inhalation_table(request):
    report_name = "VP Nasal and Inhalation Report"
    user = request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/VP/VPNasalInhalation.html",{"page_flag" :True,"show_flag":False,"report_name":report_name})

    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = VPUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = VPUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":

        form = VPForm(
            user=request.user,
            report_name=VPReportQuestions.objects.filter(report_name=report_name).first(),
        )

        context = {
            "main_folder":"Upper Management Review Checklist",
            "table_headers": ["Sr. No.", "Product Name","Category", "Status", "Action"],
            "page_heading": "Nasal-Inhalation",
            "reports": reports,
            "form": form,
            "action": "../../ratools/vp/add_vp_nasal_inhalation_checklist/",
            "edit_url": "/ratools/vp/show_vp_nasal_inhalation_report",
            "delete_url": "/ratools/vp/delete_vp_nasal_inhalation_checklist",
            "modal_body_content": "Nasal-Inhalation..",
            "modal_title": "Nasal-Inhalation Overview",
            "view_sample":view_sample,
            "sample_url":f"/ratools/view_sample_vp_report/{report_name}"
        }
        return render(request, "RATools/baseShow.html", context)
    else:
        return render(request, "RATools/VP/VPNasalInhalation.html",{"show_flag":False,"report_name":report_name})

@login_required(login_url='/adminmaster/login/')
def show_vp_nasal_inhalation_report(request, id):
    report_type = "VP Nasal and Inhalation Report"
    current_user = request.user
    user_report = VPUserReports.objects.get(
        report_name__report_name=report_type,  id=id
    )
    review_task_url = request.build_absolute_uri(
        reverse("show_vp_nasal_inhalation_report", args=[user_report.id])
    )

    # Handle form submission
    if current_user.role == "company_user":
        flag=False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            # Check if the form is being completed
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = VPReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)
                comment = request.POST.get(f"comment_{question.id}", "")

                if answer_value:
                    # Update or create answer
                    answer, created = VPUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name=user_report,
                        report_question=question,
                        defaults={"answer": answer_value, "comment": comment},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    # Email notification setup
                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send email notification
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )


            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            # messages.success(request, 'Answers saved successfully!')
            return redirect("/ratools/show_vp_nasal_inhalation_table")
    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_29
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level,review_task_url)
                user_report.save()
            return redirect("/ratools/show_vp_nasal_inhalation_table")
        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    # Get all questions
    questions = VPReportQuestions.objects.filter(report_name=report_type)

    # Get existing user answers
    user_answers = {}
    if user_report:
        answers = VPUserAnswers.objects.filter(
            report_name=user_report
        )
        for answer in answers:
            user_answers[answer.report_question_id] = {
                "answer": answer.answer,
                "comment": answer.comment,
            }

    # Organize data
    organized_data = {}
    grouped_data = {}

    for question in questions:
        category = question.category
        sub_category = question.sub_category
        sub_sub_category = question.sub_sub_category

        if category not in organized_data:
            organized_data[category] = {}
            grouped_data[question.category] = []

        if sub_category not in organized_data[category]:
            organized_data[category][sub_category] = {}
            grouped_data[question.category].append(question.sub_category)

        if sub_sub_category:
            if sub_sub_category not in organized_data[category][sub_category]:
                organized_data[category][sub_category][sub_sub_category] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][sub_sub_category].append(question)
        else:
            if None not in organized_data[category][sub_category]:
                organized_data[category][sub_category][None] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][None].append(question)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "VP Nasal and Inhalation Checklist",
        "report_name": report_type,
        "user_report": user_report,
        "complete_flag": user_report.show_buttons_doer,
        "show_flag":True,
        "flag":flag,
    }

    return render(request, "RATools/VP/VPNasalInhalation.html", context)

@login_required(login_url='/adminmaster/login/')
def add_vp_nasal_inhalation_checklist(request):
    report_name = "VP Nasal and Inhalation Report"
    if request.method == "POST":
        form = VPForm(
            request.POST,
            user=request.user,
            report_name=VPReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_vp_nasal_inhalation_table")

@login_required(login_url='/adminmaster/login/')
def delete_vp_nasal_inhalation_checklist(request, id):
    try:
        report = VPUserReports.objects.get(id=id)
        VPUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except VPUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")

    return redirect("/ratools/show_vp_nasal_inhalation_table")

# @login_required(login_url='/adminmaster/login/')
def show_vp_ophthalmic_table(request):
    user = request.user
    report_name = "VP Ophthalmic Report"
    if not request.user.is_authenticated:
        return render(request, "RATools/VP/VPOphthalmic.html",{"page_flag" :True,"show_flag":False,"report_name":report_name})

    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = VPUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = VPUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = VPForm(
            user=user,
            report_name=VPReportQuestions.objects.filter(report_name=report_name).first(),
        )

        context = {
            "main_folder":"Upper Management Review Checklist",
            "table_headers": ["Sr. No.", "Product Name","Category", "Status", "Action"],
            "page_heading": "Ophthalmic",
            "reports": reports,
            "form": form,
            "action": "../../ratools/vp/add_vp_ophthalmic_checklist/",
            "edit_url": "/ratools/vp/show_vp_ophthalmic_report",
            "delete_url": "/ratools/vp/delete_vp_ophthalmic_checklist",
            "modal_body_content": "Ophthalmic...",
            "modal_title": "Ophthalmic Overview",
            "view_sample":view_sample,
            "sample_url":f"/ratools/view_sample_vp_report/{report_name}"
        }
        return render(request, "RATools/baseShow.html", context)
    else:
        return render(request, "RATools/VP/VPOphthalmic.html",{"show_flag":False,"report_name":report_name})

@login_required(login_url='/adminmaster/login/')
def show_vp_ophthalmic_report(request, id):
    report_type = "VP Ophthalmic Report"
    current_user = request.user
    user_report = VPUserReports.objects.get(report_name__report_name=report_type, id=id)

    review_task_url = request.build_absolute_uri(
        reverse("show_vp_ophthalmic_report", args=[user_report.id])
    )
    # Handle form submission
    if current_user.role == "company_user":
        flag=False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = VPReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)
                comment = request.POST.get(f"comment_{question.id}", "")

                if answer_value:
                    # Update or create answer
                    answer, created = VPUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name=user_report,
                        report_question=question,
                        defaults={"answer": answer_value, "comment": comment},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    # Email notification setup
                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send email notification
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            # messages.success(request, 'Answers saved successfully!')
            return redirect("/ratools/show_vp_ophthalmic_table")

    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_30
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level,review_task_url)
                user_report.save()
            return redirect("/ratools/show_vp_ophthalmic_table")
        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False
    # Get all questions
    questions = VPReportQuestions.objects.filter(report_name=report_type)

    # Get existing user answers
    user_answers = {}
    if user_report:
        answers = VPUserAnswers.objects.filter(
            report_name=user_report
        )
        for answer in answers:
            user_answers[answer.report_question_id] = {
                "answer": answer.answer,
                "comment": answer.comment,
            }

    # Organize data
    organized_data = {}
    grouped_data = {}

    for question in questions:
        category = question.category
        sub_category = question.sub_category
        sub_sub_category = question.sub_sub_category

        if category not in organized_data:
            organized_data[category] = {}
            grouped_data[question.category] = []

        if sub_category not in organized_data[category]:
            organized_data[category][sub_category] = {}
            grouped_data[question.category].append(question.sub_category)

        if sub_sub_category:
            if sub_sub_category not in organized_data[category][sub_category]:
                organized_data[category][sub_category][sub_sub_category] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][sub_sub_category].append(question)
        else:
            if None not in organized_data[category][sub_category]:
                organized_data[category][sub_category][None] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][None].append(question)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "VP Ophthalmic Checklist",
        "report_name": report_type,
        "user_report": user_report,
        "complete_flag": user_report.show_buttons_doer,
        "show_flag":True,
        "flag":flag,
    }

    return render(request, "RATools/VP/VPOphthalmic.html", context)

@login_required(login_url='/adminmaster/login/')
def add_vp_ophthalmic_checklist(request):
    report_name = "VP Ophthalmic Report"
    if request.method == "POST":
        form = VPForm(
            request.POST,
            user=request.user,
            report_name=VPReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_vp_ophthalmic_table")

@login_required(login_url='/adminmaster/login/')
def delete_vp_ophthalmic_checklist(request, id):
    try:
        report = VPUserReports.objects.get(id=id)
        VPUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except VPUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")

    return redirect("/ratools/show_vp_ophthalmic_table")

# @login_required(login_url='/adminmaster/login/')
def show_vp_liquidorals_table(request):
    user = request.user
    report_name = "VP - Oral Liquids Report"
    if not request.user.is_authenticated:
        return render(request, "RATools/VP/VPLiquidOrals.html",{"page_flag" :True,"show_flag":False, "report_name":report_name})

    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = VPUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = VPUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = VPForm(
            user=user,
            report_name=VPReportQuestions.objects.filter(report_name=report_name).first(),
        )

        context = {
            "main_folder":"Upper Management Review Checklist",
            "table_headers": ["Sr. No.", "Product Name","Category", "Status", "Action"],
            "page_heading": "Liquid Oral",
            "reports": reports,
            "form": form,
            "action": "../../ratools/vp/add_vp_liquidorals_checklist/",
            "edit_url": "/ratools/vp/show_vp_liquidorals_report",
            "delete_url": "/ratools/vp/delete_vp_liquidorals_checklist",
            "modal_body_content": "Liquid Oral...",
            "modal_title": "Liquid Oral Overview",
            "view_sample":view_sample,
            "sample_url":f"/ratools/view_sample_vp_report/{report_name}"
        }
        return render(request, "RATools/baseShow.html", context)
    else:
        return render(request, "RATools/VP/VPLiquidOrals.html",{"show_flag":False, "report_name":report_name})

@login_required(login_url='/adminmaster/login/')
def show_vp_liquidorals_report(request, id):
    report_type = "VP - Oral Liquids Report"
    current_user = request.user
    user_report = VPUserReports.objects.get(
        report_name__report_name=report_type, id=id
    )
    review_task_url = request.build_absolute_uri(
        reverse("show_vp_liquidorals_report", args=[user_report.id])
    )

    # Handle form submission
    if current_user.role == "company_user":
        flag=False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            # Check if the form is being completed
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = VPReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)
                comment = request.POST.get(f"comment_{question.id}", "")

                if answer_value:
                    # Update or create answer
                    answer, created = VPUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name=user_report,
                        report_question=question,
                        defaults={"answer": answer_value, "comment": comment},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    # Email notification setup
                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send email notification
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            # messages.success(request, 'Answers saved successfully!')
            return redirect("/ratools/show_vp_liquidorals_table")
    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_31
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level,review_task_url)
                user_report.save()
            return redirect("/ratools/show_vp_liquidorals_table")
        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    # Get all questions
    questions = VPReportQuestions.objects.filter(report_name=report_type)

    # Get existing user answers
    user_answers = {}
    if user_report:
        answers = VPUserAnswers.objects.filter(
            report_name=user_report
        )
        for answer in answers:
            user_answers[answer.report_question_id] = {
                "answer": answer.answer,
                "comment": answer.comment,
            }

    # Organize data
    organized_data = {}
    grouped_data = {}

    for question in questions:
        category = question.category
        sub_category = question.sub_category
        sub_sub_category = question.sub_sub_category

        if category not in organized_data:
            organized_data[category] = {}
            grouped_data[question.category] = []

        if sub_category not in organized_data[category]:
            organized_data[category][sub_category] = {}
            grouped_data[question.category].append(question.sub_category)

        if sub_sub_category:
            if sub_sub_category not in organized_data[category][sub_category]:
                organized_data[category][sub_category][sub_sub_category] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][sub_sub_category].append(question)
        else:
            if None not in organized_data[category][sub_category]:
                organized_data[category][sub_category][None] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][None].append(question)


    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "VP - Oral Liquids Checklist",
        "report_name": report_type,
        "user_report": user_report,
        "complete_flag": user_report.show_buttons_doer,
        "show_flag":True,
        "flag":flag,
    }

    return render(request, "RATools/VP/VPLiquidOrals.html", context)

@login_required(login_url='/adminmaster/login/')
def add_vp_liquidorals_checklist(request):
    report_name = "VP - Oral Liquids Report"
    if request.method == "POST":
        form = VPForm(
            request.POST,
            user=request.user,
            report_name=VPReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_vp_liquidorals_table")

@login_required(login_url='/adminmaster/login/')
def delete_vp_liquidorals_checklist(request, id):
    try:
        report = VPUserReports.objects.get(id=id)
        VPUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except VPUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")

    return redirect("/ratools/show_vp_liquidorals_table")

# @login_required(login_url='/adminmaster/login/')
def show_vp_parenteral_table(request):
    report_name = "VP - Parenteral Report"
    user = request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/VP/VPParenteral.html",{"page_flag" :True,"show_flag":False, "report_name":report_name})

    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = VPUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = VPUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = VPForm(
            user=request.user,
            report_name=VPReportQuestions.objects.filter(report_name=report_name).first(),
        )

        context = {
            "main_folder":"Upper Management Review Checklist",
            "table_headers": ["Sr. No.", "Product Name","Category", "Status", "Action"],
            "page_heading": "Parenteral",
            "reports": reports,
            "form": form,
            "action": "../../ratools/vp/add_vp_parenteral_checklist/",
            "edit_url": "/ratools/vp/show_vp_parenteral_report",
            "delete_url": "/ratools/vp/delete_vp_parenteral_checklist",
            "modal_body_content": "Parenteral...",
            "modal_title": "Parenteral Overview",
            "view_sample":view_sample,
            "sample_url":f"/ratools/view_sample_vp_report/{report_name}"
        }
        return render(request, "RATools/baseShow.html", context)
    else:
        return render(request, "RATools/VP/VPParenteral.html",{"show_flag":False, "report_name":report_name})


@login_required(login_url='/adminmaster/login/')
def show_vp_parenteral_report(request, id):
    report_type = "VP - Parenteral Report"
    current_user = request.user
    user_report = VPUserReports.objects.get(
        report_name__report_name=report_type, id=id
    )
    review_task_url = request.build_absolute_uri(
        reverse("show_vp_parenteral_report", args=[user_report.id])
    )

    # Handle form submission
    if current_user.role == "company_user":
        flag=False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = VPReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)
                comment = request.POST.get(f"comment_{question.id}", "")

                if answer_value:
                    # Update or create answer
                    answer, created = VPUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name=user_report,
                        report_question=question,
                        defaults={"answer": answer_value, "comment": comment},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    # Email notification setup
                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send email notification
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            # messages.success(request, 'Answers saved successfully!')
            return redirect("/ratools/show_vp_parenteral_table")
    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_32
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level,review_task_url)
                user_report.save()
            return redirect("/ratools/show_vp_parenteral_table")

        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False
    # Get all questions
    questions = VPReportQuestions.objects.filter(report_name=report_type)

    # Get existing user answers
    user_answers = {}
    if user_report:
        answers = VPUserAnswers.objects.filter(
            report_name=user_report
        )
        for answer in answers:
            user_answers[answer.report_question_id] = {
                "answer": answer.answer,
                "comment": answer.comment,
            }

    # Organize data
    organized_data = {}
    grouped_data = {}

    for question in questions:
        category = question.category
        sub_category = question.sub_category
        sub_sub_category = question.sub_sub_category

        if category not in organized_data:
            organized_data[category] = {}
            grouped_data[question.category] = []

        if sub_category not in organized_data[category]:
            organized_data[category][sub_category] = {}
            grouped_data[question.category].append(question.sub_category)

        if sub_sub_category:
            if sub_sub_category not in organized_data[category][sub_category]:
                organized_data[category][sub_category][sub_sub_category] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][sub_sub_category].append(question)
        else:
            if None not in organized_data[category][sub_category]:
                organized_data[category][sub_category][None] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][None].append(question)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "VP - Parenteral Checklist",
        "report_name": report_type,
        "user_report": user_report,
        "complete_flag": user_report.show_buttons_doer,
        "show_flag":True,
        "flag":flag,
    }

    return render(request, "RATools/VP/VPParenteral.html", context)

@login_required(login_url='/adminmaster/login/')
def add_vp_parenteral_checklist(request):
    report_name = "VP - Parenteral Report"
    if request.method == "POST":
        form = VPForm(
            request.POST,
            user=request.user,
            report_name=VPReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_vp_parenteral_table")

@login_required(login_url='/adminmaster/login/')
def delete_vp_parenteral_checklist(request, id):
    try:
        report = VPUserReports.objects.get(id=id)
        VPUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except VPUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")

    return redirect("/ratools/show_vp_parenteral_table")

# @login_required(login_url='/adminmaster/login/')
def show_vp_solidoral_table(request):
    report_name = "VP - Solid Oral Report"
    user = request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/VP/VPSolidOral.html",{"page_flag" :True,"show_flag":False,"report_name":report_name})

    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = VPUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = VPUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = VPForm(
            user=request.user,
            report_name=VPReportQuestions.objects.filter(report_name=report_name).first(),
        )

        context = {
            "main_folder":"Upper Management Review Checklist",
            "table_headers": ["Sr. No.", "Product Name","Category", "Status", "Action"],
            "page_heading": "Solid Oral",
            "reports": reports,
            "form": form,
            "action": "../../ratools/vp/add_vp_solidoral_checklist/",
            "edit_url": "/ratools/vp/show_vp_solidoral_report",
            "delete_url": "/ratools/vp/delete_vp_solidoral_checklist",
            "modal_body_content": "Solid Oral..",
            "modal_title": "Solid Oral Overview",
            "view_sample":view_sample,
            "sample_url":f"/ratools/view_sample_vp_report/{report_name}"
        }
        return render(request, "RATools/baseShow.html", context)
    else:
        return render(request, "RATools/VP/VPSolidOral.html",{"show_flag":False,"report_name":report_name})

@login_required(login_url='/adminmaster/login/')
def show_vp_solidoral_report(request, id):
    report_type = "VP - Solid Oral Report"
    current_user = request.user
    user_report = VPUserReports.objects.get(
        report_name__report_name=report_type, id=id
    )
    review_task_url = request.build_absolute_uri(
        reverse("show_vp_solidoral_report", args=[user_report.id])
    )
    # Handle form submission
    if current_user.role == "company_user":
        flag=False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            is_completing = bool(request.POST.get("completed"))

            questions = VPReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)
                comment = request.POST.get(f"comment_{question.id}", "")

                if answer_value:
                    # Update or create answer
                    answer, created = VPUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name=user_report,
                        report_question=question,
                        defaults={"answer": answer_value, "comment": comment},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send email notification
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            # messages.success(request, 'Answers saved successfully!')
            return redirect("/ratools/show_vp_solidoral_table")

    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_33
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level,review_task_url)
                user_report.save()
            return redirect("/ratools/show_vp_solidoral_table")

        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    # Get all questions
    questions = VPReportQuestions.objects.filter(report_name=report_type)

    # Get existing user answers
    user_answers = {}
    if user_report:
        answers = VPUserAnswers.objects.filter(
            report_name=user_report
        )
        for answer in answers:
            user_answers[answer.report_question_id] = {
                "answer": answer.answer,
                "comment": answer.comment,
            }

    # Organize data
    organized_data = {}
    grouped_data = {}

    for question in questions:
        category = question.category
        sub_category = question.sub_category
        sub_sub_category = question.sub_sub_category

        if category not in organized_data:
            organized_data[category] = {}
            grouped_data[question.category] = []

        if sub_category not in organized_data[category]:
            organized_data[category][sub_category] = {}
            grouped_data[question.category].append(question.sub_category)

        if sub_sub_category:
            if sub_sub_category not in organized_data[category][sub_category]:
                organized_data[category][sub_category][sub_sub_category] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][sub_sub_category].append(question)
        else:
            if None not in organized_data[category][sub_category]:
                organized_data[category][sub_category][None] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][None].append(question)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "VP - Solid Oral Checklist",
        "report_name": report_type,
        "user_report": user_report,
        "complete_flag": user_report.show_buttons_doer,
        "show_flag":True,
        "flag":flag,
    }

    return render(request, "RATools/VP/VPSolidOral.html", context)

@login_required(login_url='/adminmaster/login/')
def add_vp_solidoral_checklist(request):
    report_name = "VP - Solid Oral Report"
    if request.method == "POST":
        form = VPForm(
            request.POST,
            user=request.user,
            report_name=VPReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_vp_solidoral_table")

@login_required(login_url='/adminmaster/login/')
def delete_vp_solidoral_checklist(request, id):
    try:
        report = VPUserReports.objects.get(id=id)
        VPUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except VPUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")

    return redirect("/ratools/show_vp_solidoral_table")

# @login_required(login_url='/adminmaster/login/')
def show_vp_topical_table(request):
    report_name = "VP - Topical Report"
    user = request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/VP/VPTopical.html",{"page_flag" :True,"show_flag":False,"report_name":report_name})

    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = VPUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = VPUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = VPForm(
            user=request.user,
            report_name=VPReportQuestions.objects.filter(report_name=report_name).first(),
        )

        context = {
            "main_folder":"Upper Management Review Checklist",
            "table_headers": ["Sr. No.", "Product Name","Category", "Status", "Action"],
            "page_heading": "Topical",
            "reports": reports,
            "form": form,
            "action": "../../ratools/vp/add_vp_topical_checklist/",
            "edit_url": "/ratools/vp/show_vp_topical_report",
            "delete_url": "/ratools/vp/delete_vp_topical_checklist",
            "modal_body_content": "Topical...",
            "modal_title": "Topical Overview",
            "view_sample":view_sample,
            "sample_url":f"/ratools/view_sample_vp_report/{report_name}"
        }
        return render(request, "RATools/baseShow.html", context)
    else:
        return render(request, "RATools/VP/VPTopical.html",{"show_flag":False,"report_name":report_name})

@login_required(login_url='/adminmaster/login/')
def show_vp_topical_report(request, id):
    report_type = "VP - Topical Report"
    current_user = request.user
    user_report = VPUserReports.objects.get(
        report_name__report_name=report_type, id=id
    )

    review_task_url = request.build_absolute_uri(
        reverse("show_vp_topical_report", args=[user_report.id])
    )
    # Handle form submission
    if current_user.role == "company_user":
        flag=False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            # Check if the form is being completed
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = VPReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)
                comment = request.POST.get(f"comment_{question.id}", "")

                if answer_value:
                    # Update or create answer
                    answer, created = VPUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name=user_report,
                        report_question=question,
                        defaults={"answer": answer_value, "comment": comment},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"
                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send email notification
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            # messages.success(request, 'Answers saved successfully!')
            return redirect("/ratools/show_vp_topical_table")

    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_34
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level,review_task_url)
                user_report.save()
            return redirect("/ratools/show_vp_topical_table")

        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    # Get all questions
    questions = VPReportQuestions.objects.filter(report_name=report_type)

    # Get existing user answers
    user_answers = {}
    if user_report:
        answers = VPUserAnswers.objects.filter(
             report_name=user_report
        )
        for answer in answers:
            user_answers[answer.report_question_id] = {
                "answer": answer.answer,
                "comment": answer.comment,
            }

    # Organize data
    organized_data = {}
    grouped_data = {}

    for question in questions:
        category = question.category
        sub_category = question.sub_category
        sub_sub_category = question.sub_sub_category

        if category not in organized_data:
            organized_data[category] = {}
            grouped_data[question.category] = []

        if sub_category not in organized_data[category]:
            organized_data[category][sub_category] = {}
            grouped_data[question.category].append(question.sub_category)

        if sub_sub_category:
            if sub_sub_category not in organized_data[category][sub_category]:
                organized_data[category][sub_category][sub_sub_category] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][sub_sub_category].append(question)
        else:
            if None not in organized_data[category][sub_category]:
                organized_data[category][sub_category][None] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][None].append(question)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "VP - Topical Checklist",
        "report_name": report_type,
        "user_report": user_report,
        "complete_flag": user_report.show_buttons_doer,
        "show_flag":True,
        "flag":flag,
    }

    return render(request, "RATools/VP/VPTopical.html", context)

@login_required(login_url='/adminmaster/login/')
def add_vp_topical_checklist(request):
    report_name = "VP - Topical Report"
    if request.method == "POST":
        form = VPForm(
            request.POST,
            user=request.user,
            report_name=VPReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_vp_topical_table")

@login_required(login_url='/adminmaster/login/')
def delete_vp_topical_checklist(request, id):
    try:
        report = VPUserReports.objects.get(id=id)
        VPUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except VPUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")

    return redirect("/ratools/show_vp_topical_table")

# @login_required(login_url='/adminmaster/login/')
def show_vp_transdermal_table(request):
    report_name = "VP - Transdermal Report"
    user = request.user
    if not request.user.is_authenticated:
        return render(request, "RATools/VP/VPTransdermal.html",{"page_flag" :True,"show_flag":False, "report_name":report_name})

    assigns = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        reports = VPUserReports.objects.filter(report_name__report_name=report_name, user=user)
    elif user.role == "company_checker":
        if report_name in assigns.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_checker_7 = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            report_name__report_name=report_name,
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_5="True",
        )
        checklists_as_checker_7 = VPUserReports.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_checker_7
            ],
            report_name__report_name=report_name,
            approved_by_checkers_level_6="True",
        )

        reports = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_checker_7
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        reports = VPUserReports.objects.filter(report_name__report_name=report_name)
        view_sample = False
    if report_name in assigns.assigned_report or user.role == "company_checker":
        form = VPForm(
            user=request.user,
            report_name=VPReportQuestions.objects.filter(report_name=report_name).first(),
        )

        context = {
            "main_folder":"Upper Management Review Checklist",
            "table_headers": ["Sr. No.", "Product Name","Category", "Status", "Action"],
            "page_heading": "Transdermal",
            "reports": reports,
            "form": form,
            "action": "../../ratools/vp/add_vp_transdermal_checklist/",
            "edit_url": "/ratools/vp/show_vp_transdermal_report",
            "delete_url": "/ratools/vp/delete_vp_transdermal_checklist",
            "modal_body_content": "Transdermal...",
            "modal_title": "Transdermal Overview",
            "view_sample":view_sample,
            "sample_url":f"/ratools/view_sample_vp_report/{report_name}"
        }
        return render(request, "RATools/baseShow.html", context)
    else:
        return render(request, "RATools/VP/VPTransdermal.html",{"show_flag":False, "report_name":report_name})


@login_required(login_url='/adminmaster/login/')
def show_vp_transdermal_report(request, id):
    report_type = "VP - Transdermal Report"
    current_user = request.user
    user_report = VPUserReports.objects.get(
        report_name__report_name=report_type, id=id
    )
    review_task_url = request.build_absolute_uri(
        reverse("show_vp_transdermal_report", args=[user_report.id])
    )

    # Handle form submission
    if current_user.role == "company_user":
        flag=False
        assignment = AssignChecker.objects.get(user=current_user)
        if request.method == "POST":
            is_completing = bool(request.POST.get("completed"))

            # Get all questions for this report
            questions = VPReportQuestions.objects.filter(report_name=report_type)

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)
                comment = request.POST.get(f"comment_{question.id}", "")

                if answer_value:
                    # Update or create answer
                    answer, created = VPUserAnswers.objects.update_or_create(
                        user=current_user,
                        report_name=user_report,
                        report_question=question,
                        defaults={"answer": answer_value, "comment": comment},
                    )

            # Update completion status if form is being completed
            if is_completing and user_report:
                user_report.is_completed_by_doer = True
                user_report.show_buttons_doer = False
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in user_report.statues:
                        user_report.statues["Checker Level 1 Status"] = {}
                    if i.id not in user_report.statues["Checker Level 1 Status"]:
                        user_report.statues["Checker Level 1 Status"][i.id] = {}
                    user_report.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"

                    # Email notification setup
                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                            }}
                        </style>
                    </head>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>Greetings !!!</p>
                        <p>The task <strong>{user_report.product_name}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                        <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                        <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                        <p>Best regards,</p>
                        <p>{user_report.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                    </body>
                    </html>
                    """

                    plain_message = f"""
                        Subject: Regulatory Checklist Task Submission Notification: {user_report.product_name}

                        Dear {i.first_name},

                        Greetings !!!

                        The task {user_report.product_name} has been successfully submitted and is now ready for your review & inputs.

                        You can access it here: {review_task_url}

                        Thank you for your prompt attention to this. Please let me know if any clarification is required.

                        Best regards,
                        {user_report.user.first_name} via iCretegy's Regulatory Checklist Software
                    """

                    # Send email notification
                    send_mail(
                        subject=f"Regulatory Checklist Task Submission Notification: {user_report.product_name}",
                        message=plain_message,
                        from_email=user_report.user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if user_report.statues is None:
                    user_report.statues = {}
                if "Your Status" not in user_report.statues:
                    user_report.statues["Your Status"] = {}
                if current_user.id not in user_report.statues["Your Status"]:
                    user_report.statues["Your Status"] = {}
                    user_report.statues["Your Status"][current_user.id] = {}
                user_report.statues["Your Status"][current_user.id][current_user.first_name] = "Pending"
            user_report.save()

            # messages.success(request, 'Answers saved successfully!')
            return redirect("/ratools/show_vp_transdermal_table")
    elif current_user.role == "company_checker":
        assigned_user = user_report.user
        assignment = AssignChecker.objects.get(user=assigned_user)
        last_level = assignment.level_report_35
        current_level =  get_checker_level(current_user.id, assignment.checkers_json)
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(user_report, current_user, assignment, action, current_level, last_level,review_task_url)
                user_report.save()
            return redirect("/ratools/show_vp_transdermal_table")

        if user_report.statues[f"Checker Level {current_level} Status"][str(current_user.id)][current_user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    # Get all questions
    questions = VPReportQuestions.objects.filter(report_name=report_type)

    # Get existing user answers
    user_answers = {}
    if user_report:
        answers = VPUserAnswers.objects.filter(
            report_name=user_report
        )
        for answer in answers:
            user_answers[answer.report_question_id] = {
                "answer": answer.answer,
                "comment": answer.comment,
            }

    # Organize data
    organized_data = {}
    grouped_data = {}

    for question in questions:
        category = question.category
        sub_category = question.sub_category
        sub_sub_category = question.sub_sub_category

        if category not in organized_data:
            organized_data[category] = {}
            grouped_data[question.category] = []

        if sub_category not in organized_data[category]:
            organized_data[category][sub_category] = {}
            grouped_data[question.category].append(question.sub_category)

        if sub_sub_category:
            if sub_sub_category not in organized_data[category][sub_category]:
                organized_data[category][sub_category][sub_sub_category] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][sub_sub_category].append(question)
        else:
            if None not in organized_data[category][sub_category]:
                organized_data[category][sub_category][None] = []

            if question.id in user_answers:
                question.checklist_answers = type(
                    "Answer",
                    (),
                    {
                        "answer": user_answers[question.id]["answer"],
                        "comment": user_answers[question.id]["comment"],
                    },
                )()

            organized_data[category][sub_category][None].append(question)

    context = {
        "organized_data": organized_data,
        "grouped_data": grouped_data,
        "heading": "VP - Transdermal Checklist",
        "report_name": report_type,
        "user_report": user_report,
        "complete_flag": user_report.show_buttons_doer,
        "show_flag":True,
        "flag":flag,
    }

    return render(request, "RATools/VP/VPTransdermal.html", context)

@login_required(login_url='/adminmaster/login/')
def add_vp_transdermal_checklist(request):
    report_name = "VP - Transdermal Report"
    if request.method == "POST":
        form = VPForm(
            request.POST,
            user=request.user,
            report_name=VPReportQuestions.objects.filter(
                report_name=report_name
            ).first(),
        )
        if form.is_valid():
            form.save()
        else:
            print("Form Error", form.errors)
    return redirect("/ratools/show_vp_transdermal_table")

@login_required(login_url='/adminmaster/login/')
def delete_vp_transdermal_checklist(request, id):
    try:
        report = VPUserReports.objects.get(id=id)
        VPUserAnswers.objects.filter(report_name=report).delete()
        report.delete()
    except VPUserReports.DoesNotExist:
        messages.error(request, "Report not found!")
    except Exception as e:
        messages.error(request, f"Error deleting report: {str(e)}")

    return redirect("/ratools/show_vp_transdermal_table")


# White Paper Views Function Should be below this line

# @login_required(login_url='/adminmaster/login/')
# def add_appendix_checklist(request):
#     if request.method == "POST":
#         form = AppendixForm(request.POST, user=request.user)
#         if form.is_valid():
#             form.save()
#         else:
#             print(form.errors)
#     return redirect("../../ratools/appendix_white_paper")

# @login_required(login_url='/adminmaster/login/')
# def appendix_white_paper(request):
#     return render(
#         request, "RATools/WhitePaper/Appendix1CombinationProductAssessmentForm.html"
#     )

def update_checker_status(checklist, user, assignment, action, current_level, last_level, review_task_url=None):
    level_key = f"Checker Level {current_level} Status"
    level_key_next = f"Checker Level {current_level + 1} Status"

    # Initialize status dictionaries if they don't exist
    if level_key not in checklist.statues:
        checklist.statues[level_key] = {}
    if user.id not in checklist.statues[level_key]:
        checklist.statues[level_key][user.id] = {}

    status = "Approved" if action == "Approve" else "Rejected"
    checklist.statues[level_key][user.id][user.first_name] = status

    if action == "Reject":
        level_key_current = f"Checker Level {current_level - 1} Status"
        print("level_key_current",level_key_current)
        if level_key_current in checklist.statues:
                for checker_id in assignment.checkers_json[f"level_{current_level - 1}"]:
                    print("checker_id Befour",checker_id)
                    if str(checker_id) in checklist.statues[level_key_current]:
                        print("checker_id",checker_id)
                        for name in checklist.statues[level_key_current][str(checker_id)]:
                                    print("\n\n>>>Reject Name>>",name)
                                    checklist.statues[level_key_current][str(checker_id)][name] = "In Review"

        # Update user status to pending
        if current_level == 1:
            if "Your Status" not in checklist.statues:
                checklist.statues["Your Status"] = {}
            if checklist.user.id not in checklist.statues["Your Status"]:
                checklist.statues["Your Status"][checklist.user.id] = {}
            checklist.statues["Your Status"][checklist.user.id][checklist.user.first_name] = "Pending"
            # Enable doer buttons
            checklist.show_buttons_doer = True

    level_checkers = assignment.checkers_json[f"level_{current_level}"]
    print("\n\n>>>>>Level  checker>>>>",level_checkers)
    current_level_statuses = checklist.statues.get(level_key, {})
    current_level_statuses_next = checklist.statues.get(level_key_next, {})

    # Count of "In Review" statuses
    in_review_count = sum(
        1 for checker_id in level_checkers
        for status in current_level_statuses.get(str(checker_id), {}).values()
        if status == "In Review"
    )

    # Check if the current user's status is "Approve"
    current_user_approved = (
        current_level_statuses.get(str(user.id), {}).get(user.first_name) == "In Review"
    )

    all_approved = (
        all(status == "Approved" for checker_id in level_checkers
            for status in current_level_statuses.get(str(checker_id), {}).values())
        or
        (in_review_count == 1 and current_user_approved and action == "Approve")
    )

    if all_approved:
        for i in assignment.checkers_json[f"level_{current_level + 1}"]:
                        html_message = f"""
                        <!DOCTYPE html>
                        <html>
                        <head>
                            <style>
                                body {{
                                    font-family: Arial, sans-serif;
                                }}
                            </style>
                        </head>
                        <body>
                            <p>Dear { CustomUser.objects.get(id=i).first_name },</p>
                            <p>Greetings !!!</p>
                                <p>The task <strong>{checklist.product_name if hasattr(checklist,'product_name') else checklist.name_of_api}</strong> has been successfully submitted and is now ready for your review &amp; inputs.</p>
                            <p>You can access it here: <a href="{review_task_url}">Review Task</a>.</p>
                            <p>Thank you for your prompt attention to this. Please let me know if any clarification is required.</p>
                            <p>Best regards,</p>
                            <p>{checklist.user.first_name} via iCretegy's Regulatory Checklist Software</p>
                        </body>
                        </html>
                        """

                        plain_message = f"""
                            Subject: Regulatory Checklist Task Submission Notification: {checklist.product_name if hasattr(checklist,'product_name') else checklist.name_of_api}

                            Dear {CustomUser.objects.get(id=i).first_name},

                            Greetings !!!

                            The task {checklist.product_name if hasattr(checklist,'product_name') else checklist.name_of_api} has been successfully submitted and is now ready for your review & inputs.

                            You can access it here: {review_task_url}

                            Thank you for your prompt attention to this. Please let me know if any clarification is required.

                            Best regards,
                            {checklist.user.first_name} via iCretegy's Regulatory Checklist Software
                        """

                        # Send personalized email to each checker
                        send_mail(
                            subject=f"Regulatory Checklist Task Submission Notification: {checklist.product_name if hasattr(checklist,'product_name') else checklist.name_of_api}",
                            message=plain_message,
                            # from_email=checklist.user.email,
                            from_email=settings.DEFAULT_FROM_EMAIL,
                            recipient_list=[CustomUser.objects.get(id=i).email],
                            html_message=html_message,
                        )
                        print("email sent to checker",CustomUser.objects.get(id=i).first_name)


    level_checkers_next = assignment.checkers_json[f"level_{current_level + 1}"]

    flag_reject = (
        any(status == "Rejected" for checker_id in level_checkers_next
            for status in current_level_statuses_next.get(str(checker_id), {}).values())
    )

    level_checkers_next = assignment.checkers_json[f"level_{current_level + 1}"]

    flag_reject = (
        any(status == "Rejected" for checker_id in level_checkers_next
            for status in current_level_statuses_next.get(str(checker_id), {}).values())
    )

    current_approval = getattr(checklist, f"approved_by_checkers_level_{current_level}")
    print("\n\n>>Current Level>>>>",current_level)
    print("\n\n>>last_level>>>>",last_level)
    # Only set approval flag if all have approved and it's not already True
    if current_level <= last_level:
        if (all_approved and current_approval not in ["True", "Done"]) or flag_reject:
            if current_level == last_level:
                setattr(checklist, f"approved_by_checkers_level_{current_level}", "Done")
            else:
                setattr(checklist, f"approved_by_checkers_level_{current_level}", "True")

            # If this level is newly approved, set next level to "In Review"
            if current_level <= last_level:
                print("\n\n>>Current Level>>>> inside ",current_level)
                print("\n\n>>last_level>>>> inside ",last_level)
                next_level_key = f"Checker Level {current_level + 1} Status"
                for checker_id in assignment.checkers_json[f"level_{current_level + 1}"]:
                    if next_level_key not in checklist.statues:
                        checklist.statues[next_level_key] = {}
                    if str(checker_id) not in checklist.statues[next_level_key]:
                        checklist.statues[next_level_key][str(checker_id)] = {}
                    checklist.statues[next_level_key][str(checker_id)][CustomUser.objects.get(id=checker_id).first_name] = "In Review"

    return checklist

def get_checker_level(user_id, checkers_json):
    """Returns the level number (1-7) of the checker based on checkers_json"""
    for level, checker_ids in checkers_json.items():
        if user_id in checker_ids:
            return int(level.split('_')[1])
    return None

# def get_checker_level(user_id, checkers_json):
#     """Returns the level number (1-7) of the checker based on checkers_json"""
#     for level, checker_ids in checkers_json.items():
#         if user_id in checker_ids:
#             return int(level.split('_')[1])
#     return None

@login_required(login_url='/adminmaster/login/')
def view_general_white_paper_sample(request):
    questions = GeneralReportQuestions.objects.all()
    organized_data = {}
    for question in questions:
        category = question.category
        sub_category = question.sub_category

        if category not in organized_data:
            organized_data[category] = {}

        if sub_category not in organized_data[category]:
            organized_data[category][sub_category] = []

        question.checklist_answers = type(
            "Answer",
            (),
            {
                "answer": None,
                "comment": None,
            },
        )()

        organized_data[category][sub_category].append(question)
    context = {
        "organized_data":organized_data,
        "show_flag":True,
        "complete_flag":False,
        "flag":False,
    }
    return render(request,"RATools/WhitePaper/GeneralWhitePaper.html",context)

@login_required(login_url='/adminmaster/login/')
def general_white_paper_report(request, id):
    user = request.user
    checklist = GeneralChecklistUSer.objects.get(id=id)
    data = GeneralAnswer.objects.get(checklist=checklist)
    table_13 = GeneralTable13.objects.filter(ans_rel=data)
    table_14 = GeneralTable14.objects.filter(ans_rel=data)
    complete_flag = checklist.show_buttons_doer
    appendix_data = AppendixWhitePaper.objects.get(checklist_user=checklist)
    apx_table = AppendixTableRowsAnswers.objects.filter(appendix=appendix_data)


    review_task_url = request.build_absolute_uri(
        reverse("general_white_paper_report", args=[checklist.id])
    )

    if user.role == "company_user":
        flag=False
        assignment = AssignChecker.objects.get(user=user)
        if request.method == "POST":
            data.product_name = request.POST.get("product_name")
            data.strength = request.POST.get("strength")
            data.dosage_form = request.POST.get("dosage_form")
            data.filing_category = request.POST.get("filing_category")
            data.product_manu_site = request.POST.get("product_manu_site")
            data.anda_holder_name = request.POST.get("anda_holder_name")
            data.dmf_holder = request.POST.get("dmf_holder")
            data.dmf_manu_site = request.POST.get("dmf_manu_site")
            data.proprietary_name_rld = request.POST.get("proprietary_name_rld")
            data.rld_rs_strength_rld = request.POST.get("rld_rs_strength_rld")
            data.nda_anda_rld = request.POST.get("nda_anda_rld")
            data.approval_date_rld = request.POST.get("approval_date_rld")
            data.nda_holder_rld = request.POST.get("nda_holder_rld")
            data.te_code_rld = request.POST.get("te_code_rld")
            data.max_daily_dose_rld = request.POST.get("max_daily_dose_rld")
            data.rems_requirement_rld = request.POST.get("rems_requirement_rld")
            data.proprietary_name_rs = request.POST.get("proprietary_name_rs")
            data.rld_rs_strength_rs = request.POST.get("rld_rs_strength_rs")
            data.nda_anda_rs = request.POST.get("nda_anda_rs")
            data.approval_date_rs = request.POST.get("approval_date_rs")
            data.nda_holder_rs = request.POST.get("nda_holder_rs")
            data.te_code_rs = request.POST.get("te_code_rs")
            data.max_daily_dose_rs = request.POST.get("max_daily_dose_rs")
            data.rems_requirement_rs = request.POST.get("rems_requirement_rs")
            if request.FILES.get("patent_snapshot"):
                data.patent_snapshot = request.FILES.get("patent_snapshot")
            if request.FILES.get("exclusivity_snapshot"):
                data.exclusivity_snapshot = request.FILES.get("exclusivity_snapshot")
            data.dosing_regimen_rld = request.POST.get("dosing_regimen_rld")
            data.dosing_regimen_proposed = request.POST.get("dosing_regimen_proposed")
            data.indication_rld = request.POST.get("indication_rld")
            data.indication_proposed = request.POST.get("indication_proposed")
            data.proposed_mdd = request.POST.get("proposed_mdd")
            data.basis_mdd = request.POST.get("basis_mdd")
            data.control_mdd = request.POST.get("control_mdd")
            data.drug_shortage_status = request.POST.get("drug_shortage_status")
            data.date_first_period = request.POST.get("date_first_period")
            if request.FILES.get("drug_shortage_snap"):
                data.drug_shortage_snap = request.FILES.get("drug_shortage_snap")
            data.is_api = request.POST.get("is_api")
            data.have_potential = request.POST.get("have_potential")
            if request.FILES.get("snapshot_7"):
                data.snapshot_7 = request.FILES.get("snapshot_7")
            data.pre_assign_anda_number = request.POST.get("pre_assign_anda_number")
            data.if_yes_9 = request.POST.get("if_yes_9")  # boolean field
            data.detail_9 = request.POST.get("detail_9")
            data.regular_history = request.POST.get("regular_history")
            data.drug_sub_dmf_status = request.POST.get("drug_sub_dmf_status")
            data.detail_12 = request.POST.get("detail_12")
            data.detail_13 = request.POST.get("detail_13")
            data.detail_15 = request.POST.get("detail_15")
            data.detail_16 = request.POST.get("detail_16")
            data.detail_17 = request.POST.get("detail_17")
            data.detail_18 = request.POST.get("detail_18")
            data.detail_19 = request.POST.get("detail_19")
            data.detail_20 = request.POST.get("detail_20")
            data.detail_21 = request.POST.get("detail_21")
            data.detail_22 = request.POST.get("detail_22")
            data.detail_23 = request.POST.get("detail_23")
            if request.FILES.get("snapshot_23"):
                data.snapshot_23 = request.FILES.get("snapshot_23")
            data.detail_24 = request.POST.get("detail_24")
            data.detail_25_1 = request.POST.get("detail_25_1")
            data.detail_25_2 = request.POST.get("detail_25_2")
            data.detail_25_3 = request.POST.get("detail_25_3")
            data.save()

            #Combination Product Assessment Form
            appendix_data.product_strength = request.POST.get("product_strength")
            appendix_data.anda_nda = request.POST.get("anda_nda")
            appendix_data.applicant = request.POST.get("applicant")
            appendix_data.pr_manu_site = request.POST.get("pr_manu_site")
            appendix_data.package_type = request.POST.get("package_type")

            appendix_data.ir_tablet = bool(request.POST.get("ir_tablet"))
            appendix_data.ir_capsule = bool(request.POST.get("ir_capsule"))
            appendix_data.er_tablet = bool(request.POST.get("er_tablet"))
            appendix_data.er_capsule = bool(request.POST.get("er_capsule"))
            appendix_data.topical = bool(request.POST.get("topical"))
            appendix_data.sub_tablets = bool(request.POST.get("sub_tablets"))
            appendix_data.top_trans_gel = bool(request.POST.get("top_trans_gel"))
            appendix_data.nasal_sp = bool(request.POST.get("nasal_sp"))
            appendix_data.oral_sss = bool(request.POST.get("oral_sss"))
            appendix_data.ointment = bool(request.POST.get("ointment"))
            appendix_data.inhalation = bool(request.POST.get("inhalation"))
            appendix_data.inj_pep_com = bool(request.POST.get("inj_pep_com"))
            appendix_data.tdds = bool(request.POST.get("tdds"))
            appendix_data.ophthalmic = bool(request.POST.get("ophthalmic"))
            appendix_data.other_1 = bool(request.POST.get("other_1"))
            appendix_data.other_2 = bool(request.POST.get("other_2"))
            appendix_data.other_3 = bool(request.POST.get("other_3"))

            appendix_data.other_name_1 = request.POST.get("other_name_1")
            appendix_data.other_name_2 = request.POST.get("other_name_2")
            appendix_data.other_name_3 = request.POST.get("other_name_3")
            # Basis of Submission
            appendix_data.rld_product = request.POST.get("rld_product")
            appendix_data.basis_anda = request.POST.get("basis_anda")
            appendix_data.basis_anda_applicant = request.POST.get("basis_anda_applicant")
            appendix_data.market_avail_rx = bool(request.POST.get("market_avail_rx"))
            appendix_data.market_avail_otc = bool(request.POST.get("market_avail_otc"))
            # Combination Product Assessment Form
            appendix_data.com_product_name = request.POST.get("com_product_name")
            appendix_data.com_anda = request.POST.get("com_anda")
            appendix_data.date_anda = request.POST.get("date_anda")
            appendix_data.current_status_literature = bool(request.POST.get("current_status_literature"))
            appendix_data.current_status_development = bool(request.POST.get("current_status_development"))
            appendix_data.current_status_execution = bool(request.POST.get("current_status_execution"))
            appendix_data.current_status_submission = bool(request.POST.get("current_status_submission"))
            appendix_data.current_status_fda = bool(request.POST.get("current_status_fda"))
            appendix_data.current_status_approved = bool(request.POST.get("current_status_approved"))
            appendix_data.reference_list_drug = request.POST.get("reference_list_drug")
            appendix_data.nda_anda_form = request.POST.get("nda_anda_form")
            appendix_data.applicant_rld = request.POST.get("applicant_rld")
            if request.FILES.get("rld_package_config"):
                appendix_data.rld_package_config = request.FILES.get("rld_package_config")
            if request.FILES.get("company_package_config"):
                appendix_data.company_package_config = request.FILES.get("company_package_config")

            appendix_data.description_device_1 = request.POST.get("description_device_1")
            appendix_data.description_device_2 = request.POST.get("description_device_2")
            appendix_data.description_device_3 = request.POST.get("description_device_3")
            appendix_data.company_anda_form = request.POST.get("company_anda_form")
            appendix_data.rld_cross_labeled = request.POST.get("rld_cross_labeled")
            appendix_data.type_comb_pro_single = bool(request.POST.get("type_comb_pro_single"))
            appendix_data.type_comb_pro_co_packaged = bool(request.POST.get("type_comb_pro_co_packaged"))
            appendix_data.type_comb_pro_cross_labeled = bool(request.POST.get("type_comb_pro_cross_labeled"))
            appendix_data.category_1_device = bool(request.POST.get("category_1_device"))
            appendix_data.category_2_device = bool(request.POST.get("category_2_device"))
            appendix_data.category_3_device = bool(request.POST.get("category_3_device"))
            appendix_data.category_convenience = bool(request.POST.get("category_convenience"))
            appendix_data.category_prefilled_drug = bool(request.POST.get("category_prefilled_drug"))
            appendix_data.category_prefilled_biologic = bool(request.POST.get("category_prefilled_biologic"))
            appendix_data.category_device_coated_drug = bool(request.POST.get("category_device_coated_drug"))
            appendix_data.category_device_coated_biologic = bool(request.POST.get("category_device_coated_biologic"))
            appendix_data.category_drug_biologic_combination = bool(request.POST.get("category_drug_biologic_combination"))
            appendix_data.category_separate_product = bool(request.POST.get("category_separate_product"))
            appendix_data.category_possible_combination = bool(request.POST.get("category_possible_combination"))
            appendix_data.category_other_type = bool(request.POST.get("category_other_type"))

            appendix_data.plan_device_assembly = request.POST.get("plan_device_assembly")
            appendix_data.instruction_of_use = request.POST.get("instruction_of_use")
            appendix_data.diff_com_rld = request.POST.get("diff_com_rld")
            appendix_data.if_yes_diff_device = request.POST.get("if_yes_diff_device")
            appendix_data.other_attr_specific = request.POST.get("other_attr_specific")
            appendix_data.conclusion = request.POST.get("conclusion")

            # Appendix 1: List of Item
            appendix_data.threshold_analysis_shared_by = request.POST.get("threshold_analysis_shared_by")
            appendix_data.threshold_analysis_review_completion = request.POST.get("threshold_analysis_review_completion")
            appendix_data.threshold_analysis_final_review = request.POST.get("threshold_analysis_final_review")

            # print("appendix_data",request.POST.get("threshold_analysis_shared_by"))
            appendix_data.threshold_finding_shared_by = request.POST.get("threshold_finding_shared_by")
            appendix_data.threshold_finding_review_completion = request.POST.get("threshold_finding_review_completion")
            appendix_data.threshold_finding_final_review = request.POST.get("threshold_finding_final_review")

            appendix_data.design_dev_shared_by = request.POST.get("design_dev_shared_by")
            appendix_data.design_dev_review_completion = request.POST.get("design_dev_review_completion")
            appendix_data.design_dev_final_review = request.POST.get("design_dev_final_review")

            appendix_data.dhf_shared_by = request.POST.get("dhf_shared_by")
            appendix_data.dhf_review_completion = request.POST.get("dhf_review_completion")
            appendix_data.dhf_final_review = request.POST.get("dhf_final_review")

            appendix_data.risk_analysis_shared_by = request.POST.get("risk_analysis_shared_by")
            appendix_data.risk_analysis_review_completion = request.POST.get("risk_analysis_review_completion")
            appendix_data.risk_analysis_final_review = request.POST.get("risk_analysis_final_review")

            appendix_data.qsr_design_shared_by = request.POST.get("qsr_design_shared_by")
            appendix_data.qsr_design_review_completion = request.POST.get("qsr_design_review_completion")
            appendix_data.qsr_design_final_review = request.POST.get("qsr_design_final_review")

            appendix_data.cgmp_qsr_shared_by = request.POST.get("cgmp_qsr_shared_by")
            appendix_data.cgmp_qsr_review_completion = request.POST.get("cgmp_qsr_review_completion")
            appendix_data.cgmp_qsr_final_review = request.POST.get("cgmp_qsr_final_review")

            appendix_data.vendor_docs_shared_by = request.POST.get("vendor_docs_shared_by")
            appendix_data.vendor_docs_review_completion = request.POST.get("vendor_docs_review_completion")
            appendix_data.vendor_docs_final_review = request.POST.get("vendor_docs_final_review")

            appendix_data.save()

            checklist.is_completed_by_doer = bool(request.POST.get("completed"))
            if bool(request.POST.get("completed")):
                checklist.show_buttons_doer = False
                if checklist.statues is None:
                    checklist.statues = {}
                if "Your Status" not in checklist.statues:
                    checklist.statues["Your Status"] = {}
                if user.id not in checklist.statues["Your Status"]:
                    checklist.statues["Your Status"][user.id] = {}
                checklist.statues["Your Status"][user.id][user.first_name] = "Submitted"

                for i in assignment.assigned_checker_level_1.all():
                    if "Checker Level 1 Status" not in checklist.statues:
                        checklist.statues["Checker Level 1 Status"] = {}
                    if i.id not in checklist.statues["Checker Level 1 Status"]:
                        checklist.statues["Checker Level 1 Status"][i.id] = {}
                    checklist.statues["Checker Level 1 Status"][i.id][i.first_name] = "In Review"
                     # Email notification setup
                    html_message = f"""
                    <!DOCTYPE html>
                    <html>
                    <body>
                        <p>Dear {i.first_name},</p>
                        <p>The task <strong>{data.product_name}</strong> has been submitted for your review.</p>
                        <p><a href=\"{review_task_url}\">Review Task</a></p>
                        <p>Best regards,</p>
                        <p>{user.first_name}</p>
                    </body>
                    </html>
                    """
                    plain_message = f"""
                        Dear {i.first_name},
                        The task {data.product_name} has been submitted for your review.
                        Access it here: {review_task_url}
                        Best regards,
                        {user.first_name}
                    """
                    # print("NAME OF I",i)
                    send_mail(
                        subject=f"Task Submission Notification: {data.product_name}",
                        message=plain_message,
                        from_email=user.email,
                        recipient_list=[i.email],
                        html_message=html_message,
                    )
            else:
                if checklist.statues is None:
                    checklist.statues = {}
                if "Your Status" not in checklist.statues:
                    checklist.statues["Your Status"] = {}
                if user.id not in checklist.statues["Your Status"]:
                    checklist.statues["Your Status"] = {}
                    checklist.statues["Your Status"][user.id] = {}
                checklist.statues["Your Status"][user.id][user.first_name] = "Pending"
            checklist.save()
            # print("Comments of the checker", request.POST.get("checkerCommentData"))
            table_13_data = request.POST.get("productTableData")
            # print("table_13_data", table_13_data)
            if table_13_data:
                try:
                    table_13_data = json.loads(table_13_data)

                    # First, delete existing instances for this data for table 13
                    GeneralTable13.objects.filter(ans_rel=data).delete()

                    for row in table_13_data:
                        GeneralTable13.objects.create(
                            ans_rel=data,
                            ingredients=row["ingredients"],
                            salt=row["salt"],
                            rld_formation=row["rld_formation"],
                            proposed_generic=row["proposed_generic"],
                            function=row["function"],
                        )
                except json.JSONDecodeError:
                    print("Error decoding table data")
                except Exception as e:
                    print(f"Error saving table data: {str(e)}")

            table_14_data = request.POST.get("assessmentTableData")
            # print("table_14_data",table_14_data)
            if table_14_data:
                try:
                    table_14_data = json.loads(table_14_data)

                    GeneralTable14.objects.filter(ans_rel=data).delete()

                    for row in table_14_data:
                        GeneralTable14.objects.create(
                            ans_rel=data,
                            ingredients=row["ingredients"],
                            qty_ml=row["qty_ml"],
                            w_v=row["w_v"],
                            total_daily_intake=row["total_daily_intake"],
                            max_potency=row["max_potency"],
                        )
                except json.JSONDecodeError:
                    print("Error decoding table data")
                except Exception as e:
                    print(f"Error saving table data: {str(e)}")

            apx_table_data = request.POST.get("apxTableData")
            # print("Raw apx_table_data:", apx_table_data)

            if apx_table_data:
                try:
                    apx_table_data = json.loads(apx_table_data)
                    AppendixTableRowsAnswers.objects.filter(appendix=appendix_data).delete()

                    for row in apx_table_data:
                        AppendixTableRowsAnswers.objects.create(
                            appendix=appendix_data,
                            QSR_list= row["QSR_list"],
                            ownership=row["ownership"],
                            initial_template=row["initial_template"],
                            responsibility_review=row["responsibility_review"],
                            review_completion=row["review_completion"],
                            final_review=row["final_review"],
                        )
                    print("apx_table_data",apx_table_data)
                except json.JSONDecodeError:
                    print("Error decoding appendix table data")
                except Exception as e:
                    print(f"Error saving appendix table data: {str(e)}")

            questions = GeneralReportQuestions.objects.all()

            for question in questions:
                answer_key = f"answer_{question.id}"
                answer_value = request.POST.get(answer_key)
                # comment_key = f"comment_{question.id}"
                # comment_value = request.POST.get(comment_key)
                comment = request.POST.get(f"comment_{question.id}", "")
                # print("comment_value",comment)

                if answer_value:
                    answer, created = GeneralUserAnswers.objects.update_or_create(
                        ans_rel=data,
                        report_question_id=question.id,
                        defaults={"answer": answer_value, "comment": comment},
                    )
            print("Redirecting to /ratools/general_white_paper_table")
            return redirect("/ratools/general_white_paper_table")
        # return redirect("/ratools/general_white_paper_table")

    elif user.role == "company_checker":
        assigner_user = checklist.user
        assignment = AssignChecker.objects.get(user=assigner_user)
        current_level =  get_checker_level(user.id, assignment.checkers_json)
        last_level = assignment.level_report_38
        if request.method == "POST":
            action = request.POST.get("checker_action")
            if action in ["Approve", "Reject"]:
                update_checker_status(checklist, user, assignment, action, current_level, last_level,review_task_url)
                checklist.save()
            return redirect("/ratools/general_white_paper_table")

        if checklist.statues[f"Checker Level {current_level} Status"][str(user.id)][user.first_name] == "In Review":
            flag = True
        else:
            flag = False
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        flag = False

    questions = GeneralReportQuestions.objects.all()
    user_answers = {}
    if checklist:
        # Change this line to include both answer and comment
        answers = GeneralUserAnswers.objects.filter(
            ans_rel=data
        )  # Added ans_rel filter
        user_answers = {
            answer.report_question_id: {
                "answer": answer.answer,
                "comment": answer.comment,
            }
            for answer in answers
        }

    organized_data = {}
    for question in questions:
        category = question.category
        sub_category = question.sub_category

        if category not in organized_data:
            organized_data[category] = {}

        if sub_category not in organized_data[category]:
            organized_data[category][sub_category] = []

        # Move this outside the sub_category check
        if question.id in user_answers:
            question.checklist_answers = type(
                "Answer",
                (),
                {
                    "answer": user_answers[question.id]["answer"],
                    "comment": user_answers[question.id]["comment"],
                },
            )()

        organized_data[category][sub_category].append(question)
    table_13 = GeneralTable13.objects.filter(ans_rel=data)
    table_14 = GeneralTable14.objects.filter(ans_rel=data)
    apx_table = AppendixTableRowsAnswers.objects.filter(appendix=appendix_data)
    print("apx_table",apx_table)
    return render(
        request,
        "RATools/WhitePaper/GeneralWhitePaper.html",
        {
            "checklist": checklist,
            "data": data,
            "table_13": table_13,
            "table_14": table_14,
            "organized_data": organized_data,
            "show_flag": True,
            "complete_flag": complete_flag,
            "flag":flag,
            "appendix_data": appendix_data,
            "apx_table":apx_table,
        },
    )

# @login_required(login_url='/adminmaster/login/')
def general_white_paper_table(request):
    user = request.user
    if not request.user.is_authenticated:
        return render(
            request,
            "RATools/WhitePaper/GeneralWhitePaper.html",
            {
                "page_flag" :True,
                "show_flag": False,
                "heading": "",
                "report_name": "General White Paper",
            },
        )

    report_name = "General White Paper"
    assignments = AssignChecker.objects.get(user=user)
    if user.role == "company_user":
        view_sample = False
        checklist = GeneralChecklistUSer.objects.filter(user=request.user)
    elif user.role == "company_checker":
        if report_name in assignments.view_sample_reports:
            view_sample = True
        else:
            view_sample = False
        assigned_reports_as_checker_1 = AssignChecker.objects.filter(
            assigned_checker_level_1=user
        )
        assigned_reports_as_checker_2 = AssignChecker.objects.filter(
            assigned_checker_level_2=user
        )
        assigned_reports_as_checker_3 = AssignChecker.objects.filter(
            assigned_checker_level_3=user
        )
        assigned_reports_as_checker_4 = AssignChecker.objects.filter(
            assigned_checker_level_4=user
        )
        assigned_reports_as_checker_5 = AssignChecker.objects.filter(
            assigned_checker_level_5=user
        )
        assigned_reports_as_checker_6 = AssignChecker.objects.filter(
            assigned_checker_level_6=user
        )
        assigned_reports_as_head = AssignChecker.objects.filter(
            assigned_checker_level_7=user
        )

        checklists_as_checker_1 = GeneralChecklistUSer.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_1
            ],
            is_completed_by_doer=True,
        )
        checklists_as_checker_2 = GeneralChecklistUSer.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_2
            ],
            approved_by_checkers_level_1="True",
        )
        checklists_as_checker_3 = GeneralChecklistUSer.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_3
            ],
            approved_by_checkers_level_2="True",
        )
        checklists_as_checker_4 = GeneralChecklistUSer.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_4
            ],
            approved_by_checkers_level_3="True",
        )
        checklists_as_checker_5 = GeneralChecklistUSer.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_5
            ],
            approved_by_checkers_level_4="True",
        )
        checklists_as_checker_6 = GeneralChecklistUSer.objects.filter(
            user__in=[
                assigned_report.user
                for assigned_report in assigned_reports_as_checker_6
            ],
            approved_by_checkers_level_5="True",
        )
        checklists_as_head = GeneralChecklistUSer.objects.filter(
            user__in=[
                assigned_report.user for assigned_report in assigned_reports_as_head
            ],
            approved_by_checkers_level_6="True",
        )

        checklist = (
            checklists_as_checker_1
            | checklists_as_checker_2
            | checklists_as_checker_3
            | checklists_as_checker_4
            | checklists_as_checker_5
            | checklists_as_checker_6
            | checklists_as_head
        )
    else:
        # role == 'admin': the chain above binds nothing, so these
        # names were unbound and every admin request raised
        # UnboundLocalError. Read-only oversight.
        checklist = GeneralChecklistUSer.objects.all()
        view_sample = False

    if report_name in assignments.assigned_report or user.role == "company_checker":
        form = GeneralForm(user=request.user)
        table_headers = [
            "Sr. No.",
            "Product Name",
            "Status",
            "Action",
        ]
        return render(
            request,
            "RATools/baseShow.html",
            {
                "main_folder":"White Paper",
                "table_headers": table_headers,
                "form": form,
                "reports": checklist,
                "action": "../../ratools/add_general_checklist/",
                "edit_url": "/ratools/general_white_paper_report",
                "delete_url": "/ratools/delete_general_checklist",
                "modal_body_content": "White Paper..",
                "modal_title": "White Paper Overview",
                "page_heading": report_name,
                "view_sample":view_sample,
                "sample_url":"/ratools/view_general_white_paper_sample",
            },
        )
    else:
        context = {
            "show_flag": False,
            "heading": "General White Paper Report",
            "report_name": report_name,
        }
        return render(request, "RATools/WhitePaper/GeneralWhitePaper.html", context)

@login_required(login_url='/adminmaster/login/')
def add_general_checklist(request):
    if request.method == "POST":
        form = GeneralForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
        else:
            print(form.errors)
    return redirect("../../ratools/general_white_paper_table")

@login_required(login_url='/adminmaster/login/')
def delete_general_checklist(request, id):
    checklist = get_object_or_404(GeneralChecklistUSer, id=id)
    checklist.delete()
    return redirect("../../ratools/general_white_paper_table")

# def requestdemo(request):
#     return render(request,"requestdemo.html")



# def requestdemo(request):
#     if request.method == "POST":
#         full_name = request.POST.get("fullName")
#         email = request.POST.get("email")
#         country = request.POST.get("country")
#         phone = request.POST.get("phone")
#         company_name = request.POST.get("companyName")
#         company_domain = request.POST.get("companyDomain")
#         service = request.POST.get("service")
#         question = request.POST.get("question")

#         email_domain = email.split('@')[-1]

#         print("\n\n<>>>>>>email domain>>>",email_domain)
#         if email_domain != company_domain:
#             messages.error(request, "Email domain does not match the company domain.")
#         else:
#             DemoRequest.objects.create(
#                 full_name=full_name,
#                 email=email,
#                 country=country,
#                 phone=phone,
#                 company_name=company_name,
#                 company_domain=company_domain,
#                 service=service,
#                 question=question
#             )
#             messages.success(request, "Your request has been submitted successfully.")
#             return render(request, "HomePage.html")

#     return render(request,"requestdemo.html")


# def requestdemo(request):
#     if request.method == "POST":
#         full_name = request.POST.get("fullName")
#         email = request.POST.get("email")
#         country = request.POST.get("country")
#         phone = request.POST.get("phone")
#         company_name = request.POST.get("companyName")
#         company_domain = request.POST.get("companyDomain")
#         service = request.POST.get("service")
#         question = request.POST.get("question")

#         email_domain = email.split('@')[-1]

#         print("\n\n<>>>>>>email domain>>>",email_domain)
#         if email_domain != company_domain:
#             messages.error(request, "Email domain does not match the company domain.")
#         else:
#             demo_request = DemoRequest.objects.create(
#                 full_name=full_name,
#                 email=email,
#                 country=country,
#                 phone=phone,
#                 company_name=company_name,
#                 company_domain=company_domain,
#                 service=service,
#                 question=question
#             )

#             # Send email notification
#             email_subject = f"New Demo Request from {full_name}"
#             email_body = f"""
# New demo request details:

# Full Name: {full_name}
# Email: {email}
# Country: {country}
# Phone: {phone}
# Company Name: {company_name}
# Company Domain: {company_domain}
# Service Requested: {service}
# Question: {question}
#             """

#             send_mail(
#                 subject=email_subject,
#                 message=email_body,
#                 from_email=settings.DEFAULT_FROM_EMAIL,
#                 recipient_list=['inquiry@icretegy.com'],
#                 fail_silently=False,
#             )

#             return render(request, "requestdemo.html")

#     return render(request, "requestdemo.html")



def _booking_holidays_map():
    """{'YYYY-MM-DD': 'Display Name'} for every admin-added holiday —
    Public/Company/Team Leave all block bookings the same way, so the
    category doesn't matter for this lookup."""
    return {h.date.isoformat(): h.name for h in BookingHoliday.objects.all()}


def _is_working_day(d):
    """Mon-Fri always open. Sunday always off. Saturday open except the
    2nd and 4th Saturday of the month (matches the company's posted hours)."""
    weekday = d.weekday()  # Monday=0 ... Sunday=6
    if weekday == 6:
        return False
    if weekday == 5:
        saturday_of_month = (d.day - 1) // 7 + 1  # 1st..5th Saturday
        if saturday_of_month in (2, 4):
            return False
    return True


# Every country the visitor can pick in step 1, and the IANA timezone(s)
# that belong to it — used to populate the "Your Timezone" dropdown in
# step 2 (a country like the US or Russia spans several zones).
DEMO_BOOKING_COUNTRIES = sorted(
    ({"code": code, "name": name} for code, name in pytz.country_names.items()),
    key=lambda c: c["name"],
)
DEMO_BOOKING_COUNTRY_TIMEZONES = {
    code: list(zones) for code, zones in pytz.country_timezones.items()
}

# Free/personal email providers — rejected in favor of a company domain.
DEMO_BOOKING_PERSONAL_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com",
    "icloud.com", "aol.com", "protonmail.com", "proton.me", "rediffmail.com",
    "zoho.com", "gmx.com", "yandex.com", "mail.com", "msn.com", "me.com",
}

# Business hours the calendar offers slots within — 9 AM to 9 PM IST.
DEMO_BOOKING_DAY_START_MINUTES = 9 * 60
DEMO_BOOKING_DAY_END_MINUTES = 21 * 60


def _compute_day_slots(slot_date, exclude_id=None):
    """Everything needed to render/validate one day's slot grid, using the
    admin-configured meeting duration/buffer/interval (RATools.BookingSettings).

    exclude_id: a DemoRequest pk to leave out of the "already booked" check
    — pass the booking's own id when rescheduling, so its current slot
    doesn't block the very slots it's about to vacate.

    Returns (all_slots, blocked_slots, off_reason):
      all_slots      — every "HH:MM" slot start offered that day (interval-
                        spaced, each with enough room before close for a
                        full meeting).
      blocked_slots  — the subset of all_slots that can't be booked because
                        the candidate meeting [start, start + duration) would
                        run into an existing booking's reserved block
                        [start, start + duration + buffer) — the buffer is
                        trailing-only, so a meeting may end exactly when a
                        booked one begins, but nothing may start during the
                        gap that follows one. Also blocked by any real Outlook
                        busy/leave/OOO interval for the internal team.
      off_reason     — set (and both lists empty) if slot_date is a holiday
                        or a non-working day (Sunday, or the 2nd/4th Saturday).
    """
    holiday_name = _booking_holidays_map().get(slot_date.isoformat())
    if holiday_name:
        return [], [], holiday_name

    if not _is_working_day(slot_date):
        weekday = slot_date.weekday()
        if weekday == 6:
            return [], [], "Weekly Off (Sunday)"
        saturday_of_month = (slot_date.day - 1) // 7 + 1
        return [], [], f"Non-working Saturday ({saturday_of_month}{'nd' if saturday_of_month == 2 else 'th'} Saturday)"

    cfg = BookingSettings.load()
    duration = cfg.meeting_duration_minutes
    buffer_ = cfg.buffer_minutes
    interval = cfg.slot_interval_minutes

    all_slots = []
    m = DEMO_BOOKING_DAY_START_MINUTES
    while m + duration <= DEMO_BOOKING_DAY_END_MINUTES:
        all_slots.append(m)
        m += interval

    booked_qs = DemoRequest.objects.filter(slot_date=slot_date, status="confirmed").exclude(slot_time__isnull=True)
    if exclude_id:
        booked_qs = booked_qs.exclude(pk=exclude_id)
    booked_starts = [t.hour * 60 + t.minute for t in booked_qs.values_list("slot_time", flat=True)]

    # Fold in the internal team's real Outlook busy/leave/OOO time, if
    # configured — fails open (empty list) if Graph isn't set up yet.
    team_emails = cfg.internal_team_email_list()
    busy_starts_minutes = []
    if team_emails:
        ist = py_timezone(timedelta(hours=5, minutes=30))
        day_start_utc = datetime.combine(slot_date, datetime.min.time(), tzinfo=ist).astimezone(py_timezone.utc)
        day_end_utc = day_start_utc + timedelta(days=1)
        for busy_start, busy_end in get_busy_intervals(team_emails, day_start_utc, day_end_utc):
            busy_start_ist = busy_start.astimezone(ist)
            busy_end_ist = busy_end.astimezone(ist)
            if busy_start_ist.date() == slot_date:
                busy_starts_minutes.append((
                    busy_start_ist.hour * 60 + busy_start_ist.minute,
                    busy_end_ist.hour * 60 + busy_end_ist.minute,
                ))

    def blocked(candidate):
        for b in booked_starts:
            # Buffer is trailing-only: a booking reserves [start, start+duration+buffer),
            # while the candidate only occupies its own meeting [start, start+duration).
            # So a slot may end exactly when a booked one starts (no wasted time before
            # a booking), but nothing may begin inside the gap that follows one.
            if candidate < b + duration + buffer_ and b < candidate + duration:
                return True
        for busy_start, busy_end in busy_starts_minutes:
            if candidate < busy_end and busy_start < candidate + duration:
                return True
        return False

    blocked_slots = [m for m in all_slots if blocked(m)]

    def fmt(total_minutes):
        return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"

    return [fmt(m) for m in all_slots], [fmt(m) for m in blocked_slots], None


# ── Booking confirmation / notification emails ──────────────────────────
# Sent via Microsoft Graph (RATools/graph_email.py) with an inline logo and
# an .ics attachment, only for requests that picked a calendar slot. Plain
# inquiries (no slot) keep using the simple SMTP send_mail() below.

_LOGO_DIR = os.path.join(settings.BASE_DIR, "static", "img")
_LOGO_CID = {"blue": "ipharmaai-logo-blue", "white": "ipharmaai-logo-white"}
_logo_bytes_cache = {}


def _logo_bytes(variant):
    if variant not in _logo_bytes_cache:
        with open(os.path.join(_LOGO_DIR, f"ipharmaai-logo-{variant}.png"), "rb") as f:
            _logo_bytes_cache[variant] = f.read()
    return _logo_bytes_cache[variant]


def _logo_inline_image(variant):
    return {
        "cid": _LOGO_CID[variant],
        "name": f"ipharmaai-logo-{variant}.png",
        "content_type": "image/png",
        "content_bytes": _logo_bytes(variant),
    }


def _logo_html(dark_bg=False):
    variant = "white" if dark_bg else "blue"
    cid = _LOGO_CID[variant]
    return f'<img src="cid:{cid}" alt="iPharmaAI" height="42" style="height:42px;width:auto;display:block;margin:0 auto;border:0;">'


def _detail_row(label, value):
    if not value:
        return ""
    return (
        "<tr>"
        f'<td width="170" valign="top" style="width:170px;padding:11px 14px 11px 0;border-bottom:1px solid #e8edf1;color:#6b7280;font-size:14px;line-height:20px;">{escape(label)}</td>'
        f'<td valign="top" style="padding:11px 0;border-bottom:1px solid #e8edf1;color:#111827;font-size:14px;line-height:20px;font-weight:600;">{escape(str(value))}</td>'
        "</tr>"
    )


def _confirmation_html(*, first_name, attendee_name, date_label, time_label, meeting_url, service, question, duration_minutes=30, manage_url=None, tz_abbr="IST"):
    safe_first_name = escape(first_name)
    safe_date = escape(date_label)
    safe_time = escape(time_label)
    safe_meeting_url = escape(meeting_url, quote=True)
    safe_manage_url = escape(manage_url, quote=True) if manage_url else None
    service_row = _detail_row("Service Type", service)
    question_block = (
        f'<p style="margin:16px 0 0;color:#3e4c59;line-height:1.6;"><strong>Question:</strong> {escape(question)}</p>'
        if question else ""
    )
    return f'''<!DOCTYPE html>
<html>
<head>
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
</head>
<body style="margin:0;padding:0;background-color:#f4f6f8;font-family:Arial,Helvetica,sans-serif;color:#152536;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="width:100%;background-color:#f4f6f8;border-collapse:collapse;">
    <tr>
      <td align="center" style="padding:24px 12px;">
        <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="width:100%;max-width:640px;background-color:#ffffff;border:1px solid #dfe5ea;border-collapse:separate;border-spacing:0;border-radius:8px;overflow:hidden;">
          <tr>
            <td align="center" style="background-color:#ffffff;padding:32px 24px 28px;border-bottom:1px solid #dfe5ea;">
              {_logo_html()}
              <p style="margin:14px 0 0;color:#6b7280;font-size:14px;line-height:20px;">Consultation Confirmed &#10003;</p>
            </td>
          </tr>
          <tr>
            <td style="padding:36px 32px 32px;background-color:#ffffff;">
              <p style="margin:0 0 24px;color:#34495e;font-size:16px;line-height:24px;">Hi {safe_first_name}, your demo is scheduled. Here's what you need to know:</p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#e8f6fd;border-left:6px solid #0e6787;border-radius:8px;border-collapse:separate;margin:0 0 26px;">
                <tr>
                  <td width="58" valign="top" style="padding:24px 0 24px 24px;">
                    <table role="presentation" width="42" height="42" cellspacing="0" cellpadding="0" style="background-color:#0e6787;border-radius:21px;">
                      <tr><td align="center" valign="middle" style="color:#ffffff;font-size:18px;line-height:42px;">&#9638;</td></tr>
                    </table>
                  </td>
                  <td valign="top" style="padding:24px 24px 24px 14px;">
                    <p style="margin:0 0 8px;color:#005c83;font-size:12px;line-height:16px;font-weight:700;text-transform:uppercase;letter-spacing:.3px;">Meeting Scheduled</p>
                    <p style="margin:0;color:#005c83;font-size:20px;line-height:28px;font-weight:700;">{safe_date} at {safe_time}</p>
                    <p style="margin:16px 0 0;color:#3e4c59;font-size:14px;line-height:20px;">Duration: {duration_minutes} minutes &bull; Timezone: {escape(tz_abbr)}</p>
                  </td>
                </tr>
              </table>
              <table role="presentation" align="center" cellspacing="0" cellpadding="0" style="margin:0 auto 30px;border-collapse:collapse;">
                <tr>
                  <td align="center" style="padding:0 6px 10px;">
                    <a href="{safe_meeting_url}" style="display:inline-block;min-width:130px;background-color:#0e6787;color:#ffffff;text-decoration:none;font-size:14px;line-height:20px;font-weight:700;padding:14px 24px;border-radius:5px;">Join Meeting</a>
                  </td>
                  <td align="center" style="padding:0 6px 10px;">
                    <a href="{safe_meeting_url}" style="display:inline-block;min-width:130px;background-color:#ffffff;color:#005c83;text-decoration:none;font-size:14px;line-height:20px;font-weight:700;padding:13px 24px;border:1px solid #cfd8df;border-radius:5px;">Add to Calendar</a>
                  </td>
                </tr>
              </table>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;margin:0 0 24px;">{service_row}</table>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#f5f7f9;border-collapse:separate;border-radius:6px;margin:0 0 26px;">
                <tr>
                  <td style="padding:18px 20px;">
                    <p style="margin:0 0 10px;color:#0c1b26;font-size:13px;line-height:18px;font-weight:700;text-transform:uppercase;">Need to reschedule or cancel?</p>
                    <p style="margin:0;color:#3e4c59;font-size:14px;line-height:21px;">Calendar invite is attached. {"<a href='" + safe_manage_url + "' style='color:#0e6787;font-weight:700;text-decoration:underline;'>Manage your booking</a> to pick a new time or cancel." if safe_manage_url else "Simply reply to this email."}</p>
                  </td>
                </tr>
              </table>
              {question_block}
              <p style="margin:24px 0 0;color:#34495e;font-size:14px;line-height:22px;">Questions before the call? Don't hesitate to reach out to us. We're here to help.</p>
              <p style="margin:8px 0 0;color:#111827;font-size:14px;line-height:20px;font-weight:700;">&mdash; iPharmaAI Team</p>
            </td>
          </tr>
          <tr>
            <td align="center" style="background-color:#f7f9fb;padding:18px;color:#8a949e;font-size:12px;line-height:18px;border-top:1px solid #dfe5ea;">&copy; 2026 iPharmaAI &bull; <a href="#" style="color:#005c83;text-decoration:none;">Preferences</a> &bull; <a href="#" style="color:#005c83;text-decoration:none;">Unsubscribe</a></td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>'''.strip()


def _notify_html(*, attendee_name, email, phone, country, company, company_domain, service, question, date_label, time_label, meeting_url, duration_minutes=30):
    attendee_rows = "".join([
        _detail_row("Full Name", attendee_name),
        _detail_row("Email", email),
        _detail_row("Phone", phone),
        _detail_row("Organization", company),
        _detail_row("Country", country),
        _detail_row("Company Domain", company_domain),
    ])
    session_rows = "".join([
        _detail_row("Service Type", service or "General Product Demo"),
        _detail_row("Duration", f"{duration_minutes} minutes"),
        _detail_row("Scheduled Date", date_label),
        _detail_row("Time (IST)", time_label),
        _detail_row("Teams Link", meeting_url),
        _detail_row("Question", question),
    ])
    safe_attendee_name = escape(attendee_name)
    safe_meeting_url = escape(meeting_url, quote=True)
    return f'''<!DOCTYPE html>
<html>
<head>
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
</head>
<body style="margin:0;padding:0;background-color:#f4f6f8;font-family:Arial,Helvetica,sans-serif;color:#111827;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="width:100%;background-color:#f4f6f8;border-collapse:collapse;">
    <tr>
      <td align="center" style="padding:24px 12px;">
        <table role="presentation" width="760" cellspacing="0" cellpadding="0" style="width:100%;max-width:760px;background-color:#ffffff;border:1px solid #dfe5ea;border-collapse:separate;border-spacing:0;overflow:hidden;">
          <tr>
            <td align="center" style="background-color:#125f7a;padding:36px 24px 34px;color:#ffffff;">
              <div style="margin:0 0 14px;">{_logo_html(dark_bg=True)}</div>
              <p style="margin:0;font-size:13px;line-height:18px;letter-spacing:.5px;text-transform:uppercase;color:#ffffff;">New Consultation Booking</p>
            </td>
          </tr>
          <tr>
            <td style="padding:34px 34px 10px;background-color:#ffffff;">
              <p style="margin:0 0 24px;font-size:16px;line-height:24px;color:#111827;">Hi Team,</p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#e8f6fd;border-left:5px solid #125f7a;border-collapse:separate;margin:0 0 28px;">
                <tr>
                  <td style="padding:20px 22px;">
                    <p style="margin:0 0 5px;color:#005c83;font-size:16px;line-height:22px;font-weight:700;">&#10003; New booking received</p>
                    <p style="margin:0;color:#334155;font-size:14px;line-height:21px;">{safe_attendee_name} has scheduled a product demonstration</p>
                  </td>
                </tr>
              </table>
              <h2 style="margin:0 0 14px;color:#005c83;font-size:14px;line-height:20px;letter-spacing:.8px;text-transform:uppercase;">Attendee Information</h2>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;margin:0 0 32px;">{attendee_rows}</table>
              <h2 style="margin:0 0 14px;color:#005c83;font-size:14px;line-height:20px;letter-spacing:.8px;text-transform:uppercase;">Session Details</h2>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;margin:0 0 34px;">{session_rows}</table>
              <table role="presentation" align="center" cellspacing="0" cellpadding="0" style="margin:0 auto 36px;border-collapse:collapse;">
                <tr>
                  <td align="center">
                    <a href="{safe_meeting_url}" style="display:inline-block;background-color:#125f7a;color:#ffffff;text-decoration:none;font-size:14px;line-height:20px;font-weight:700;padding:13px 30px;border-radius:4px;">View Full Booking Details</a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td align="center" style="background-color:#f5f7f9;padding:24px;color:#8a949e;font-size:12px;line-height:18px;border-top:1px solid #dfe5ea;">&copy; 2026 iPharmaAI. All rights reserved.<br><a href="#" style="color:#005c83;text-decoration:none;">Preferences</a> | <a href="#" style="color:#005c83;text-decoration:none;">Unsubscribe</a></td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>'''.strip()


def _format_slot_date_label(d):
    # "Thursday, August 20, 2026"
    return f"{d.strftime('%A, %B')} {d.day}, {d.year}"


def _format_slot_time_label(t):
    # "9:00 AM"
    hour12 = t.hour % 12 or 12
    period = "AM" if t.hour < 12 else "PM"
    return f"{hour12}:{t.minute:02d} {period}"


def _format_slot_range_label(start, duration_minutes):
    # "9:00 AM - 9:30 AM" — the call itself, worded exactly like the slot
    # the visitor clicked in the booking widget.
    end = start + timedelta(minutes=duration_minutes)
    return f"{_format_slot_time_label(start)} - {_format_slot_time_label(end)}"


def _slot_email_labels(slot_date, slot_time, duration_minutes, tz_name=None):
    """(date_label, time_label, tz_abbr) for a booked slot.

    The slot is stored as IST wall-clock. Pass tz_name (the visitor's IANA
    zone, e.g. "America/New_York") to render the same instant in their
    timezone — the booker's email shows the slot exactly as the widget
    offered it to them, while the team's email stays in IST. Falls back to
    IST if the zone is missing or unrecognised. The date is formatted after
    conversion, so a slot that lands on the previous day abroad reads
    correctly.
    """
    ist = py_timezone(timedelta(hours=5, minutes=30))
    start = datetime.combine(slot_date, slot_time, tzinfo=ist)
    tz_abbr = "IST"

    if tz_name and tz_name != "Asia/Kolkata":
        try:
            start = start.astimezone(pytz.timezone(tz_name))
            tz_abbr = start.strftime("%Z") or tz_name
        except Exception:
            start = datetime.combine(slot_date, slot_time, tzinfo=ist)
            tz_abbr = "IST"

    return (
        _format_slot_date_label(start),
        _format_slot_range_label(start, duration_minutes),
        tz_abbr,
    )


@require_http_methods(["GET"])
def requestdemo_preview_email(request, kind):
    """Dev-only: render the confirmation/notify email HTML in the browser
    (cid: swapped for static URLs) without sending anything."""
    if not settings.DEBUG:
        raise Http404()

    sample = {
        "attendee_name": "Dev Patel",
        "first_name": "Dev",
        "email": "dev.patel@example.com",
        "phone": "+91-1234567890",
        "country": "india",
        "company": "Praverse",
        "company_domain": "example.com",
        "service": "AuditIQ",
        "question": "I would like to understand how iPharma AI can support our regulatory team.",
        "date_label": "Thursday, August 20, 2026",
        "time_label": "9:00 AM - 9:30 AM",
        "meeting_url": "https://teams.microsoft.com/l/meetup-join/sample-teams-meeting-link",
    }

    if kind == "user":
        html = _confirmation_html(
            first_name=sample["first_name"],
            attendee_name=sample["attendee_name"],
            date_label=sample["date_label"],
            time_label=sample["time_label"],
            meeting_url=sample["meeting_url"],
            service=sample["service"],
            question=sample["question"],
        )
    elif kind == "team":
        html = _notify_html(
            attendee_name=sample["attendee_name"],
            email=sample["email"],
            phone=sample["phone"],
            country=sample["country"],
            company=sample["company"],
            company_domain=sample["company_domain"],
            service=sample["service"],
            question=sample["question"],
            date_label=sample["date_label"],
            time_label=sample["time_label"],
            meeting_url=sample["meeting_url"],
        )
    else:
        raise Http404()

    # cid: references only resolve inside an actual email client once the
    # image is attached — swap in static URLs so this renders in a browser.
    html = html.replace(
        f'cid:{_LOGO_CID["blue"]}', request.build_absolute_uri('/static/img/ipharmaai-logo-blue.png')
    ).replace(
        f'cid:{_LOGO_CID["white"]}', request.build_absolute_uri('/static/img/ipharmaai-logo-white.png')
    )

    return HttpResponse(html)


def contactus(request):
    """Plain "Contact Us" — deliberately a different, lighter form than
    /requestdemo: no calendar, no timezone, no service picker. Just a
    name/email/company/message, saved as ContactMessage."""
    context = {}

    if request.method == "POST":
        full_name = (request.POST.get("fullName") or "").strip()
        email = (request.POST.get("email") or "").strip()
        company_name = (request.POST.get("companyName") or "").strip()
        message = (request.POST.get("message") or "").strip()

        if not full_name or not email or not message:
            context["error_message"] = "Please fill in your name, email, and message."
            context["form_data"] = request.POST
            return render(request, "contactus.html", context)

        email_domain = email.split("@")[-1].lower() if "@" in email else ""
        if not email_domain or "." not in email_domain:
            context["error_message"] = "Please enter a valid email address."
            context["form_data"] = request.POST
            return render(request, "contactus.html", context)

        ContactMessage.objects.create(
            full_name=full_name,
            email=email,
            company_name=company_name,
            message=message,
        )

        email_subject = f"New Contact Us message from {full_name}"
        email_body = f"""
New contact message:

Full Name: {full_name}
Email: {email}
Company: {company_name or '—'}

Message:
{message}
        """
        try:
            send_mail(
                subject=email_subject,
                message=email_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[settings.BOOKING_HOST_EMAIL],
                fail_silently=False,
            )
        except Exception as err:
            # The message is already saved — don't fail the request just
            # because the internal notification couldn't send.
            print(f"[contactus] notification email failed: {err}")

        context["success_message"] = "Thanks for reaching out! We'll get back to you shortly."
        return render(request, "contactus.html", context)

    return render(request, "contactus.html", context)


def requestdemo(request):
    booking_cfg = BookingSettings.load()
    context = {
        # The calendar widget needs the full holiday list up front so it can
        # grey out those dates without a round trip per date.
        "holidays_json": json.dumps(_booking_holidays_map()),
        "countries": DEMO_BOOKING_COUNTRIES,
        "countries_json": json.dumps(DEMO_BOOKING_COUNTRIES),
        "country_timezones_json": json.dumps(DEMO_BOOKING_COUNTRY_TIMEZONES),
        "meeting_duration_minutes": booking_cfg.meeting_duration_minutes,
    }

    if request.method == "POST":
        first_name = (request.POST.get("firstName") or "").strip()
        last_name = (request.POST.get("lastName") or "").strip()
        job_title = (request.POST.get("jobTitle") or "").strip()
        full_name = f"{first_name} {last_name}".strip()
        email = request.POST.get("email")
        country = request.POST.get("country")
        visitor_timezone = request.POST.get("timezone") or ""
        phone = request.POST.get("phone")
        company_name = request.POST.get("companyName")
        company_domain = request.POST.get("companyDomain")
        service = request.POST.get("service")
        question = request.POST.get("question")
        preferred_date = request.POST.get("preferredDate")
        preferred_time = request.POST.get("preferredTime")

        email_domain = email.split('@')[-1].lower()

        # Reject free/personal email providers before the domain-match check
        # — matching a personal domain to itself would otherwise pass.
        if email_domain in DEMO_BOOKING_PERSONAL_EMAIL_DOMAINS:
            context["error_message"] = "Please use your company email address, not a personal email provider (e.g. Gmail, Yahoo)."
            context["form_data"] = request.POST
            return render(request, "requestdemo.html", context)

        # If email domain does not match company domain, add error message
        if email_domain != (company_domain or "").lower():
            context["error_message"] = "Email domain does not match the company domain."
            context["form_data"] = request.POST  # Preserve form data
            return render(request, "requestdemo.html", context)

        slot_date = None
        slot_time = None
        if preferred_date and preferred_time:
            try:
                slot_date = datetime.strptime(preferred_date, "%Y-%m-%d").date()
                slot_time = datetime.strptime(preferred_time, "%H:%M").time()
            except ValueError:
                slot_date = None
                slot_time = None

            if slot_date and slot_time:
                # Re-check right before saving — someone else may have grabbed
                # this slot (or booked one too close to it, inside the
                # configured buffer) between the visitor loading the
                # calendar and hitting confirm.
                all_slots, blocked_slots, off_reason = _compute_day_slots(slot_date)
                if off_reason:
                    context["error_message"] = f"Sorry, {slot_date.strftime('%B %d, %Y')} is unavailable ({off_reason}) — no bookings that day. Please pick another date."
                    context["slot_conflict"] = True
                    context["form_data"] = request.POST
                    return render(request, "requestdemo.html", context)

                if preferred_time in blocked_slots:
                    context["error_message"] = "Sorry, that slot was just booked by someone else. Please pick another time."
                    context["slot_conflict"] = True
                    context["form_data"] = request.POST
                    return render(request, "requestdemo.html", context)

        # Save the request if there are no errors
        try:
            demo_request = DemoRequest.objects.create(
                first_name=first_name,
                last_name=last_name,
                job_title=job_title,
                full_name=full_name,
                email=email,
                country=country,
                timezone=visitor_timezone,
                phone=phone,
                company_name=company_name,
                company_domain=company_domain,
                service=service,
                question=question,
                slot_date=slot_date,
                slot_time=slot_time,
            )
        except IntegrityError:
            # Lost the race against a concurrent booking for the same slot.
            context["error_message"] = "Sorry, that slot was just booked by someone else. Please pick another time."
            context["slot_conflict"] = True
            context["form_data"] = request.POST
            return render(request, "requestdemo.html", context)

        if slot_date and slot_time:
            # Scheduled booking — send the rich HTML confirmation (to the
            # visitor) and notification (to the team) via Microsoft Graph,
            # with the meeting invite attached as .ics.
            cfg = BookingSettings.load()
            ist = py_timezone(timedelta(hours=5, minutes=30))
            start_dt = datetime.combine(slot_date, slot_time, tzinfo=ist).astimezone(py_timezone.utc)
            duration_minutes = cfg.meeting_duration_minutes
            end_dt = start_dt + timedelta(minutes=duration_minutes)
            # The booker reads the slot in their own timezone (exactly what the
            # widget showed them); the team always reads it in IST.
            user_date_label, user_time_label, user_tz_abbr = _slot_email_labels(
                slot_date, slot_time, duration_minutes, tz_name=visitor_timezone
            )
            date_label, time_label, _ = _slot_email_labels(slot_date, slot_time, duration_minutes)
            user_subject = f"Appointment booked: iPharmaAI Demo ({full_name}) @ {user_date_label} {user_time_label} {user_tz_abbr}"
            team_subject = f"Appointment booked: iPharmaAI Demo ({full_name}) @ {date_label} {time_label} IST"
            manage_url = request.build_absolute_uri(
                reverse("requestdemo_manage", args=[demo_request.manage_token])
            )

            try:
                event = create_calendar_event(
                    subject=f"iPharmaAI Demo - {full_name}",
                    start_dt=start_dt,
                    end_dt=end_dt,
                    attendee_email=email,
                    attendee_name=full_name,
                    internal_attendee_emails=cfg.internal_team_email_list(),
                    body_html=f"iPharmaAI product demo with {full_name} ({company_name}). Manage: {manage_url}",
                )
                meeting_url = event["join_url"]
                demo_request.graph_event_id = event["event_id"] or ""
                demo_request.save(update_fields=["graph_event_id"])

                ics_content = build_ics(IcsInput(
                    uid=f"ipharmaai-demo-{demo_request.id}@icretegy.com",
                    start=start_dt,
                    end=end_dt,
                    summary=f"iPharmaAI Demo - {full_name}",
                    description=f"{duration_minutes}-minute iPharmaAI product walkthrough.\nJoin video call: {meeting_url}",
                    location=meeting_url,
                    organizer_email=settings.BOOKING_HOST_EMAIL,
                    attendee_email=email,
                    attendee_name=full_name,
                ))

                confirmation_html = _confirmation_html(
                    first_name=first_name or full_name,
                    attendee_name=full_name,
                    date_label=user_date_label,
                    time_label=user_time_label,
                    meeting_url=meeting_url,
                    service=service,
                    question=question,
                    duration_minutes=duration_minutes,
                    manage_url=manage_url,
                    tz_abbr=user_tz_abbr,
                )
                notify_html = _notify_html(
                    attendee_name=full_name,
                    email=email,
                    phone=phone,
                    country=country,
                    company=company_name,
                    company_domain=company_domain,
                    service=service,
                    question=question,
                    date_label=date_label,
                    time_label=time_label,
                    meeting_url=meeting_url,
                    duration_minutes=duration_minutes,
                )

                send_graph_email(
                    to_email=email,
                    to_name=full_name,
                    subject=user_subject,
                    html=confirmation_html,
                    ics_content=ics_content,
                    inline_images=[_logo_inline_image("blue")],
                )
                send_graph_email(
                    to_email=settings.BOOKING_HOST_EMAIL,
                    to_name="iPharmaAI Team",
                    subject=team_subject,
                    html=notify_html,
                    ics_content=ics_content,
                    inline_images=[_logo_inline_image("white")],
                )
            except (GraphNotConfigured, Exception) as err:
                # The booking itself already succeeded (DemoRequest is
                # saved) — don't fail the whole request just because the
                # confirmation email couldn't go out. Log for follow-up.
                print(f"[requestdemo] booking email send failed: {err}")
        else:
            # Plain inquiry (no calendar slot picked) — keep the original
            # simple internal notification.
            email_subject = f"New Demo Request from {full_name}"
            email_body = f"""
New demo request details:

Full Name: {full_name}
Job Title: {job_title}
Email: {email}
Country: {country}
Phone: {phone}
Company Name: {company_name}
Company Domain: {company_domain}
Service Requested: {service}
Question: {question}
        """
            send_mail(
                subject=email_subject,
                message=email_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[settings.BOOKING_HOST_EMAIL],
                fail_silently=False,
            )

        context["success_message"] = "Your demo request has been submitted successfully!"
        return render(request, "requestdemo.html", context)

    return render(request, "requestdemo.html", context)


def requestdemo_availability(request):
    date_param = request.GET.get("date", "")
    try:
        slot_date = datetime.strptime(date_param, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"error": "Invalid date param. Use YYYY-MM-DD."}, status=400)

    all_slots, blocked_slots, off_reason = _compute_day_slots(slot_date)
    if off_reason:
        return JsonResponse({"slots": [], "bookedSlots": [], "holiday": True, "holidayName": off_reason})

    cfg = BookingSettings.load()
    return JsonResponse({
        "slots": all_slots,
        "bookedSlots": blocked_slots,
        "durationMinutes": cfg.meeting_duration_minutes,
        "bufferMinutes": cfg.buffer_minutes,
        "intervalMinutes": cfg.slot_interval_minutes,
    })


# ── Reschedule / cancel ("manage your booking") ──────────────────────────

def _slot_start_utc(slot_date, slot_time):
    ist = py_timezone(timedelta(hours=5, minutes=30))
    return datetime.combine(slot_date, slot_time, tzinfo=ist).astimezone(py_timezone.utc)


def _status_update_html(*, first_name, headline, message, date_label=None, time_label=None, meeting_url=None, tz_abbr="IST"):
    """Shared shell for the cancellation/reschedule notice emails — same
    card as the main confirmation, minus the fields that don't apply."""
    safe_first_name = escape(first_name)
    detail_block = ""
    if date_label and time_label:
        detail_block = f'''
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#e8f6fd;border-left:6px solid #0e6787;border-radius:8px;border-collapse:separate;margin:0 0 26px;">
          <tr><td style="padding:20px 24px;">
            <p style="margin:0;color:#005c83;font-size:18px;font-weight:700;">{escape(date_label)} at {escape(time_label)} {escape(tz_abbr)}</p>
          </td></tr>
        </table>'''
    cta = ""
    if meeting_url:
        safe_url = escape(meeting_url, quote=True)
        cta = f'''
        <table role="presentation" align="center" cellspacing="0" cellpadding="0" style="margin:0 auto 30px;border-collapse:collapse;">
          <tr><td align="center"><a href="{safe_url}" style="display:inline-block;background-color:#0e6787;color:#ffffff;text-decoration:none;font-size:14px;font-weight:700;padding:14px 24px;border-radius:5px;">Join Meeting</a></td></tr>
        </table>'''
    return f'''<!DOCTYPE html>
<html>
<head>
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
</head>
<body style="margin:0;padding:0;background-color:#f4f6f8;font-family:Arial,Helvetica,sans-serif;color:#152536;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="width:100%;background-color:#f4f6f8;border-collapse:collapse;">
    <tr>
      <td align="center" style="padding:24px 12px;">
        <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="width:100%;max-width:640px;background-color:#ffffff;border:1px solid #dfe5ea;border-collapse:separate;border-spacing:0;border-radius:8px;overflow:hidden;">
          <tr>
            <td align="center" style="background-color:#ffffff;padding:32px 24px 28px;border-bottom:1px solid #dfe5ea;">
              {_logo_html()}
              <p style="margin:14px 0 0;color:#6b7280;font-size:14px;line-height:20px;">{escape(headline)}</p>
            </td>
          </tr>
          <tr>
            <td style="padding:36px 32px 32px;background-color:#ffffff;">
              <p style="margin:0 0 24px;color:#34495e;font-size:16px;line-height:24px;">Hi {safe_first_name}, {escape(message)}</p>
              {detail_block}
              {cta}
              <p style="margin:24px 0 0;color:#34495e;font-size:14px;line-height:22px;">Questions? Don't hesitate to reach out to us.</p>
              <p style="margin:8px 0 0;color:#111827;font-size:14px;line-height:20px;font-weight:700;">&mdash; iPharmaAI Team</p>
            </td>
          </tr>
          <tr>
            <td align="center" style="background-color:#f7f9fb;padding:18px;color:#8a949e;font-size:12px;line-height:18px;border-top:1px solid #dfe5ea;">&copy; 2026 iPharmaAI</td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>'''.strip()


def _manage_context(demo_request):
    cfg = BookingSettings.load()
    now_utc = datetime.now(py_timezone.utc)
    context = {
        "booking": demo_request,
        "max_reschedules": cfg.max_reschedules,
        "cutoff_hours": cfg.reschedule_cutoff_hours,
        "past_cutoff": True,
        "hours_until": None,
    }
    if demo_request.slot_date and demo_request.slot_time:
        start_utc = _slot_start_utc(demo_request.slot_date, demo_request.slot_time)
        hours_until = (start_utc - now_utc).total_seconds() / 3600
        context["hours_until"] = round(hours_until, 1)
        context["past_cutoff"] = hours_until < cfg.reschedule_cutoff_hours
    return context


@require_http_methods(["GET"])
def requestdemo_manage(request, token):
    demo_request = get_object_or_404(DemoRequest, manage_token=token)
    context = _manage_context(demo_request)
    context["message"] = request.GET.get("msg", "")
    return render(request, "requestdemo_manage.html", context)


@require_http_methods(["POST"])
def requestdemo_manage_cancel(request, token):
    demo_request = get_object_or_404(DemoRequest, manage_token=token)

    if demo_request.status != "confirmed":
        return redirect(reverse("requestdemo_manage", args=[token]) + "?msg=already-cancelled")

    ctx = _manage_context(demo_request)
    if ctx["past_cutoff"]:
        return redirect(reverse("requestdemo_manage", args=[token]) + "?msg=cutoff")

    demo_request.status = "cancelled"
    demo_request.save(update_fields=["status"])
    cancel_calendar_event(demo_request.graph_event_id)

    try:
        cancel_html = _status_update_html(
            first_name=demo_request.first_name or demo_request.full_name,
            headline="Booking Cancelled",
            message="your upcoming demo has been cancelled as requested. The slot is now free — book a new time whenever you're ready.",
        )
        send_graph_email(
            to_email=demo_request.email, to_name=demo_request.full_name,
            subject=f"Cancelled: iPharmaAI Demo ({demo_request.full_name})",
            html=cancel_html, inline_images=[_logo_inline_image("blue")],
        )
        send_graph_email(
            to_email=settings.BOOKING_HOST_EMAIL, to_name="iPharmaAI Team",
            subject=f"Cancelled: iPharmaAI Demo ({demo_request.full_name})",
            html=_status_update_html(
                first_name="Team",
                headline="Booking Cancelled",
                message=f"{demo_request.full_name} ({demo_request.company_name}) cancelled their demo.",
            ),
            inline_images=[_logo_inline_image("white")],
        )
    except (GraphNotConfigured, Exception) as err:
        print(f"[requestdemo_manage_cancel] email send failed: {err}")

    return redirect(reverse("requestdemo_manage", args=[token]) + "?msg=cancelled")


@require_http_methods(["GET", "POST"])
def requestdemo_manage_reschedule(request, token):
    demo_request = get_object_or_404(DemoRequest, manage_token=token)
    ctx = _manage_context(demo_request)

    if demo_request.status != "confirmed":
        return redirect(reverse("requestdemo_manage", args=[token]) + "?msg=already-cancelled")
    if ctx["past_cutoff"]:
        return redirect(reverse("requestdemo_manage", args=[token]) + "?msg=cutoff")
    if demo_request.reschedule_count >= ctx["max_reschedules"]:
        return redirect(reverse("requestdemo_manage", args=[token]) + "?msg=max-reschedules")

    if request.method == "GET":
        ctx["error_message"] = request.GET.get("error", "")
        return render(request, "requestdemo_reschedule.html", ctx)

    new_date_str = request.POST.get("newDate")
    new_time_str = request.POST.get("newTime")
    try:
        new_date = datetime.strptime(new_date_str, "%Y-%m-%d").date()
        new_time = datetime.strptime(new_time_str, "%H:%M").time()
    except (ValueError, TypeError):
        return redirect(reverse("requestdemo_manage_reschedule", args=[token]) + "?error=Please+pick+a+valid+date+and+time.")

    all_slots, blocked_slots, off_reason = _compute_day_slots(new_date, exclude_id=demo_request.id)
    if off_reason or new_time_str not in all_slots or new_time_str in blocked_slots:
        return redirect(reverse("requestdemo_manage_reschedule", args=[token]) + "?error=That+time+is+no+longer+available.+Please+pick+another.")

    cfg = BookingSettings.load()
    old_date, old_time = demo_request.slot_date, demo_request.slot_time
    demo_request.slot_date = new_date
    demo_request.slot_time = new_time
    demo_request.reschedule_count += 1
    demo_request.ics_sequence += 1
    try:
        demo_request.save()
    except IntegrityError:
        demo_request.slot_date, demo_request.slot_time = old_date, old_time
        return redirect(reverse("requestdemo_manage_reschedule", args=[token]) + "?error=That+time+was+just+taken.+Please+pick+another.")

    start_dt = _slot_start_utc(new_date, new_time)
    duration_minutes = cfg.meeting_duration_minutes
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    # Booker reads the new slot in their own timezone; the team reads IST.
    user_date_label, user_time_label, user_tz_abbr = _slot_email_labels(
        new_date, new_time, duration_minutes, tz_name=demo_request.timezone
    )
    date_label, time_label, _ = _slot_email_labels(new_date, new_time, duration_minutes)
    update_calendar_event(demo_request.graph_event_id, start_dt=start_dt, end_dt=end_dt)

    manage_url = request.build_absolute_uri(reverse("requestdemo_manage", args=[token]))
    try:
        meeting_url = "https://ipharmaai.com/ratools/requestdemo"
        ics_content = build_ics(IcsInput(
            uid=f"ipharmaai-demo-{demo_request.id}@icretegy.com",
            start=start_dt, end=end_dt,
            summary=f"iPharmaAI Demo - {demo_request.full_name}",
            description=f"{duration_minutes}-minute iPharmaAI product walkthrough (rescheduled).",
            location=meeting_url,
            organizer_email=settings.BOOKING_HOST_EMAIL,
            attendee_email=demo_request.email,
            attendee_name=demo_request.full_name,
        ))
        confirmation_html = _status_update_html(
            first_name=demo_request.first_name or demo_request.full_name,
            headline="Booking Rescheduled",
            message="your demo has been moved to a new time. Here's the updated schedule:",
            date_label=user_date_label, time_label=user_time_label, tz_abbr=user_tz_abbr,
        ) + f"<!-- manage: {manage_url} -->"
        send_graph_email(
            to_email=demo_request.email, to_name=demo_request.full_name,
            subject=f"Rescheduled: iPharmaAI Demo ({demo_request.full_name}) @ {user_date_label} {user_time_label} {user_tz_abbr}",
            html=confirmation_html, ics_content=ics_content,
            inline_images=[_logo_inline_image("blue")],
        )
        send_graph_email(
            to_email=settings.BOOKING_HOST_EMAIL, to_name="iPharmaAI Team",
            subject=f"Rescheduled: iPharmaAI Demo ({demo_request.full_name}) @ {date_label} {time_label} IST",
            html=_status_update_html(
                first_name="Team", headline="Booking Rescheduled",
                message=f"{demo_request.full_name} ({demo_request.company_name}) moved their demo to a new time.",
                date_label=date_label, time_label=time_label,
            ),
            ics_content=ics_content, inline_images=[_logo_inline_image("white")],
        )
    except (GraphNotConfigured, Exception) as err:
        print(f"[requestdemo_manage_reschedule] email send failed: {err}")

    return redirect(reverse("requestdemo_manage", args=[token]) + "?msg=rescheduled")
