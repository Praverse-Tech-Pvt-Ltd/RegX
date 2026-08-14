from django.urls import path
from . import views
# admin master urls


urlpatterns = [
    path('', views.homepage),
    path('adminbase',views.adminbase),
    path("login/",views.login,name="login"),
    path("logout/",views.logout,name="logout"),
    path("view_users",views.view_users,name="view_users"),
    path("edit_user/<int:id>",views.edit_user,name="edit_user"),
    path("add_user",views.add_user,name="add_user"),
    path("delete_user/<int:id>",views.delete_user),

    #ANDA
    path('show_anda_mdi_dpi', views.show_anda_mdi_dpi, name='show_anda_mdi_dpi'),
    path('add_anda_mdi_and_dpi/', views.add_anda_mdi_and_dpi, name='add_anda_mdi_and_dpi'),
    path('edit_anda_mdi_and_dpi/<int:id>', views.edit_anda_mdi_and_dpi, name='edit_anda_mdi_and_dpi'),
    path('delete_anda_mdi_and_dpit/<int:id>', views.delete_anda_mdi_and_dpit, name='delete_anda_mdi_and_dpit'),


    path('show_anda_nasalspray_inhalation_checklist', views.show_anda_nasalspray_inhalation_checklist, name='show_anda_nasalspray_inhalation_checklist'),
    path('add_anda_nasalspray_inhalation_report/', views.add_anda_nasalspray_inhalation_report, name='add_anda_nasalspray_inhalation_report'),
    path('edit_anda_nasalspray_inhalation_report/<int:id>', views.edit_anda_nasalspray_inhalation_report, name='edit_anda_nasalspray_inhalation_report'),
    path('delete_anda_nasalspray_inhalation_report/<int:id>', views.delete_anda_nasalspray_inhalation_report, name='delete_anda_nasalspray_inhalation_report'),

    # Parenteral Dosage
    path('show_anda_parenteral_dosage_table', views.show_anda_parenteral_dosage_table, name='show_anda_parenteral_dosage_table'),
    path('add_anda_parenteral_dosage/', views.add_anda_parenteral_dosage, name='add_anda_parenteral_dosage'),
    path('edit_anda_parenteral_dosage/<int:id>', views.edit_anda_parenteral_dosage, name='edit_anda_parenteral_dosage'),
    path('delete_anda_parenteral_dosage/<int:id>', views.delete_anda_parenteral_dosage, name='delete_anda_parenteral_dosage'),

    # Ophthalmic Dosage
    path('show_anda_ophthalmic_dosage_table', views.show_anda_ophthalmic_dosage_table, name='show_anda_ophthalmic_dosage_table'),
    path('add_anda_ophthalmic_dosage/', views.add_anda_ophthalmic_dosage, name='add_anda_ophthalmic_dosage'),
    path('edit_anda_ophthalmic_dosage/<int:id>', views.edit_anda_ophthalmic_dosage, name='edit_anda_ophthalmic_dosage'),
    path('delete_anda_ophthalmic_dosage/<int:id>', views.delete_anda_ophthalmic_dosage, name='delete_anda_ophthalmic_dosage'),

    # Semi Solid Topical Dosage
    path('show_anda_semi_solid_topical_dosage_table', views.show_anda_semi_solid_topical_dosage_table, name='show_anda_semi_solid_topical_dosage_table'),
    path('add_anda_semi_solid_topical_dosage/', views.add_anda_semi_solid_topical_dosage, name='add_anda_semi_solid_topical_dosage'),
    path('edit_anda_semi_solid_topical_dosage/<int:id>', views.edit_anda_semi_solid_topical_dosage, name='edit_anda_semi_solid_topical_dosage'),
    path('delete_anda_semi_solid_topical_dosage/<int:id>', views.delete_anda_semi_solid_topical_dosage, name='delete_anda_semi_solid_topical_dosage'),

    # Solid Oral Dosage
    path('show_anda_solid_oral_dosage_table', views.show_anda_solid_oral_dosage_table, name='show_anda_solid_oral_dosage_table'),
    path('add_anda_solid_oral_dosage/', views.add_anda_solid_oral_dosage, name='add_anda_solid_oral_dosage'),
    path('edit_anda_solid_oral_dosage/<int:id>', views.edit_anda_solid_oral_dosage, name='edit_anda_solid_oral_dosage'),
    path('delete_anda_solid_oral_dosage/<int:id>', views.delete_anda_solid_oral_dosage, name='delete_anda_solid_oral_dosage'),

    # Transdermal Dosage
    path('show_anda_transdermal_dosage_table', views.show_anda_transdermal_dosage_table, name='show_anda_transdermal_dosage_table'),
    path('add_anda_transdermal_dosage/', views.add_anda_transdermal_dosage, name='add_anda_transdermal_dosage'),
    path('edit_anda_transdermal_dosage/<int:id>', views.edit_anda_transdermal_dosage, name='edit_anda_transdermal_dosage'),
    path('delete_anda_transdermal_dosage/<int:id>', views.delete_anda_transdermal_dosage, name='delete_anda_transdermal_dosage'),

    # General ANDA
    path('show_anda_general_table', views.show_anda_general_table, name='show_anda_general_table'),
    path('add_anda_general/', views.add_anda_general, name='add_anda_general'),
    path('edit_anda_general/<int:id>', views.edit_anda_general, name='edit_anda_general'),
    path('delete_anda_general/<int:id>', views.delete_anda_general, name='delete_anda_general'),



    #VP
    path('show_vp_mdi_dpi', views.show_vp_mdi_dpi, name='show_vp_mdi_dpi'),
    path('add_vp_mdi_and_dpi/', views.add_vp_mdi_and_dpi, name='add_vp_mdi_and_dpi'),
    path('edit_vp_mdi_and_dpi/<int:id>', views.edit_vp_mdi_and_dpi, name='edit_vp_mdi_and_dpi'),
    path('delete_vp_mdi_and_dpi/<int:id>', views.delete_vp_mdi_and_dpi, name='delete_vp_mdi_and_dpi'),

    path('show_vp_nasal_inhalation', views.show_vp_nasal_inhalation, name='show_vp_nasal_inhalation'),
    path('add_vp_nasal_inhalation/', views.add_vp_nasal_inhalation, name='add_vp_nasal_inhalation'),
    path('edit_vp_nasal_inhalation/<int:id>', views.edit_vp_nasal_inhalation, name='edit_vp_nasal_inhalation'),
    path('delete_vp_nasal_inhalation/<int:id>', views.delete_vp_nasal_inhalation, name='delete_vp_nasal_inhalation'),

    # Ophthalmic URLs
    path('show_vp_ophthalmic', views.show_vp_ophthalmic, name='show_vp_ophthalmic'),
    path('add_vp_ophthalmic/', views.add_vp_ophthalmic, name='add_vp_ophthalmic'),
    path('edit_vp_ophthalmic/<int:id>', views.edit_vp_ophthalmic, name='edit_vp_ophthalmic'),
    path('delete_vp_ophthalmic/<int:id>', views.delete_vp_ophthalmic, name='delete_vp_ophthalmic'),

    # Liquid Orals URLs
    path('show_vp_liquidorals_table', views.show_vp_liquidorals_table, name='show_vp_liquidorals_table'),
    path('add_vp_liquidorals/', views.add_vp_liquidorals, name='add_vp_liquidorals'),
    path('edit_vp_liquidorals/<int:id>', views.edit_vp_liquidorals, name='edit_vp_liquidorals'),
    path('delete_vp_liquidorals/<int:id>', views.delete_vp_liquidorals, name='delete_vp_liquidorals'),

    # Parenteral URLs
    path('show_vp_parenteral_table', views.show_vp_parenteral_table, name='show_vp_parenteral_table'),
    path('add_vp_parenteral/', views.add_vp_parenteral, name='add_vp_parenteral'),
    path('edit_vp_parenteral/<int:id>', views.edit_vp_parenteral, name='edit_vp_parenteral'),
    path('delete_vp_parenteral/<int:id>', views.delete_vp_parenteral, name='delete_vp_parenteral'),

    # Solid Oral URLs
    path('show_vp_solidoral_table', views.show_vp_solidoral_table, name='show_vp_solidoral_table'),
    path('add_vp_solidoral/', views.add_vp_solidoral, name='add_vp_solidoral'),
    path('edit_vp_solidoral/<int:id>', views.edit_vp_solidoral, name='edit_vp_solidoral'),
    path('delete_vp_solidoral/<int:id>', views.delete_vp_solidoral, name='delete_vp_solidoral'),

    # Topical URLs
    path('show_vp_topical_table', views.show_vp_topical_table, name='show_vp_topical_table'),
    path('add_vp_topical/', views.add_vp_topical, name='add_vp_topical'),
    path('edit_vp_topical/<int:id>', views.edit_vp_topical, name='edit_vp_topical'),
    path('delete_vp_topical/<int:id>', views.delete_vp_topical, name='delete_vp_topical'),

    # Transdermal URLs
    path('show_vp_transdermal_table', views.show_vp_transdermal_table, name='show_vp_transdermal_table'),
    path('add_vp_transdermal/', views.add_vp_transdermal, name='add_vp_transdermal'),
    path('edit_vp_transdermal/<int:id>', views.edit_vp_transdermal, name='edit_vp_transdermal'),
    path('delete_vp_transdermal/<int:id>', views.delete_vp_transdermal, name='delete_vp_transdermal'),




    #DMF
    #CA
    path('show_dmfca_table', views.show_dmfca_table, name='show_dmfca_table'),
    path('add_dmfca_question/', views.add_dmfca_question, name='add_dmfca_question'),
    path('edit_dmfca_question/<int:id>', views.edit_dmfca_question, name='edit_dmfca_question'),
    path('delete_dmfca_question/<int:id>', views.delete_dmfca_question, name='delete_dmfca_question'),

    #Review
    path('show_dmf_review_table', views.show_dmf_review_table, name='show_dmf_review_table'),
    path('add_dmf_review/', views.add_dmf_review, name='add_dmf_review'),
    path('edit_dmf_review/<int:id>', views.edit_dmf_review, name='edit_dmf_review'),
    path('delete_dmf_review/<int:id>', views.delete_dmf_review, name='delete_dmf_review'),

    # white_papers
    #general_white_papers
    path('show_general_white_papers_table', views.show_general_white_papers_table, name='show_general_white_papers_table'),
    path('add_general_white_papers/', views.add_general_white_papers, name='add_general_white_papers'),
    path('edit_general_white_papers/<int:id>', views.edit_general_white_papers, name='edit_general_white_papers'),
    path('delete_general_white_papers/<int:id>', views.delete_general_white_papers, name='delete_general_white_papers'),

]
