from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # ANDA URLs here
    path('anda/ectd_acceptance_deficiency/', views.anda_ectd_acceptance_deficiency),
    path('anda/technical_acceptance_deficiency/', views.anda_technical_acceptance_deficiency),
    path('anda/nasal_spray_deficiency/', views.anda_nasal_spray_deficiency),
    path('anda/liquid_oral_deficiency/', views.anda_liquid_oral_deficiency),
    path('anda/iud_deficiency/', views.anda_iud_deficiency),
    path('anda/tdds-deficiency/', views.anda_tdds_deficiency),
    path('anda/suppository_deficiency/', views.anda_suppository_deficiency),
    path('anda/topicals_deficiency/', views.anda_topicals_deficiency),
    path('anda/solid_oral_deficiency/', views.anda_solid_oral_deficiency),
    path('anda/ophthalmic_deficiency/', views.anda_ophthalmic_deficiency),
    path('anda/otic_deficiency/', views.anda_otic_deficiency),
    path('anda/injectable_peptide_deficiency/', views.anda_injectable_peptide_deficiency),
    path('anda/injectable_general_deficiency/', views.anda_injectable_general_deficiency),

    # Major CR URLs here
    path('', views.show_major_cr),
    path('majorcr/nasal_spray_deficiency/', views.majorcr_nasal_spray_deficiency),
    path('form483/', views.form483_dashboard),
    path('auditiq/', views.auditiq_dashboard, name='auditiq_dashboard'),
    path('form483_database', views.show_form483_data),
    path('majorcr/liquid_oral_deficiency/', views.majorcr_liquid_oral_deficiency),
    path('majorcr/iud_deficiency/', views.majorcr_iud_deficiency),
    path('majorcr/tdds-deficiency/', views.majorcr_tdds_deficiency),
    path('majorcr/suppository_deficiency/', views.majorcr_suppository_deficiency),
    path('majorcr/topicals_deficiency/', views.majorcr_topicals_deficiency),
    path('majorcr/solid_oral_deficiency/', views.majorcr_solid_oral_deficiency),
    path('majorcr/ophthalmic_deficiency/', views.majorcr_ophthalmic_deficiency),
    path('majorcr/otic_deficiency/', views.majorcr_otic_deficiency),
    path('majorcr/injectable_peptide_deficiency/', views.majorcr_injectable_peptide_deficiency),
    path('majorcr/injectable_general_deficiency/', views.majorcr_injectable_general_deficiency),

    # dashboard api
    path('get_anda_chart_data/',views.get_anda_chart_data, name='get_anda_chart_data'),
    path('get_anda_bubble_data/',views.get_anda_bubble_data, name='get_anda_bubble_data'),
    path('ai_master_base/',views.ai_master_base, name='ai_master_base'),
    path('anda_deficicency_count_pie/',views.anda_deficicency_count_pie, name='anda_deficicency_count_pie'),
    path('anda_category_deficicency_count_pie/',views.anda_category_deficicency_count_pie, name='anda_category_deficicency_count_pie'),
    path('anda_dosage_count_pie/',views.anda_dosage_count_pie, name='anda_dosage_count_pie'),
    path('get_major_cr_chart_data/',views.get_major_cr_chart_data, name='get_major_cr_chart_data'),
    path('get_major_cr_bubble_data/',views.get_major_cr_bubble_data, name='get_major_cr_bubble_data'),
    path('major_cr_base/',views.major_cr_base, name='major_cr_base'),
    path('major_cr_deficicency_count_pie/',views.major_cr_deficicency_count_pie, name='major_cr_deficicency_count_pie'),
    path('major_cr_category_deficicency_count_pie/',views.major_cr_category_deficicency_count_pie, name='major_cr_category_deficicency_count_pie'),

    path('pie-chart-main-category/', views.pie_chart_main_category, name='pie_chart_main_category'),
    path('major_cr_pie_chart_dosage_form/', views.major_cr_pie_chart_dosage_form, name='major_cr_pie_chart_dosage_form'),
    path('pie-chart-deficiency-type/', views.pie_chart_deficiency_type, name='pie_chart_deficiency_type'),
    path('pie-chart-category-of-deficiency/', views.pie_chart_category_of_deficiency, name='pie_chart_category_of_deficiency'),
    path('bar-chart-main-category/', views.bar_chart_main_category, name='bar_chart_main_category'),
    path('bar-chart-cmc-section/', views.bar_chart_cmc_section, name='bar_chart_cmc_section'),
    path('bar-chart-category-vs-deficiency/', views.bar_chart_category_vs_deficiency, name='bar_chart_category_vs_deficiency'),
    path('major_cr_bar_chart_cmc_section/', views.major_cr_bar_chart_cmc_section, name='major_cr_bar_chart_cmc_section'),
    path('major_cr_bar_chart_category_vs_deficiency/', views.major_cr_bar_chart_category_vs_deficiency, name='major_cr_bar_chart_category_vs_deficiency'),


    path('list_of_organization_names/',views.list_of_organization_names, name='list_of_organization_names'),
    path('list_of_fei_numbers/',views.list_of_fei_numbers, name='list_of_fei_numbers'),
    path('list_of_country/',views.list_of_country, name='list_of_country'),
    path('list_of_company/',views.list_of_company, name='list_of_company'),
    path('list_of_investigators/',views.list_of_investigators, name='list_of_investigators'),
    path('list_of_establishments/', views.list_of_establishments, name='list_of_establishments'),
    path('list_of_systems/',views.list_of_systems, name='list_of_systems'),
    path("list_of_years/", views.list_of_years, name="list_of_years"),
    path('company_object/',views.company_object, name='company_object'),
    path('render_company_name/',views.render_company_name, name='render_company_name'),
    path('render_investigator/', views.render_investigator, name='render_investigator'),
    path('new_investigator/', views.new_investigator, name='new_investigator'),
    path('particular_investigator/', views.particular_investigator, name='particular_investigator'),

    path('render_systempage/', views.render_systempage, name='render_systempage'),
    path('render_system_checklist/', views.render_system_checklist, name='render_system_checklist'),
    path('render_yearofinspection/', views.render_yearofinspection, name='render_yearofinspection'),

    path('warning_letter/', views.warning_letter, name='warning_letter'),
    path('inspection_hub/', views.inspection_hub, name='inspection_hub'),
    path('usfda_guideline/', views.usfda_guideline, name='usfda_guideline'),
    path('section_inspection/', views.section_inspection, name='section_inspection'),
    path('playbook/', views.playbook, name='playbook'),
    path('render_warning_letter/', views.render_warning_letter, name='render_warning_letter'),
    path('warning_letter_company/',views.warning_letter_company, name='warning_letter_company'),
    path('issuing_office_list/',views.issuing_office_list, name='issuing_office_list'),
    path('warning_letter_data/',views.warning_letter_data, name='warning_letter_data'),

    path('updates-data/', views.updates_data, name='updates_data'),
    path('checked-updates/', views.checked_updates, name='checked_updates'),
    path('gmpc/active-country-excels/', views.gmpc_active_country_excels, name='gmpc_active_country_excels'),
    path('gmpc/filter-options/', views.gmpc_filter_options_api, name='gmpc_filter_options_api'),
    # path('active-announcements/', views.active_announcements, name='active_announcements'),

    path('system_checklist/', views.system_checklists, name='system_checklist'),
    path('top20_recurring/', views.india_manufacturer, name='india_manufacturer'),
    path('render_top20recurring_detail/', views.render_top20recurring_detail, name='render_top20recurring_detail'),

    path('investigator_insights/', views.investigator_insights, name='investigator_insights'),
    path('investigator-detail-insights/', views.investigator_detail_insights, name='investigator_detail_insights'),

    # path('get_filters_api/<str:country>/', views.get_filters_api, name='get_filters_api'),
    path('gmpc_module/', views.gmpc_homepage, name='gmpc_module'),
    path('gmpc_dashboard/', views.gmpc_dashboard, name='gmpc_dashboard'),
    path('render_gmpc_search/', views.gmpc_module, name='render_gmpc_search'),
    path('top10_investigators/', views.top10_investigators, name='top10_investigators'),
    path('top10_companies/', views.top10_companies, name='top10_companies'),




    # path('chat_ui_view/', views.chat_ui_view, name='chat_ui'),
    # path("chat_with_bot/", views.chat_with_bot, name="chat_with_bot"),
    # path('clear_chat/', views.clear_chat, name='clear_chat'),
    # path('new_chat/', views.new_chat, name='new_chat'),
    # path("get_all_chat_histories/", views.get_all_chat_histories, name="get_all_chat_histories"),
    # path("get_all_chat_by_specific_id/<int:chat_id>/", views.get_all_chat_by_specific_id, name="get_all_chat_by_specific_id"),
    # path("delete_chat_by_id/<int:chat_id>/", views.delete_chat_by_id, name="delete_chat_by_id"),


]+ static(settings.STATIC_URL, document_root=settings.STATIC_ROOT) + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
