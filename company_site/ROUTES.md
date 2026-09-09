# company_site — URL reference

Generated from the live Django URLconf, not from documentation.

**`APPEND_SLASH` is `False`.** Django does not redirect `/path` to `/path/`
or back, and each route accepts only one of the two forms. Copy the path
exactly as written below, slash included or omitted as shown — a wrong
slash returns a 404 that looks like the page does not exist.

| | |
|---|---|
| Routes listed | 342 |
| Django admin routes (auto-generated, not listed) | 377 |
| Require a trailing slash | 188 |
| Must omit the trailing slash | 154 |

## Ports

| Port | Serves |
|---|---|
| **8080** | Everything user-facing. Refuses user management and `/admin/`. |
| **8090** | The admin console: all of `/adminmaster/` plus `/admin/`. |

`/adminmaster/login/` works on both — an admin has to authenticate on the
origin they will use, because the session cookie is per-origin.

---

## Root  (4 routes)

| URL | Trailing slash | Port | View name |
|---|---|---|---|
| `/` | **no** | 8080 | `` |
| `/about-alpesh/` | yes | 8080 | `` |
| `/privacy-policy/` | yes | 8080 | `` |
| `/termsofuse/` | yes | 8080 | `` |

## RATools  (167 routes)

| URL | Trailing slash | Port | View name |
|---|---|---|---|
| `/ratools/` | yes | 8080 | `` |
| `/ratools/add_dmf_checklist/` | yes | 8080 | `add_dmf_checklist` |
| `/ratools/add_general_checklist/` | yes | 8080 | `add_general_checklist` |
| `/ratools/add_iig_dpi_checklist/` | yes | 8080 | `add_iig_dpi_checklist` |
| `/ratools/add_iig_inhalation_checklist/` | yes | 8080 | `add_iig_inhalation_checklist` |
| `/ratools/add_iig_injection_checklist/` | yes | 8080 | `add_iig_injection_checklist` |
| `/ratools/add_iig_liposome_checklist/` | yes | 8080 | `add_iig_liposome_checklist` |
| `/ratools/add_iig_liquidoral_checklist/` | yes | 8080 | `add_iig_liquidoral_checklist` |
| `/ratools/add_iig_mdi_checklist/` | yes | 8080 | `add_iig_mdi_checklist` |
| `/ratools/add_iig_microsphere_checklist/` | yes | 8080 | `add_iig_microsphere_checklist` |
| `/ratools/add_iig_nasal_checklist/` | yes | 8080 | `add_iig_nasal_checklist` |
| `/ratools/add_iig_semisolid_checklist/` | yes | 8080 | `add_iig_semisolid_checklist` |
| `/ratools/add_iig_tablet_checklist/` | yes | 8080 | `add_iig_tablet_checklist` |
| `/ratools/add_iig_topical_checklist/` | yes | 8080 | `add_iig_topical_checklist` |
| `/ratools/add_iig_transdermal_checklist/` | yes | 8080 | `add_iig_transdermal_checklist` |
| `/ratools/add_sss_checklist/` | yes | 8080 | `add_sss_checklist` |
| `/ratools/anda/add_anda_general_checklist/` | yes | 8080 | `add_anda_general_checklist` |
| `/ratools/anda/add_anda_liposome_checklist/` | yes | 8080 | `add_anda_liposome_checklist` |
| `/ratools/anda/add_anda_mdi_and_dpi_checklist/` | yes | 8080 | `add_anda_mdi_and_dpi_checklist` |
| `/ratools/anda/add_anda_microsphere_checklist/` | yes | 8080 | `add_anda_microsphere_checklist` |
| `/ratools/anda/add_anda_nasalspray_inhalation_checklist/` | yes | 8080 | `add_anda_nasalspray_inhalation_checklist` |
| `/ratools/anda/add_anda_ophthalmic_dosage_checklist/` | yes | 8080 | `add_anda_ophthalmic_dosage_checklist` |
| `/ratools/anda/add_anda_parenteral_dosage_checklist/` | yes | 8080 | `add_anda_parenteral_dosage_checklist` |
| `/ratools/anda/add_anda_semi_solid_topical_dosage_checklist/` | yes | 8080 | `add_anda_semi_solid_topical_dosage_checklist` |
| `/ratools/anda/add_anda_solid_oral_dosage_checklist/` | yes | 8080 | `add_anda_solid_oral_dosage_checklist` |
| `/ratools/anda/add_anda_transdermal_dosage_checklist/` | yes | 8080 | `add_anda_transdermal_dosage_checklist` |
| `/ratools/anda/delete_anda_general_checklist/<id>` | **no** | 8080 | `delete_anda_general_checklist` |
| `/ratools/anda/delete_anda_liposome_checklist/<id>` | **no** | 8080 | `delete_anda_liposome_checklist` |
| `/ratools/anda/delete_anda_mdi_and_dpi_checklist/<id>` | **no** | 8080 | `delete_anda_mdi_and_dpi_checklist` |
| `/ratools/anda/delete_anda_microsphere_checklist/<id>` | **no** | 8080 | `delete_anda_microsphere_checklist` |
| `/ratools/anda/delete_anda_nasalspray_inhalation_checklist/<id>` | **no** | 8080 | `delete_anda_nasalspray_inhalation_checklist` |
| `/ratools/anda/delete_anda_ophthalmic_dosage_checklist/<id>` | **no** | 8080 | `delete_anda_ophthalmic_dosage_checklist` |
| `/ratools/anda/delete_anda_parenteral_dosage_checklist/<id>` | **no** | 8080 | `delete_anda_parenteral_dosage_checklist` |
| `/ratools/anda/delete_anda_semi_solid_topical_dosage_checklist/<id>` | **no** | 8080 | `delete_anda_semi_solid_topical_dosage_checklist` |
| `/ratools/anda/delete_anda_solid_oral_dosage_checklist/<id>` | **no** | 8080 | `delete_anda_solid_oral_dosage_checklist` |
| `/ratools/anda/delete_anda_transdermal_dosage_checklist/<id>` | **no** | 8080 | `delete_anda_transdermal_dosage_checklist` |
| `/ratools/anda/show_anda_general_report/<id>/` | yes | 8080 | `show_anda_general_report` |
| `/ratools/anda/show_anda_liposome_report/<id>/` | yes | 8080 | `show_anda_liposome_report` |
| `/ratools/anda/show_anda_mdi_and_dpi_report/<id>/` | yes | 8080 | `show_anda_mdi_and_dpi_report` |
| `/ratools/anda/show_anda_microsphere_report/<id>/` | yes | 8080 | `show_anda_microsphere_report` |
| `/ratools/anda/show_anda_nasalspray_inhalation_report/<id>/` | yes | 8080 | `show_anda_nasalspray_inhalation_report` |
| `/ratools/anda/show_anda_ophthalmic_dosage_report/<id>/` | yes | 8080 | `show_anda_ophthalmic_dosage_report` |
| `/ratools/anda/show_anda_parenteral_dosage_report/<id>/` | yes | 8080 | `show_anda_parenteral_dosage_report` |
| `/ratools/anda/show_anda_semi_solid_topical_dosage_report/<id>/` | yes | 8080 | `show_anda_semi_solid_topical_dosage_report` |
| `/ratools/anda/show_anda_solid_oral_report/<id>/` | yes | 8080 | `show_anda_solid_oral_report` |
| `/ratools/anda/show_anda_transdermal_dosage_report/<id>/` | yes | 8080 | `show_anda_transdermal_dosage_report` |
| `/ratools/baseshow/` | yes | 8080 | `` |
| `/ratools/contactus` | **no** | 8080 | `contactus` |
| `/ratools/delete_general_checklist/<id>` | **no** | 8080 | `delete_general_checklist` |
| `/ratools/delete_iig_checklist_dpi/<id>` | **no** | 8080 | `delete_iig_checklist_dpi` |
| `/ratools/delete_iig_checklist_inhalation/<id>` | **no** | 8080 | `delete_iig_checklist_inhalation` |
| `/ratools/delete_iig_checklist_injection/<id>` | **no** | 8080 | `delete_iig_checklist_injection` |
| `/ratools/delete_iig_checklist_liposome/<id>` | **no** | 8080 | `delete_iig_checklist_liposome` |
| `/ratools/delete_iig_checklist_liquidoral/<id>` | **no** | 8080 | `delete_iig_checklist_liquidoral` |
| `/ratools/delete_iig_checklist_mdi/<id>` | **no** | 8080 | `delete_iig_checklist_mdi` |
| `/ratools/delete_iig_checklist_microsphere/<id>` | **no** | 8080 | `delete_iig_checklist_microsphere` |
| `/ratools/delete_iig_checklist_nasal/<id>` | **no** | 8080 | `delete_iig_checklist_nasal` |
| `/ratools/delete_iig_checklist_semisolid/<id>` | **no** | 8080 | `delete_iig_checklist_semisolid` |
| `/ratools/delete_iig_checklist_tablet/<id>` | **no** | 8080 | `delete_iig_checklist_tablet` |
| `/ratools/delete_iig_checklist_topical/<id>` | **no** | 8080 | `delete_iig_checklist_topical` |
| `/ratools/delete_iig_checklist_transdermal/<id>` | **no** | 8080 | `delete_iig_checklist_transdermal` |
| `/ratools/delete_sss/<id>` | **no** | 8080 | `delete_sss` |
| `/ratools/dmf/delete_dmf_checklist/<id>` | **no** | 8080 | `delete_dmf_checklist` |
| `/ratools/download/<document_name>/` | yes | 8080 | `download_document` |
| `/ratools/general_white_paper_report/<id>/` | yes | 8080 | `general_white_paper_report` |
| `/ratools/general_white_paper_table` | **no** | 8080 | `general_white_paper_table` |
| `/ratools/module/` | yes | 8080 | `` |
| `/ratools/module/download-folder/` | yes | 8080 | `download_folder_zip` |
| `/ratools/module/open-file/` | yes | 8080 | `open_file` |
| `/ratools/modulehome/` | yes | 8080 | `` |
| `/ratools/requestdemo` | **no** | 8080 | `` |
| `/ratools/requestdemo/availability` | **no** | 8080 | `requestdemo_availability` |
| `/ratools/requestdemo/manage/<token>/` | yes | 8080 | `requestdemo_manage` |
| `/ratools/requestdemo/manage/<token>/cancel/` | yes | 8080 | `requestdemo_manage_cancel` |
| `/ratools/requestdemo/manage/<token>/reschedule/` | yes | 8080 | `requestdemo_manage_reschedule` |
| `/ratools/requestdemo/preview-email/<kind>/` | yes | 8080 | `requestdemo_preview_email` |
| `/ratools/show_anda_faciltiy` | **no** | 8080 | `show_anda_faciltiy` |
| `/ratools/show_anda_general_table` | **no** | 8080 | `` |
| `/ratools/show_anda_liposome_table` | **no** | 8080 | `` |
| `/ratools/show_anda_mdi_and_dpi_table` | **no** | 8080 | `` |
| `/ratools/show_anda_mdi_and_dpi_table/` | yes | 8080 | `` |
| `/ratools/show_anda_microsphere_table` | **no** | 8080 | `` |
| `/ratools/show_anda_nasalspray_inhalation_table` | **no** | 8080 | `` |
| `/ratools/show_anda_ophthalmic_dosage_table` | **no** | 8080 | `` |
| `/ratools/show_anda_parenteral_dosage_table` | **no** | 8080 | `` |
| `/ratools/show_anda_semi_solid_topical_dosage_table` | **no** | 8080 | `` |
| `/ratools/show_anda_solid_oral_dosage_table` | **no** | 8080 | `` |
| `/ratools/show_anda_transdermal_dosage_table` | **no** | 8080 | `` |
| `/ratools/show_api_faciltiy` | **no** | 8080 | `show_api_faciltiy` |
| `/ratools/show_api_validation_table` | **no** | 8080 | `` |
| `/ratools/show_api_verification_table` | **no** | 8080 | `` |
| `/ratools/show_controlled_correspondences_bestpractice` | **no** | 8080 | `show_controlled_correspondences_bestpractice` |
| `/ratools/show_controlled_correspondences_template` | **no** | 8080 | `show_controlled_correspondences_template` |
| `/ratools/show_dmf_report/<id>/` | yes | 8080 | `show_dmf_report` |
| `/ratools/show_dmf_table` | **no** | 8080 | `show_dmf_table` |
| `/ratools/show_drug_product_validation_table` | **no** | 8080 | `` |
| `/ratools/show_iig_dpi` | **no** | 8080 | `show_iig_dpi` |
| `/ratools/show_iig_inhalation_table` | **no** | 8080 | `show_iig_inhalation_table` |
| `/ratools/show_iig_injection_table` | **no** | 8080 | `show_iig_injection_table` |
| `/ratools/show_iig_liposome` | **no** | 8080 | `show_iig_liposome` |
| `/ratools/show_iig_liquidoral_table` | **no** | 8080 | `show_iig_liquidoral_table` |
| `/ratools/show_iig_mdi_table` | **no** | 8080 | `show_iig_mdi_table` |
| `/ratools/show_iig_microsphere` | **no** | 8080 | `show_iig_microsphere` |
| `/ratools/show_iig_nasal_table` | **no** | 8080 | `show_iig_nasal_table` |
| `/ratools/show_iig_proportionality_clearance_report/<id>/` | yes | 8080 | `show_iig_proportionality_clearance_report` |
| `/ratools/show_iig_semisolid_table` | **no** | 8080 | `show_iig_semisolid_table` |
| `/ratools/show_iig_tablet_table` | **no** | 8080 | `show_iig_tablet_table` |
| `/ratools/show_iig_topical_table` | **no** | 8080 | `show_iig_topical_table` |
| `/ratools/show_iig_transdermal_table` | **no** | 8080 | `show_iig_transdermal_table` |
| `/ratools/show_sss` | **no** | 8080 | `show_sss` |
| `/ratools/show_vp_liposome_table` | **no** | 8080 | `` |
| `/ratools/show_vp_liquidorals_table` | **no** | 8080 | `` |
| `/ratools/show_vp_mdi_and_dpi_table` | **no** | 8080 | `` |
| `/ratools/show_vp_microsphere_table` | **no** | 8080 | `` |
| `/ratools/show_vp_nasal_inhalation_table` | **no** | 8080 | `` |
| `/ratools/show_vp_ophthalmic_table` | **no** | 8080 | `` |
| `/ratools/show_vp_parenteral_table` | **no** | 8080 | `` |
| `/ratools/show_vp_solidoral_table` | **no** | 8080 | `` |
| `/ratools/show_vp_topical_table` | **no** | 8080 | `` |
| `/ratools/show_vp_transdermal_table` | **no** | 8080 | `` |
| `/ratools/size_shape_score_report/<id>/` | yes | 8080 | `size_shape_score_report` |
| `/ratools/validation/add_api_validation_checklist/` | yes | 8080 | `add_api_validation_checklist` |
| `/ratools/validation/add_api_verification_checklist/` | yes | 8080 | `add_api_verification_checklist` |
| `/ratools/validation/add_drug_product_validation_checklist/` | yes | 8080 | `add_drug_product_validation_checklist` |
| `/ratools/validation/delete_api_validation_checklist/<id>` | **no** | 8080 | `delete_api_validation_checklist` |
| `/ratools/validation/delete_api_verification_checklist/<id>` | **no** | 8080 | `delete_api_verification_checklist` |
| `/ratools/validation/delete_drug_product_validation_checklist/<id>` | **no** | 8080 | `delete_drug_product_validation_checklist` |
| `/ratools/validation/show_api_validation_report/<id>/` | yes | 8080 | `show_api_validation_report` |
| `/ratools/validation/show_api_verification_report/<id>/` | yes | 8080 | `show_api_verification_report` |
| `/ratools/validation/show_drug_product_validation_report/<id>/` | yes | 8080 | `show_drug_product_validation_report` |
| `/ratools/view_general_white_paper_sample` | **no** | 8080 | `view_general_white_paper_sample` |
| `/ratools/view_sample_anda_checklist/<report_name>` | **no** | 8080 | `view_sample_anda_checklist` |
| `/ratools/view_sample_dmf` | **no** | 8080 | `view_sample_dmf` |
| `/ratools/view_sample_iig_reports/<report_name>` | **no** | 8080 | `view_sample_iig_reports` |
| `/ratools/view_sample_sss` | **no** | 8080 | `view_sample_sss` |
| `/ratools/view_sample_validation_report/<report_name>` | **no** | 8080 | `view_sample_validation_report` |
| `/ratools/view_sample_vp_report/<report_name>` | **no** | 8080 | `view_sample_vp_report` |
| `/ratools/vp/add_vp_liposome_checklist/` | yes | 8080 | `add_vp_liposome_checklist` |
| `/ratools/vp/add_vp_liquidorals_checklist/` | yes | 8080 | `add_vp_liquidorals_checklist` |
| `/ratools/vp/add_vp_mdi_and_dpi_checklist/` | yes | 8080 | `add_vp_mdi_and_dpi_checklist` |
| `/ratools/vp/add_vp_microsphere_checklist/` | yes | 8080 | `add_vp_microsphere_checklist` |
| `/ratools/vp/add_vp_nasal_inhalation_checklist/` | yes | 8080 | `add_vp_nasal_inhalation_checklist` |
| `/ratools/vp/add_vp_ophthalmic_checklist/` | yes | 8080 | `add_vp_ophthalmic_checklist` |
| `/ratools/vp/add_vp_parenteral_checklist/` | yes | 8080 | `add_vp_parenteral_checklist` |
| `/ratools/vp/add_vp_solidoral_checklist/` | yes | 8080 | `add_vp_solidoral_checklist` |
| `/ratools/vp/add_vp_topical_checklist/` | yes | 8080 | `add_vp_topical_checklist` |
| `/ratools/vp/add_vp_transdermal_checklist/` | yes | 8080 | `add_vp_transdermal_checklist` |
| `/ratools/vp/delete_vp_liposome_checklist/<id>` | **no** | 8080 | `delete_vp_liposome_checklist` |
| `/ratools/vp/delete_vp_liquidorals_checklist/<id>` | **no** | 8080 | `delete_vp_liquidorals_checklist` |
| `/ratools/vp/delete_vp_mdi_and_dpi_checklist/<id>` | **no** | 8080 | `delete_vp_mdi_and_dpi_checklist` |
| `/ratools/vp/delete_vp_microsphere_checklist/<id>` | **no** | 8080 | `delete_vp_microsphere_checklist` |
| `/ratools/vp/delete_vp_nasal_inhalation_checklist/<id>` | **no** | 8080 | `delete_vp_nasal_inhalation_checklist` |
| `/ratools/vp/delete_vp_ophthalmic_checklist/<id>` | **no** | 8080 | `delete_vp_ophthalmic_checklist` |
| `/ratools/vp/delete_vp_parenteral_checklist/<id>` | **no** | 8080 | `delete_vp_parenteral_checklist` |
| `/ratools/vp/delete_vp_solidoral_checklist/<id>` | **no** | 8080 | `delete_vp_solidoral_checklist` |
| `/ratools/vp/delete_vp_topical_checklist/<id>` | **no** | 8080 | `delete_vp_topical_checklist` |
| `/ratools/vp/delete_vp_transdermal_checklist/<id>` | **no** | 8080 | `delete_vp_transdermal_checklist` |
| `/ratools/vp/show_vp_liposome_report/<id>/` | yes | 8080 | `show_vp_liposome_report` |
| `/ratools/vp/show_vp_liquidorals_report/<id>/` | yes | 8080 | `show_vp_liquidorals_report` |
| `/ratools/vp/show_vp_mdi_and_dpi_report/<id>/` | yes | 8080 | `show_vp_mdi_and_dpi_report` |
| `/ratools/vp/show_vp_microsphere_report/<id>/` | yes | 8080 | `show_vp_microsphere_report` |
| `/ratools/vp/show_vp_nasal_inhalation_report/<id>/` | yes | 8080 | `show_vp_nasal_inhalation_report` |
| `/ratools/vp/show_vp_ophthalmic_report/<id>/` | yes | 8080 | `show_vp_ophthalmic_report` |
| `/ratools/vp/show_vp_parenteral_report/<id>/` | yes | 8080 | `show_vp_parenteral_report` |
| `/ratools/vp/show_vp_solidoral_report/<id>/` | yes | 8080 | `show_vp_solidoral_report` |
| `/ratools/vp/show_vp_topical_report/<id>/` | yes | 8080 | `show_vp_topical_report` |
| `/ratools/vp/show_vp_transdermal_report/<id>/` | yes | 8080 | `show_vp_transdermal_report` |

