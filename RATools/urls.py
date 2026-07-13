from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    # Authentication URLs Should be below this line
    path("", views.basetemplate),
    path("baseshow/", views.baseShow),
    path("module/", views.module_view),
    path("modulehome/",views.moduletemplate),

    path("module/open-file/", views.open_file, name="open_file"),
    path("module/download-folder/", views.download_folder_zip, name="download_folder_zip"),

    # ANDA URLs Should be below this line
    path("requestdemo", views.requestdemo),
    path("requestdemo/availability", views.requestdemo_availability, name="requestdemo_availability"),
    path("requestdemo/preview-email/<str:kind>/", views.requestdemo_preview_email, name="requestdemo_preview_email"),
    # MDI AND DIP
    path("show_anda_mdi_and_dpi_table", views.show_anda_mdi_and_dpi_table),
    path("show_anda_mdi_and_dpi_table/", views.show_anda_mdi_and_dpi_table),
    path(
        "anda/show_anda_mdi_and_dpi_report/<int:id>/",
        views.show_anda_mdi_and_dpi_report,
        name="show_anda_mdi_and_dpi_report",
    ),
    path(
        "anda/add_anda_mdi_and_dpi_checklist/",
        views.add_anda_mdi_and_dpi_checklist,
        name="add_anda_mdi_and_dpi_checklist",
    ),
    path(
        "anda/delete_anda_mdi_and_dpi_checklist/<int:id>",
        views.delete_anda_mdi_and_dpi_checklist,
        name="delete_anda_mdi_and_dpi_checklist",
    ),
    path("show_anda_liposome_table", views.show_anda_liposome_table),
    path(
        "anda/show_anda_liposome_report/<int:id>/",
        views.show_anda_liposome_report,
        name="show_anda_liposome_report",
    ),
    path(
        "anda/add_anda_liposome_checklist/",
        views.add_anda_liposome_checklist,
        name="add_anda_liposome_checklist",
    ),
    path(
        "anda/delete_anda_liposome_checklist/<int:id>",
        views.delete_anda_liposome_checklist,
        name="delete_anda_liposome_checklist",
    ),


    path("show_anda_microsphere_table", views.show_anda_microsphere_table),
    path(
        "anda/show_anda_microsphere_report/<int:id>/",
        views.show_anda_microsphere_report,
        name="show_anda_microsphere_report",
    ),
    path(
        "anda/add_anda_microsphere_checklist/",
        views.add_anda_microsphere_checklist,
        name="add_anda_microsphere_checklist",
    ),
    path(
        "anda/delete_anda_microsphere_checklist/<int:id>",
        views.delete_anda_microsphere_checklist,
        name="delete_anda_microsphere_checklist",
    ),


    # Nasalspray Inhalation
    path(
        "show_anda_nasalspray_inhalation_table",
        views.show_anda_nasalspray_inhalation_table,
    ),
    path(
        "anda/show_anda_nasalspray_inhalation_report/<int:id>/",
        views.show_anda_nasalspray_inhalation_report,
        name="show_anda_nasalspray_inhalation_report",
    ),
    path(
        "anda/add_anda_nasalspray_inhalation_checklist/",
        views.add_anda_nasalspray_inhalation_checklist,
        name="add_anda_nasalspray_inhalation_checklist",
    ),
    path(
        "anda/delete_anda_nasalspray_inhalation_checklist/<int:id>",
        views.delete_anda_nasalspray_inhalation_checklist,
        name="delete_anda_nasalspray_inhalation_checklist",
    ),
    # Parenteral Dosage
    path("show_anda_parenteral_dosage_table", views.show_anda_parenteral_dosage_table),
    path(
        "anda/show_anda_parenteral_dosage_report/<int:id>/",
        views.show_anda_parenteral_dosage_report,
        name="show_anda_parenteral_dosage_report",
    ),
    path(
        "anda/add_anda_parenteral_dosage_checklist/",
        views.add_anda_parenteral_dosage_checklist,
        name="add_anda_parenteral_dosage_checklist",
    ),
    path(
        "anda/delete_anda_parenteral_dosage_checklist/<int:id>",
        views.delete_anda_parenteral_dosage_checklist,
        name="delete_anda_parenteral_dosage_checklist",
    ),
    # TransdermL Dosage
    path(
        "show_anda_transdermal_dosage_table", views.show_anda_transdermal_dosage_table
    ),
    path(
        "anda/show_anda_transdermal_dosage_report/<int:id>/",
        views.show_anda_transdermal_dosage_report,
        name="show_anda_transdermal_dosage_report",
    ),
    path(
        "anda/add_anda_transdermal_dosage_checklist/",
        views.add_anda_transdermal_dosage_checklist,
        name="add_anda_transdermal_dosage_checklist",
    ),
    path(
        "anda/delete_anda_transdermal_dosage_checklist/<int:id>",
        views.delete_anda_transdermal_dosage_checklist,
        name="delete_anda_transdermal_dosage_checklist",
    ),
    # General Table
    path("show_anda_general_table", views.show_anda_general_table),
    path(
        "anda/show_anda_general_report/<int:id>/",
        views.show_anda_general_report,
        name="show_anda_general_report",
    ),
    path(
        "anda/add_anda_general_checklist/",
        views.add_anda_general_checklist,
        name="add_anda_general_checklist",
    ),
    path(
        "anda/delete_anda_general_checklist/<int:id>",
        views.delete_anda_general_checklist,
        name="delete_anda_general_checklist",
    ),
    # Opthalmic Dosage
    path("show_anda_ophthalmic_dosage_table", views.show_anda_ophthalmic_dosage_table),
    path(
        "anda/show_anda_ophthalmic_dosage_report/<int:id>/",
        views.show_anda_ophthalmic_dosage_report,
        name="show_anda_ophthalmic_dosage_report",
    ),
    path(
        "anda/add_anda_ophthalmic_dosage_checklist/",
        views.add_anda_ophthalmic_dosage_checklist,
        name="add_anda_ophthalmic_dosage_checklist",
    ),
    path(
        "anda/delete_anda_ophthalmic_dosage_checklist/<int:id>",
        views.delete_anda_ophthalmic_dosage_checklist,
        name="delete_anda_ophthalmic_dosage_checklist",
    ),
    # Semi Solid Dosage
    path(
        "show_anda_semi_solid_topical_dosage_table",
        views.show_anda_semi_solid_topical_dosage_table,
    ),
    path(
        "anda/show_anda_semi_solid_topical_dosage_report/<int:id>/",
        views.show_anda_semi_solid_topical_dosage_report,
        name="show_anda_semi_solid_topical_dosage_report",
    ),
    path(
        "anda/add_anda_semi_solid_topical_dosage_checklist/",
        views.add_anda_semi_solid_topical_dosage_checklist,
        name="add_anda_semi_solid_topical_dosage_checklist",
    ),
    path(
        "anda/delete_anda_semi_solid_topical_dosage_checklist/<int:id>",
        views.delete_anda_semi_solid_topical_dosage_checklist,
        name="delete_anda_semi_solid_topical_dosage_checklist",
    ),
    # Solid Oral Dosage
    path("show_anda_solid_oral_dosage_table", views.show_anda_solid_oral_dosage_table),
    path(
        "anda/show_anda_solid_oral_report/<int:id>/",
        views.show_anda_solid_oral_report,
        name="show_anda_solid_oral_report",
    ),
    path(
        "anda/add_anda_solid_oral_dosage_checklist/",
        views.add_anda_solid_oral_dosage_checklist,
        name="add_anda_solid_oral_dosage_checklist",
    ),
    path(
        "anda/delete_anda_solid_oral_dosage_checklist/<int:id>",
        views.delete_anda_solid_oral_dosage_checklist,
        name="delete_anda_solid_oral_dosage_checklist",
    ),
    # ANDA Facility Tamplate URLs Should be below this line
    path("show_anda_faciltiy", views.show_anda_faciltiy, name="show_anda_faciltiy"),
    # Controlled Correspondences URLs Should be below this line
    path(
        "show_controlled_correspondences_bestpractice",
        views.show_controlled_correspondences_bestpractice,
        name="show_controlled_correspondences_bestpractice",
    ),
    path(
        "show_controlled_correspondences_template",
        views.show_controlled_correspondences_template,
        name="show_controlled_correspondences_template",
    ),
    # DMF URLs Should be below this line
    path("add_dmf_checklist/", views.add_dmf_checklist, name="add_dmf_checklist"),
    path("show_dmf_table", views.show_dmf_table, name="show_dmf_table"),
    path("show_dmf_report/<int:id>/", views.show_dmf_report, name="show_dmf_report"),
    path('dmf/delete_dmf_checklist/<int:id>', views.delete_dmf_checklist, name='delete_dmf_checklist'),
    # IIG URLs Should be below this line

    path("show_iig_liposome", views.show_iig_liposome, name="show_iig_liposome"),
    path(
        "add_iig_liposome_checklist/",
        views.add_iig_liposome_checklist,
        name="add_iig_liposome_checklist",
    ),
    path(
        "delete_iig_checklist_liposome/<int:id>",
        views.delete_iig_checklist_liposome,
        name="delete_iig_checklist_liposome",
    ),

    path("show_iig_microsphere", views.show_iig_microsphere, name="show_iig_microsphere"),
    path(
        "add_iig_microsphere_checklist/",
        views.add_iig_microsphere_checklist,
        name="add_iig_microsphere_checklist",
    ),
    path(
        "delete_iig_checklist_microsphere/<int:id>",
        views.delete_iig_checklist_microsphere,
        name="delete_iig_checklist_microsphere",
    ),
    path("show_iig_dpi", views.show_iig_dpi, name="show_iig_dpi"),
    path(
        "add_iig_dpi_checklist/",
        views.add_iig_dpi_checklist,
        name="add_iig_dpi_checklist",
    ),
    path(
        "delete_iig_checklist_dpi/<int:id>",
        views.delete_iig_checklist_dpi,
        name="delete_iig_checklist_dpi",
    ),
    path(
        "show_iig_inhalation_table",
        views.show_iig_inhalation_table,
        name="show_iig_inhalation_table",
    ),
    path(
        "add_iig_inhalation_checklist/",
        views.add_iig_inhalation_checklist,
        name="add_iig_inhalation_checklist",
    ),
    path(
        "delete_iig_checklist_inhalation/<int:id>",
        views.delete_iig_checklist_inhalation,
        name="delete_iig_checklist_inhalation",
    ),
    path(
        "show_iig_liquidoral_table",
        views.show_iig_liquidoral_table,
        name="show_iig_liquidoral_table",
    ),
    path(
        "add_iig_liquidoral_checklist/",
        views.add_iig_liquidoral_checklist,
        name="add_iig_liquidoral_checklist",
    ),
    path(
        "delete_iig_checklist_liquidoral/<int:id>",
        views.delete_iig_checklist_liquidoral,
        name="delete_iig_checklist_liquidoral",
    ),
    path(
        "show_iig_injection_table",
        views.show_iig_injection_table,
        name="show_iig_injection_table",
    ),
    path(
        "add_iig_injection_checklist/",
        views.add_iig_injection_checklist,
        name="add_iig_injection_checklist",
    ),
    path(
        "delete_iig_checklist_injection/<int:id>",
        views.delete_iig_checklist_injection,
        name="delete_iig_checklist_injection",
    ),
    path("show_iig_mdi_table", views.show_iig_mdi_table, name="show_iig_mdi_table"),
    path(
        "add_iig_mdi_checklist/",
        views.add_iig_mdi_checklist,
        name="add_iig_mdi_checklist",
    ),
    path(
        "delete_iig_checklist_mdi/<int:id>",
        views.delete_iig_checklist_mdi,
        name="delete_iig_checklist_mdi",
    ),
    path(
        "show_iig_semisolid_table",
        views.show_iig_semisolid_table,
        name="show_iig_semisolid_table",
    ),
    path(
        "add_iig_semisolid_checklist/",
        views.add_iig_semisolid_checklist,
        name="add_iig_semisolid_checklist",
    ),
    path(
        "delete_iig_checklist_semisolid/<int:id>",
        views.delete_iig_checklist_semisolid,
        name="delete_iig_checklist_semisolid",
    ),
    path(
        "show_iig_nasal_table", views.show_iig_nasal_table, name="show_iig_nasal_table"
    ),
    path(
        "add_iig_nasal_checklist/",
        views.add_iig_nasal_checklist,
        name="add_iig_nasal_checklist",
    ),
    path(
        "delete_iig_checklist_nasal/<int:id>",
        views.delete_iig_checklist_nasal,
        name="delete_iig_checklist_nasal",
    ),
    path(
        "show_iig_tablet_table",
        views.show_iig_tablet_table,
        name="show_iig_tablet_table",
    ),
    path(
        "add_iig_tablet_checklist/",
        views.add_iig_tablet_checklist,
        name="add_iig_tablet_checklist",
    ),
    path(
        "delete_iig_checklist_tablet/<int:id>",
        views.delete_iig_checklist_tablet,
        name="delete_iig_checklist_tablet",
    ),
    path(
        "show_iig_topical_table",
        views.show_iig_topical_table,
        name="show_iig_topical_table",
    ),
    path(
        "add_iig_topical_checklist/",
        views.add_iig_topical_checklist,
        name="add_iig_topical_checklist",
    ),
    path(
        "delete_iig_checklist_topical/<int:id>",
        views.delete_iig_checklist_topical,
        name="delete_iig_checklist_topical",
    ),
    path(
        "show_iig_transdermal_table",
        views.show_iig_transdermal_table,
        name="show_iig_transdermal_table",
    ),
    path(
        "add_iig_transdermal_checklist/",
        views.add_iig_transdermal_checklist,
        name="add_iig_transdermal_checklist",
    ),
    path(
        "delete_iig_checklist_transdermal/<int:id>",
        views.delete_iig_checklist_transdermal,
        name="delete_iig_checklist_transdermal",
    ),
    path(
        "show_iig_proportionality_clearance_report/<int:id>/",
        views.show_iig_proportionality_clearance_report,
        name="show_iig_proportionality_clearance_report",
    ),
    # Size, Shape & Score URLs Should be below this line
    path("show_sss", views.show_sss, name="show_sss"),
    path("add_sss_checklist/", views.add_sss_checklist, name="add_sss_checklist"),
    path("delete_sss/<int:id>", views.delete_sss, name="delete_sss"),
    path(
        "size_shape_score_report/<int:id>/",
        views.size_shape_score_report,
        name="size_shape_score_report",
    ),
    # API Facility URLs Should be below this line
    path("show_api_faciltiy", views.show_api_faciltiy, name="show_api_faciltiy"),
    path(
        "download/<str:document_name>/",
        views.download_document,
        name="download_document",
    ),
    # Validation URLs Should be below this line
    path("show_api_validation_table", views.show_api_validation_table),
    path(
        "validation/show_api_validation_report/<int:id>/",
        views.show_api_validation_report,
        name="show_api_validation_report",
    ),
    path(
        "validation/add_api_validation_checklist/",
        views.add_api_validation_checklist,
        name="add_api_validation_checklist",
    ),
    path(
        "validation/delete_api_validation_checklist/<int:id>",
        views.delete_api_validation_checklist,
        name="delete_api_validation_checklist",
    ),
    path("show_api_verification_table", views.show_api_verification_table),
    path(
        "validation/show_api_verification_report/<int:id>/",
        views.show_api_verification_report,
        name="show_api_verification_report",
    ),
    path(
        "validation/add_api_verification_checklist/",
        views.add_api_verification_checklist,
        name="add_api_verification_checklist",
    ),
    path(
        "validation/delete_api_verification_checklist/<int:id>",
        views.delete_api_verification_checklist,
        name="delete_api_verification_checklist",
    ),
    path(
        "show_drug_product_validation_table", views.show_drug_product_validation_table
    ),
    path(
        "validation/show_drug_product_validation_report/<int:id>/",
        views.show_drug_product_validation_report,
        name="show_drug_product_validation_report",
    ),
    path(
        "validation/add_drug_product_validation_checklist/",
        views.add_drug_product_validation_checklist,
        name="add_drug_product_validation_checklist",
    ),
    path(
        "validation/delete_drug_product_validation_checklist/<int:id>",
        views.delete_drug_product_validation_checklist,
        name="delete_drug_product_validation_checklist",
    ),
    # VP URLs Should be below this line

    path("show_vp_liposome_table", views.show_vp_liposome_table),
    path(
        "vp/show_vp_liposome_report/<int:id>/",
        views.show_vp_liposome_report,
        name="show_vp_liposome_report",
    ),
    path(
        "vp/add_vp_liposome_checklist/",
        views.add_vp_liposome_checklist,
        name="add_vp_liposome_checklist",
    ),
    path(
        "vp/delete_vp_liposome_checklist/<int:id>",
        views.delete_vp_liposome_checklist,
        name="delete_vp_liposome_checklist",
    ),

    path("show_vp_microsphere_table", views.show_vp_microsphere_table),
    path(
        "vp/show_vp_microsphere_report/<int:id>/",
        views.show_vp_microsphere_report,
        name="show_vp_microsphere_report",
    ),
    path(
        "vp/add_vp_microsphere_checklist/",
        views.add_vp_microsphere_checklist,
        name="add_vp_microsphere_checklist",
    ),
    path(
        "vp/delete_vp_microsphere_checklist/<int:id>",
        views.delete_vp_microsphere_checklist,
        name="delete_vp_microsphere_checklist",
    ),

    # MDI AND DIP
    path("show_vp_mdi_and_dpi_table", views.show_vp_mdi_and_dpi_table),
    path(
        "vp/show_vp_mdi_and_dpi_report/<int:id>/",
        views.show_vp_mdi_and_dpi_report,
        name="show_vp_mdi_and_dpi_report",
    ),
    path(
        "vp/add_vp_mdi_and_dpi_checklist/",
        views.add_vp_mdi_and_dpi_checklist,
        name="add_vp_mdi_and_dpi_checklist",
    ),
    path(
        "vp/delete_vp_mdi_and_dpi_checklist/<int:id>",
        views.delete_vp_mdi_and_dpi_checklist,
        name="delete_vp_mdi_and_dpi_checklist",
    ),


    # Nasal and Inhalation
    path("show_vp_nasal_inhalation_table", views.show_vp_nasal_inhalation_table),
    path(
        "vp/show_vp_nasal_inhalation_report/<int:id>/",
        views.show_vp_nasal_inhalation_report,
        name="show_vp_nasal_inhalation_report",
    ),
    path(
        "vp/add_vp_nasal_inhalation_checklist/",
        views.add_vp_nasal_inhalation_checklist,
        name="add_vp_nasal_inhalation_checklist",
    ),
    path(
        "vp/delete_vp_nasal_inhalation_checklist/<int:id>",
        views.delete_vp_nasal_inhalation_checklist,
        name="delete_vp_nasal_inhalation_checklist",
    ),
    # Ophthalmic
    path("show_vp_ophthalmic_table", views.show_vp_ophthalmic_table),
    path(
        "vp/show_vp_ophthalmic_report/<int:id>/",
        views.show_vp_ophthalmic_report,
        name="show_vp_ophthalmic_report",
    ),
    path(
        "vp/add_vp_ophthalmic_checklist/",
        views.add_vp_ophthalmic_checklist,
        name="add_vp_ophthalmic_checklist",
    ),
    path(
        "vp/delete_vp_ophthalmic_checklist/<int:id>",
        views.delete_vp_ophthalmic_checklist,
        name="delete_vp_ophthalmic_checklist",
    ),
    # Liquid Oral
    path("show_vp_liquidorals_table", views.show_vp_liquidorals_table),
    path(
        "vp/show_vp_liquidorals_report/<int:id>/",
        views.show_vp_liquidorals_report,
        name="show_vp_liquidorals_report",
    ),
    path(
        "vp/add_vp_liquidorals_checklist/",
        views.add_vp_liquidorals_checklist,
        name="add_vp_liquidorals_checklist",
    ),
    path(
        "vp/delete_vp_liquidorals_checklist/<int:id>",
        views.delete_vp_liquidorals_checklist,
        name="delete_vp_liquidorals_checklist",
    ),
    # Parenteral
    path("show_vp_parenteral_table", views.show_vp_parenteral_table),
    path(
        "vp/show_vp_parenteral_report/<int:id>/",
        views.show_vp_parenteral_report,
        name="show_vp_parenteral_report",
    ),
    path(
        "vp/add_vp_parenteral_checklist/",
        views.add_vp_parenteral_checklist,
        name="add_vp_parenteral_checklist",
    ),
    path(
        "vp/delete_vp_parenteral_checklist/<int:id>",
        views.delete_vp_parenteral_checklist,
        name="delete_vp_parenteral_checklist",
    ),
    # Solid Oral
    path("show_vp_solidoral_table", views.show_vp_solidoral_table),
    path(
        "vp/show_vp_solidoral_report/<int:id>/",
        views.show_vp_solidoral_report,
        name="show_vp_solidoral_report",
    ),
    path(
        "vp/add_vp_solidoral_checklist/",
        views.add_vp_solidoral_checklist,
        name="add_vp_solidoral_checklist",
    ),
    path(
        "vp/delete_vp_solidoral_checklist/<int:id>",
        views.delete_vp_solidoral_checklist,
        name="delete_vp_solidoral_checklist",
    ),
    # Topical
    path("show_vp_topical_table", views.show_vp_topical_table),
    path(
        "vp/show_vp_topical_report/<int:id>/",
        views.show_vp_topical_report,
        name="show_vp_topical_report",
    ),
    path(
        "vp/add_vp_topical_checklist/",
        views.add_vp_topical_checklist,
        name="add_vp_topical_checklist",
    ),
    path(
        "vp/delete_vp_topical_checklist/<int:id>",
        views.delete_vp_topical_checklist,
        name="delete_vp_topical_checklist",
    ),
    # Transermal
    path("show_vp_transdermal_table", views.show_vp_transdermal_table),
    path(
        "vp/show_vp_transdermal_report/<int:id>/",
        views.show_vp_transdermal_report,
        name="show_vp_transdermal_report",
    ),
    path(
        "vp/add_vp_transdermal_checklist/",
        views.add_vp_transdermal_checklist,
        name="add_vp_transdermal_checklist",
    ),
    path(
        "vp/delete_vp_transdermal_checklist/<int:id>",
        views.delete_vp_transdermal_checklist,
        name="delete_vp_transdermal_checklist",
    ),
    # White Paper URLs Should be below this line
    # path(
    #     "add_appendix_checklist/",
    #     views.add_appendix_checklist,
    #     name="add_appendix_checklist",
    # ),
    path(
        "add_general_checklist/",
        views.add_general_checklist,
        name="add_general_checklist",
    ),
    path(
        "delete_general_checklist/<int:id>",
        views.delete_general_checklist,
        name="delete_general_checklist",
    ),
    path(
        "general_white_paper_report/<int:id>/",
        views.general_white_paper_report,
        name="general_white_paper_report",
    ),
    path(
        "general_white_paper_table",
        views.general_white_paper_table,
        name="general_white_paper_table",
    ),
    # path(
    #     "appendix_white_paper", views.appendix_white_paper, name="appendix_white_paper"
    # ),
    path("view_sample_anda_checklist/<str:report_name>", views.view_sample_anda_checklist, name="view_sample_anda_checklist"),
    path("view_sample_iig_reports/<str:report_name>", views.view_sample_iig_reports, name="view_sample_iig_reports"),
    path("view_sample_validation_report/<str:report_name>", views.view_sample_validation_report, name="view_sample_validation_report"),
    path("view_sample_vp_report/<str:report_name>", views.view_sample_vp_report, name="view_sample_vp_report"),
    path("view_sample_dmf",views.view_sample_dmf,name="view_sample_dmf"),
    path("view_sample_sss",views.view_sample_sss,name="view_sample_sss"),
    path("view_general_white_paper_sample",views.view_general_white_paper_sample,name="view_general_white_paper_sample"),
]+ static(settings.STATIC_URL, document_root=settings.STATIC_ROOT) + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