## AIDatabase  (87 routes)

| URL | Trailing slash | Port | View name |
|---|---|---|---|
| `/aidatabase/` | yes | 8080 | `` |
| `/aidatabase/ai_master_base/` | yes | 8080 | `ai_master_base` |
| `/aidatabase/anda/ectd_acceptance_deficiency/` | yes | 8080 | `` |
| `/aidatabase/anda/injectable_general_deficiency/` | yes | 8080 | `` |
| `/aidatabase/anda/injectable_peptide_deficiency/` | yes | 8080 | `` |
| `/aidatabase/anda/iud_deficiency/` | yes | 8080 | `` |
| `/aidatabase/anda/liquid_oral_deficiency/` | yes | 8080 | `` |
| `/aidatabase/anda/nasal_spray_deficiency/` | yes | 8080 | `` |
| `/aidatabase/anda/ophthalmic_deficiency/` | yes | 8080 | `` |
| `/aidatabase/anda/otic_deficiency/` | yes | 8080 | `` |
| `/aidatabase/anda/solid_oral_deficiency/` | yes | 8080 | `` |
| `/aidatabase/anda/suppository_deficiency/` | yes | 8080 | `` |
| `/aidatabase/anda/tdds-deficiency/` | yes | 8080 | `` |
| `/aidatabase/anda/technical_acceptance_deficiency/` | yes | 8080 | `` |
| `/aidatabase/anda/topicals_deficiency/` | yes | 8080 | `` |
| `/aidatabase/anda_category_deficicency_count_pie/` | yes | 8080 | `anda_category_deficicency_count_pie` |
| `/aidatabase/anda_deficicency_count_pie/` | yes | 8080 | `anda_deficicency_count_pie` |
| `/aidatabase/anda_dosage_count_pie/` | yes | 8080 | `anda_dosage_count_pie` |
| `/aidatabase/auditiq/` | yes | 8080 | `auditiq_dashboard` |
| `/aidatabase/bar-chart-category-vs-deficiency/` | yes | 8080 | `bar_chart_category_vs_deficiency` |
| `/aidatabase/bar-chart-cmc-section/` | yes | 8080 | `bar_chart_cmc_section` |
| `/aidatabase/bar-chart-main-category/` | yes | 8080 | `bar_chart_main_category` |
| `/aidatabase/checked-updates/` | yes | 8080 | `checked_updates` |
| `/aidatabase/company_object/` | yes | 8080 | `company_object` |
| `/aidatabase/form483/` | yes | 8080 | `` |
| `/aidatabase/form483_database` | **no** | 8080 | `` |
| `/aidatabase/get_anda_bubble_data/` | yes | 8080 | `get_anda_bubble_data` |
| `/aidatabase/get_anda_chart_data/` | yes | 8080 | `get_anda_chart_data` |
| `/aidatabase/get_major_cr_bubble_data/` | yes | 8080 | `get_major_cr_bubble_data` |
| `/aidatabase/get_major_cr_chart_data/` | yes | 8080 | `get_major_cr_chart_data` |
| `/aidatabase/gmpc/active-country-excels/` | yes | 8080 | `gmpc_active_country_excels` |
| `/aidatabase/gmpc/filter-options/` | yes | 8080 | `gmpc_filter_options_api` |
| `/aidatabase/gmpc_dashboard/` | yes | 8080 | `gmpc_dashboard` |
| `/aidatabase/gmpc_module/` | yes | 8080 | `gmpc_module` |
| `/aidatabase/inspection_hub/` | yes | 8080 | `inspection_hub` |
| `/aidatabase/investigator-detail-insights/` | yes | 8080 | `investigator_detail_insights` |
| `/aidatabase/investigator_insights/` | yes | 8080 | `investigator_insights` |
| `/aidatabase/issuing_office_list/` | yes | 8080 | `issuing_office_list` |
| `/aidatabase/list_of_company/` | yes | 8080 | `list_of_company` |
| `/aidatabase/list_of_country/` | yes | 8080 | `list_of_country` |
| `/aidatabase/list_of_establishments/` | yes | 8080 | `list_of_establishments` |
| `/aidatabase/list_of_fei_numbers/` | yes | 8080 | `list_of_fei_numbers` |
| `/aidatabase/list_of_investigators/` | yes | 8080 | `list_of_investigators` |
| `/aidatabase/list_of_organization_names/` | yes | 8080 | `list_of_organization_names` |
| `/aidatabase/list_of_systems/` | yes | 8080 | `list_of_systems` |
| `/aidatabase/list_of_years/` | yes | 8080 | `list_of_years` |
| `/aidatabase/major_cr_bar_chart_category_vs_deficiency/` | yes | 8080 | `major_cr_bar_chart_category_vs_deficiency` |
| `/aidatabase/major_cr_bar_chart_cmc_section/` | yes | 8080 | `major_cr_bar_chart_cmc_section` |
| `/aidatabase/major_cr_base/` | yes | 8080 | `major_cr_base` |
| `/aidatabase/major_cr_category_deficicency_count_pie/` | yes | 8080 | `major_cr_category_deficicency_count_pie` |
| `/aidatabase/major_cr_deficicency_count_pie/` | yes | 8080 | `major_cr_deficicency_count_pie` |
| `/aidatabase/major_cr_pie_chart_dosage_form/` | yes | 8080 | `major_cr_pie_chart_dosage_form` |
| `/aidatabase/majorcr/injectable_general_deficiency/` | yes | 8080 | `` |
| `/aidatabase/majorcr/injectable_peptide_deficiency/` | yes | 8080 | `` |
| `/aidatabase/majorcr/iud_deficiency/` | yes | 8080 | `` |
| `/aidatabase/majorcr/liquid_oral_deficiency/` | yes | 8080 | `` |
| `/aidatabase/majorcr/nasal_spray_deficiency/` | yes | 8080 | `` |
| `/aidatabase/majorcr/ophthalmic_deficiency/` | yes | 8080 | `` |
| `/aidatabase/majorcr/otic_deficiency/` | yes | 8080 | `` |
| `/aidatabase/majorcr/solid_oral_deficiency/` | yes | 8080 | `` |
| `/aidatabase/majorcr/suppository_deficiency/` | yes | 8080 | `` |
| `/aidatabase/majorcr/tdds-deficiency/` | yes | 8080 | `` |
| `/aidatabase/majorcr/topicals_deficiency/` | yes | 8080 | `` |
| `/aidatabase/new_investigator/` | yes | 8080 | `new_investigator` |
| `/aidatabase/particular_investigator/` | yes | 8080 | `particular_investigator` |
| `/aidatabase/pie-chart-category-of-deficiency/` | yes | 8080 | `pie_chart_category_of_deficiency` |
| `/aidatabase/pie-chart-deficiency-type/` | yes | 8080 | `pie_chart_deficiency_type` |
| `/aidatabase/pie-chart-main-category/` | yes | 8080 | `pie_chart_main_category` |
| `/aidatabase/playbook/` | yes | 8080 | `playbook` |
| `/aidatabase/render_company_name/` | yes | 8080 | `render_company_name` |
| `/aidatabase/render_gmpc_search/` | yes | 8080 | `render_gmpc_search` |
| `/aidatabase/render_investigator/` | yes | 8080 | `render_investigator` |
| `/aidatabase/render_system_checklist/` | yes | 8080 | `render_system_checklist` |
| `/aidatabase/render_systempage/` | yes | 8080 | `render_systempage` |
| `/aidatabase/render_top20recurring_detail/` | yes | 8080 | `render_top20recurring_detail` |
| `/aidatabase/render_warning_letter/` | yes | 8080 | `render_warning_letter` |
| `/aidatabase/render_yearofinspection/` | yes | 8080 | `render_yearofinspection` |
| `/aidatabase/section_inspection/` | yes | 8080 | `section_inspection` |
| `/aidatabase/system_checklist/` | yes | 8080 | `system_checklist` |
| `/aidatabase/top10_companies/` | yes | 8080 | `top10_companies` |
| `/aidatabase/top10_investigators/` | yes | 8080 | `top10_investigators` |
| `/aidatabase/top20_recurring/` | yes | 8080 | `india_manufacturer` |
| `/aidatabase/updates-data/` | yes | 8080 | `updates_data` |
| `/aidatabase/usfda_guideline/` | yes | 8080 | `usfda_guideline` |
| `/aidatabase/warning_letter/` | yes | 8080 | `warning_letter` |
| `/aidatabase/warning_letter_company/` | yes | 8080 | `warning_letter_company` |
| `/aidatabase/warning_letter_data/` | yes | 8080 | `warning_letter_data` |

## AdminMaster  (84 routes)

| URL | Trailing slash | Port | View name |
|---|---|---|---|
| `/adminmaster/` | yes | 8080 + 8090 | `` |
| `/adminmaster/add_anda_general/` | yes | 8080 + 8090 | `add_anda_general` |
| `/adminmaster/add_anda_mdi_and_dpi/` | yes | 8080 + 8090 | `add_anda_mdi_and_dpi` |
| `/adminmaster/add_anda_nasalspray_inhalation_report/` | yes | 8080 + 8090 | `add_anda_nasalspray_inhalation_report` |
| `/adminmaster/add_anda_ophthalmic_dosage/` | yes | 8080 + 8090 | `add_anda_ophthalmic_dosage` |
| `/adminmaster/add_anda_parenteral_dosage/` | yes | 8080 + 8090 | `add_anda_parenteral_dosage` |
| `/adminmaster/add_anda_semi_solid_topical_dosage/` | yes | 8080 + 8090 | `add_anda_semi_solid_topical_dosage` |
| `/adminmaster/add_anda_solid_oral_dosage/` | yes | 8080 + 8090 | `add_anda_solid_oral_dosage` |
| `/adminmaster/add_anda_transdermal_dosage/` | yes | 8080 + 8090 | `add_anda_transdermal_dosage` |
| `/adminmaster/add_dmf_review/` | yes | 8080 + 8090 | `add_dmf_review` |
| `/adminmaster/add_dmfca_question/` | yes | 8080 + 8090 | `add_dmfca_question` |
| `/adminmaster/add_general_white_papers/` | yes | 8080 + 8090 | `add_general_white_papers` |
| `/adminmaster/add_user` | **no** | 8090 only | `add_user` |
| `/adminmaster/add_vp_liquidorals/` | yes | 8080 + 8090 | `add_vp_liquidorals` |
| `/adminmaster/add_vp_mdi_and_dpi/` | yes | 8080 + 8090 | `add_vp_mdi_and_dpi` |
| `/adminmaster/add_vp_nasal_inhalation/` | yes | 8080 + 8090 | `add_vp_nasal_inhalation` |
| `/adminmaster/add_vp_ophthalmic/` | yes | 8080 + 8090 | `add_vp_ophthalmic` |
| `/adminmaster/add_vp_parenteral/` | yes | 8080 + 8090 | `add_vp_parenteral` |
| `/adminmaster/add_vp_solidoral/` | yes | 8080 + 8090 | `add_vp_solidoral` |
| `/adminmaster/add_vp_topical/` | yes | 8080 + 8090 | `add_vp_topical` |
| `/adminmaster/add_vp_transdermal/` | yes | 8080 + 8090 | `add_vp_transdermal` |
| `/adminmaster/adminbase` | **no** | 8090 (8080 redirects here) | `` |
| `/adminmaster/delete_anda_general/<id>` | **no** | 8080 + 8090 | `delete_anda_general` |
| `/adminmaster/delete_anda_mdi_and_dpit/<id>` | **no** | 8080 + 8090 | `delete_anda_mdi_and_dpit` |
| `/adminmaster/delete_anda_nasalspray_inhalation_report/<id>` | **no** | 8080 + 8090 | `delete_anda_nasalspray_inhalation_report` |
| `/adminmaster/delete_anda_ophthalmic_dosage/<id>` | **no** | 8080 + 8090 | `delete_anda_ophthalmic_dosage` |
| `/adminmaster/delete_anda_parenteral_dosage/<id>` | **no** | 8080 + 8090 | `delete_anda_parenteral_dosage` |
| `/adminmaster/delete_anda_semi_solid_topical_dosage/<id>` | **no** | 8080 + 8090 | `delete_anda_semi_solid_topical_dosage` |
| `/adminmaster/delete_anda_solid_oral_dosage/<id>` | **no** | 8080 + 8090 | `delete_anda_solid_oral_dosage` |
| `/adminmaster/delete_anda_transdermal_dosage/<id>` | **no** | 8080 + 8090 | `delete_anda_transdermal_dosage` |
| `/adminmaster/delete_dmf_review/<id>` | **no** | 8080 + 8090 | `delete_dmf_review` |
| `/adminmaster/delete_dmfca_question/<id>` | **no** | 8080 + 8090 | `delete_dmfca_question` |
| `/adminmaster/delete_general_white_papers/<id>` | **no** | 8080 + 8090 | `delete_general_white_papers` |
| `/adminmaster/delete_user/<id>` | **no** | 8090 only | `` |
| `/adminmaster/delete_vp_liquidorals/<id>` | **no** | 8080 + 8090 | `delete_vp_liquidorals` |
| `/adminmaster/delete_vp_mdi_and_dpi/<id>` | **no** | 8080 + 8090 | `delete_vp_mdi_and_dpi` |
| `/adminmaster/delete_vp_nasal_inhalation/<id>` | **no** | 8080 + 8090 | `delete_vp_nasal_inhalation` |
| `/adminmaster/delete_vp_ophthalmic/<id>` | **no** | 8080 + 8090 | `delete_vp_ophthalmic` |
| `/adminmaster/delete_vp_parenteral/<id>` | **no** | 8080 + 8090 | `delete_vp_parenteral` |
| `/adminmaster/delete_vp_solidoral/<id>` | **no** | 8080 + 8090 | `delete_vp_solidoral` |
| `/adminmaster/delete_vp_topical/<id>` | **no** | 8080 + 8090 | `delete_vp_topical` |
| `/adminmaster/delete_vp_transdermal/<id>` | **no** | 8080 + 8090 | `delete_vp_transdermal` |
| `/adminmaster/edit_anda_general/<id>` | **no** | 8080 + 8090 | `edit_anda_general` |
| `/adminmaster/edit_anda_mdi_and_dpi/<id>` | **no** | 8080 + 8090 | `edit_anda_mdi_and_dpi` |
| `/adminmaster/edit_anda_nasalspray_inhalation_report/<id>` | **no** | 8080 + 8090 | `edit_anda_nasalspray_inhalation_report` |
| `/adminmaster/edit_anda_ophthalmic_dosage/<id>` | **no** | 8080 + 8090 | `edit_anda_ophthalmic_dosage` |
| `/adminmaster/edit_anda_parenteral_dosage/<id>` | **no** | 8080 + 8090 | `edit_anda_parenteral_dosage` |
| `/adminmaster/edit_anda_semi_solid_topical_dosage/<id>` | **no** | 8080 + 8090 | `edit_anda_semi_solid_topical_dosage` |
| `/adminmaster/edit_anda_solid_oral_dosage/<id>` | **no** | 8080 + 8090 | `edit_anda_solid_oral_dosage` |
| `/adminmaster/edit_anda_transdermal_dosage/<id>` | **no** | 8080 + 8090 | `edit_anda_transdermal_dosage` |
| `/adminmaster/edit_dmf_review/<id>` | **no** | 8080 + 8090 | `edit_dmf_review` |
| `/adminmaster/edit_dmfca_question/<id>` | **no** | 8080 + 8090 | `edit_dmfca_question` |
| `/adminmaster/edit_general_white_papers/<id>` | **no** | 8080 + 8090 | `edit_general_white_papers` |
| `/adminmaster/edit_user/<id>` | **no** | 8090 only | `edit_user` |
| `/adminmaster/edit_vp_liquidorals/<id>` | **no** | 8080 + 8090 | `edit_vp_liquidorals` |
| `/adminmaster/edit_vp_mdi_and_dpi/<id>` | **no** | 8080 + 8090 | `edit_vp_mdi_and_dpi` |
| `/adminmaster/edit_vp_nasal_inhalation/<id>` | **no** | 8080 + 8090 | `edit_vp_nasal_inhalation` |
| `/adminmaster/edit_vp_ophthalmic/<id>` | **no** | 8080 + 8090 | `edit_vp_ophthalmic` |
| `/adminmaster/edit_vp_parenteral/<id>` | **no** | 8080 + 8090 | `edit_vp_parenteral` |
| `/adminmaster/edit_vp_solidoral/<id>` | **no** | 8080 + 8090 | `edit_vp_solidoral` |
| `/adminmaster/edit_vp_topical/<id>` | **no** | 8080 + 8090 | `edit_vp_topical` |
| `/adminmaster/edit_vp_transdermal/<id>` | **no** | 8080 + 8090 | `edit_vp_transdermal` |
| `/adminmaster/login/` | yes | 8080 + 8090 | `login` |
| `/adminmaster/logout/` | yes | 8080 + 8090 | `logout` |
| `/adminmaster/show_anda_general_table` | **no** | 8080 + 8090 | `show_anda_general_table` |
| `/adminmaster/show_anda_mdi_dpi` | **no** | 8080 + 8090 | `show_anda_mdi_dpi` |
| `/adminmaster/show_anda_nasalspray_inhalation_checklist` | **no** | 8080 + 8090 | `show_anda_nasalspray_inhalation_checklist` |
| `/adminmaster/show_anda_ophthalmic_dosage_table` | **no** | 8080 + 8090 | `show_anda_ophthalmic_dosage_table` |
| `/adminmaster/show_anda_parenteral_dosage_table` | **no** | 8080 + 8090 | `show_anda_parenteral_dosage_table` |
| `/adminmaster/show_anda_semi_solid_topical_dosage_table` | **no** | 8080 + 8090 | `show_anda_semi_solid_topical_dosage_table` |
| `/adminmaster/show_anda_solid_oral_dosage_table` | **no** | 8080 + 8090 | `show_anda_solid_oral_dosage_table` |
| `/adminmaster/show_anda_transdermal_dosage_table` | **no** | 8080 + 8090 | `show_anda_transdermal_dosage_table` |
| `/adminmaster/show_dmf_review_table` | **no** | 8080 + 8090 | `show_dmf_review_table` |
| `/adminmaster/show_dmfca_table` | **no** | 8080 + 8090 | `show_dmfca_table` |
| `/adminmaster/show_general_white_papers_table` | **no** | 8080 + 8090 | `show_general_white_papers_table` |
| `/adminmaster/show_vp_liquidorals_table` | **no** | 8080 + 8090 | `show_vp_liquidorals_table` |
| `/adminmaster/show_vp_mdi_dpi` | **no** | 8080 + 8090 | `show_vp_mdi_dpi` |
| `/adminmaster/show_vp_nasal_inhalation` | **no** | 8080 + 8090 | `show_vp_nasal_inhalation` |
| `/adminmaster/show_vp_ophthalmic` | **no** | 8080 + 8090 | `show_vp_ophthalmic` |
| `/adminmaster/show_vp_parenteral_table` | **no** | 8080 + 8090 | `show_vp_parenteral_table` |
| `/adminmaster/show_vp_solidoral_table` | **no** | 8080 + 8090 | `show_vp_solidoral_table` |
| `/adminmaster/show_vp_topical_table` | **no** | 8080 + 8090 | `show_vp_topical_table` |
| `/adminmaster/show_vp_transdermal_table` | **no** | 8080 + 8090 | `show_vp_transdermal_table` |
| `/adminmaster/view_users` | **no** | 8090 only | `view_users` |

