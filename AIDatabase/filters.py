import django_filters
from django.db.models import Q
from .models import *
from django import forms
from django import forms
from django_filters import DateFilter
import logging
import openai
import json
import re

logger = logging.getLogger(__name__)

_openai_client = None


def _get_openai_client():
    """
    Lazily build an openai>=1.0 client.

    The module-level openai.api_key assignment below is the legacy (<1.0) way
    of configuring the SDK and does nothing for the current client; read it
    here so the configured key is still honoured without changing where the
    key comes from.
    """
    global _openai_client
    if _openai_client is None:
        api_key = getattr(openai, "api_key", None)
        if not api_key:
            return None
        _openai_client = openai.OpenAI(api_key=api_key)
    return _openai_client

# openai.api_key = "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"
# openai.api_key = "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"
# client = openai.OpenAI(api_key="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")  # Replace with your actual OpenAI API key
openai.api_key = "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"
def get_synonyms_from_chatgpt(query):
    # print("query",query)
    prompt = f"""You are a helpful assistant that helps extract keywords, synonyms, and related terms from a user's input query. The keywords should be suitable for searching data in a database.

            For the input query, provide a list of:
            1. Relevant keywords from the query.
            2. Synonyms of those keywords.
            3. Related terms or concepts.

            Input Query: "{query}"

            If the words like this is present in the query : ['Capsules', 'Tablets', 'Vaginal Inserts', 'Injection', 'ER Tablets', 'Oral Suspension', 'Nasal Spray', 'Gel', 'Transdermal', 'ER Oral Suspension', 'DR Capsules', 'Oral Liquid', 'Nasal Spray', 'Solid Oral Tablet', 'Solid Oral Capsule', 'Topical ', 'Vaginal ', 'Injection', 'Transdermal','Nasal Spray'],
            return me the list under the name "dosage"
            If the words like this is present in the query: ['CMC', 'Clinical', 'clinical', 'CMC/ Clinical', ' Clinical', ' Solution', 'Solution', ' Suspension', 'Suspension', 'Sublingual Tablet', 'IR Tablet', 'DR Tablet', 'ER Tablet', 'IR Capsule', 'Ointment', 'ER Capsule', ' Insert', 'Dry Powder', 'Lyo', ' Gel', 'Gel', 'Patch', 'Cream','Nasal Spray', 'Powder for Oral Suspension', 'Oral Solution', 'ER Oral Suspension', 'Oral Suspension', 'Powder for Oral Solution', 'Vaginal ring', 'Topical Patch', 'Transdermal Patch', 'Suppository', 'Ointment', ' Solution', ' Gel', 'Cream', 'ER Capsules', 'ER Tablets', 'IR Tablets', 'IR Capsules', 'DR Tablets', ' ER Tablets', 'Sublingual Tablets', 'DR Capsules', 'Chewable Tablets', 'Otic', ' Ophthalmic ', 'Injectable', 'General Injectable ']
            return me the list under the name "cmc"
            If the words like this is present in the query: ['Drug Product', 'Drug Substance', 'Microbiology', 'QOS', 'Drug Product ', 'Process ', 'Drug Substance ', 'Bioequivalence (Module 5)', 'Biopharmaceutics', 'Drug substance']
            return me the list under the name "type_of_dosage"
            If the words like this is present in the query: ['Hyperlink/Bookmark', 'Legibility/Page Orientation', 'ICH M4 - CTD Structure', 'PDF Properties', 'STF / SAS / XPT', 'Organization/Format', 'File Naming', 'Publishing', '356h Form', 'Drug Product', '3455 Form', 'Administrative', 'Labeling', 'Bioequivalence', 'Drug Substance', 'Drug Substance/ Drug Product', '3674 Form','Administrative & Facilities', 'Stability (32P8)', 'BE & In-Vitro', 'General Property/ Administrative', 'Specification & CoA (32S41 & 32S44)', 'Components & Composition (3.2.P.1)', 'Method & Valdation (32P52 & 32P53)', 'Drug-Device', 'Characterization & Justification', 'Produc Development Report (32P2)', 'Manufacturing Process/ Scale-up', 'ANDA Exhibit Batch (32R)', 'In-Process Controls', 'Specification & CoA (32P51 & 32P54)', 'Container/Closure (3.2.P.7)', 'Microbiology', 'Product Development Report (32P2)', 'QOS (Module 2.3)', 'Excipients', 'Method & Valdation (32S42 & 32S43)', 'Reference Std', 'Process Validation', 'Bio', 'Drug Substance- Physico-Chemical Property', 'Charaterization/& Justification', 'Specification/CoA', 'Tablets', 'Container/Closure (32P7)', 'Stability', 'Components & Composition (32P1)', 'Dissolution', 'Reference Standard', 'Administrative/ Facilities', 'Drug substance- physico-Chemical Property', 'Drug Substance- General', 'Elemental Impurities', 'Polymorphism', 'Extractable /Leachable', 'DMF', 'Method &Valdation (32S42 & 32S43)', 'General/Administrative', 'Product Development Report-32P2', 'Characterization/Justification', 'Facility', 'Method &Valdation (32P52 & 32P53)', 'Drug - Device', 'Specification & CoA (32P51 &32P54)', 'ANDA Batch/ Reconciliation / 32R', 'Bioequivelence ', 'Component &Compostion (32P1)', 'Batch Formula', 'Compatibility Protocol ', 'Extactable / Leatchable ', 'Specification/CoA (32P541 & 32P544)', 'Stability -32P8', 'Components/ Composition (32P1)', 'Excipients (32P4)', 'Container/Closure', 'container/Closure', 'Extractable/Leachables', 'Specification/CoA (32P51 & 32P54)', 'Drug Substance - General', ' Specification/CoA (32S41 & 32S44)', 'Reference Standard (32S4)', 'Reference Standard (32P56)', 'Container/Closure (32S6)', 'Bioequivalence', 'Labeling', ' Elemental Impurities', 'administrative/ Facilities', 'Manufacturing Process/Scale-up', 'Specification/CoA (32P541 &32P544)', 'PDR-QbD (Development Report) - 32P2', 'Specification & CoA (32S41 &32S44)', 'Stability (32S7)', 'Components/ Composition', 'Drug- Device']
            return me the list under the name "deficiency"
            If the words like this is present in the query: ['DRL', 'Minor CR', 'Major CR', 'IR']
            return me the list under the name "category"
            Provide your response in this exact JSON format:
            {{"keywords": [], "synonyms": [], "related_terms": [], "dosage": [], "cmc": [], "deficiency":[] , "category":[], "type_of_dosage": [] }}
            """

    try:
        client = _get_openai_client()
        if client is None:
            logger.warning("OpenAI API key is not configured; skipping synonym expansion.")
            return [], [], [], [], [], []

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.7
        )
        # print("try..............,",response)

        # content = response['choices'][0]['message']['content']
        content = response.choices[0].message.content
        # print("Raw GPT response:", content)  # Debug print

        # Find the JSON object in the response
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        # print("\n\n>>>Json",json_match)
        if json_match:
            # print("\n\n>>>Json after",json_match)
            json_str = json_match.group()
            # Clean up the string
            json_str = json_str.replace("'", '"').replace('\n', '').strip()
            data = json.loads(json_str)

            # print("Data ======> ",data)
            # Combine all terms for searching
            search_terms = set()
            dosage_terms = set()
            cmc_terms = set()
            deficiency_terms = set()
            category_terms = set()
            type_of_dosage_terms = set()

            search_terms.update(data.get('keywords', []))
            search_terms.update(data.get('synonyms', []))
            search_terms.update(data.get('related_terms', []))

            dosage_terms.update(data.get('dosage',[]))
            cmc_terms.update(data.get('cmc',[]))
            deficiency_terms.update(data.get('deficiency',[]))
            category_terms.update(data.get('category',[]))
            type_of_dosage_terms.update(data.get('type_of_dosage',[]))
            # print("Extracted search terms:", list(search_terms))  # Debug print
            return list(search_terms),list(dosage_terms),list(cmc_terms),list(deficiency_terms),list(category_terms),list(type_of_dosage_terms)
        else:
            # print("Else>.....")
            # print("No JSON object found in response")
            return [],[],[],[],[],[]

    except Exception:
        logger.exception("Failed to expand search query via OpenAI; falling back to literal search.")
        return [],[],[],[],[],[]

# class ANDAFilter(django_filters.FilterSet):
#     dosage_form = django_filters.ChoiceFilter(
#         field_name='dosage_form',
#         label='Dosage Form',
#         empty_label="Select Dosage Form"
#     )
#     cmc_section = django_filters.ChoiceFilter(
#         field_name='cmc_section',
#         label='CMC Section',
#         empty_label="Select CMC Section"
#     )
#     deficiency_type = django_filters.ChoiceFilter(
#         field_name='deficiency_type',
#         label='Deficiency Type',
#         empty_label="Select Deficiency Type"
#     )
#     category_of_deficiency = django_filters.ChoiceFilter(
#         field_name='category_of_deficiency',
#         label='Category of Deficiency',
#         empty_label="Select Category of Deficiency"
#     )
#     search_deficiency = django_filters.CharFilter(
#         field_name='deficiency',
#         label='Search Deficiency',
#         method='filter_search_deficiency'
#     )

#     class Meta:
#         model = ANDA
#         fields = ['dosage_form', 'cmc_section', 'deficiency_type', 'category_of_deficiency','search_deficiency']

#     def __init__(self, *args, **kwargs):
#         main_category = kwargs.pop('main_category', None)
#         super().__init__(*args, **kwargs)

#         queryset = ANDA.objects.filter(main_cateogry=main_category) if main_category else ANDA.objects.all()

#         # Get search terms from the search_deficiency input
#         search_deficiency = self.data.get('search_deficiency')
#         if search_deficiency:
#             search_terms = get_synonyms_from_chatgpt(search_deficiency)
#             print(f"Search terms for '{search_deficiency}':", search_terms)  # Debug print

#             # Update dropdown choices based on search terms
#             self.update_dropdown_choices(queryset, search_terms)

#         # Set default dropdown choices if no search_deficiency is provided
#         else:
#             self.filters['dosage_form'].extra['choices'] = [(df, df) for df in queryset.values_list('dosage_form', flat=True).distinct()]
#             self.filters['cmc_section'].extra['choices'] = [(cmc, cmc) for cmc in queryset.values_list('cmc_section', flat=True).distinct()]
#             self.filters['deficiency_type'].extra['choices'] = [(dt, dt) for dt in queryset.values_list('deficiency_type', flat=True).distinct()]
#             self.filters['category_of_deficiency'].extra['choices'] = [(cod, cod) for cod in queryset.values_list('category_of_deficiency', flat=True).distinct()]

#         # Add CSS classes to dropdowns
#         self.filters['dosage_form'].field.widget.attrs.update({'class': 'form-select'})
#         self.filters['cmc_section'].field.widget.attrs.update({'class': 'form-select'})
#         self.filters['deficiency_type'].field.widget.attrs.update({'class': 'form-select'})
#         self.filters['category_of_deficiency'].field.widget.attrs.update({'class': 'form-select'})

#     def update_dropdown_choices(self, queryset, search_terms):
#         """
#         Update dropdown choices based on search terms.
#         """
#         # Filter queryset based on search terms across all relevant fields
#         q_objects = Q()
#         for term in search_terms:
#             q_objects |= (
#                 Q(deficiency__icontains=term) |
#                 Q(dosage_form__icontains=term) |
#                 Q(cmc_section__icontains=term) |
#                 Q(deficiency_type__icontains=term) |
#                 Q(category_of_deficiency__icontains=term)
#             )
#         filtered_queryset = queryset.filter(q_objects)

#         # Update dropdown choices
#         self.filters['dosage_form'].extra['choices'] = [(df, df) for df in filtered_queryset.values_list('dosage_form', flat=True).distinct()]
#         self.filters['cmc_section'].extra['choices'] = [(cmc, cmc) for cmc in filtered_queryset.values_list('cmc_section', flat=True).distinct()]
#         self.filters['deficiency_type'].extra['choices'] = [(dt, dt) for dt in filtered_queryset.values_list('deficiency_type', flat=True).distinct()]
#         self.filters['category_of_deficiency'].extra['choices'] = [(cod, cod) for cod in filtered_queryset.values_list('category_of_deficiency', flat=True).distinct()]

#     def filter_search_deficiency(self, queryset, name, value):
#         if not value:
#             return queryset

#         search_terms = get_synonyms_from_chatgpt(value)
#         print(f"Search terms for '{value}':", search_terms)  # Debug print

#         # Build a Q object to search across all relevant fields
#         q_objects = Q()
#         for term in search_terms:
#             q_objects |= (
#                 Q(deficiency__icontains=term) |
#                 Q(dosage_form__icontains=term) |
#                 Q(cmc_section__icontains=term) |
#                 Q(deficiency_type__icontains=term) |
#                 Q(category_of_deficiency__icontains=term)
#             )

#         # Apply dropdown filters
#         if self.data.get('dosage_form'):
#             queryset = queryset.filter(dosage_form=self.data['dosage_form'])
#         if self.data.get('cmc_section'):
#             queryset = queryset.filter(cmc_section=self.data['cmc_section'])
#         if self.data.get('deficiency_type'):
#             queryset = queryset.filter(deficiency_type=self.data['deficiency_type'])
#         if self.data.get('category_of_deficiency'):
#             queryset = queryset.filter(category_of_deficiency=self.data['category_of_deficiency'])

#         # Apply search deficiency filter
#         return queryset.filter(q_objects)


class ANDAFilter(django_filters.FilterSet):
    dosage_form = django_filters.ChoiceFilter(
        field_name='dosage_form',
        label='Dosage Form',
        empty_label="Select Dosage Type"
    )
    dosage_search = django_filters.CharFilter(
        field_name='dosage_form',
        label='Search Dosage',
        method='filter_combined_search',
        widget=forms.HiddenInput()
    )
    cmc_section = django_filters.ChoiceFilter(
        field_name='cmc_section',
        label='CMC Section',
        empty_label="Select CMC Section"
    )
    cmc_section_search = django_filters.CharFilter(
        field_name='cmc_section',
        label='Search CMC Section',
        method = 'filter_combined_search',
        widget=forms.HiddenInput()
    )
    deficiency_type = django_filters.ChoiceFilter(
        field_name='deficiency_type',
        label='Deficiency Type',
        empty_label="Select Deficiency Type"
    )
    deficiency_type_search = django_filters.CharFilter(
        field_name='deficiency_type',
        label='Search Deficiency Type',
        method='filter_combined_search',
        widget=forms.HiddenInput()  # Hide this field in the form
    )
    category_of_deficiency = django_filters.ChoiceFilter(
        field_name='category_of_deficiency',
        label='Category of Deficiency',
        empty_label="Select Category of Deficiency"
    )
    category_of_deficiency_search = django_filters.CharFilter(
        field_name='category_of_deficiency',
        label='Search Category of Deficiency Type',
        method='filter_combined_search',
        widget=forms.HiddenInput()  # Hide this field in the form
    )
    search_deficiency = django_filters.CharFilter(
        field_name='deficiency',
        label='Search Deficiency',
        method='filter_combined_search'
    )

    class Meta:
        model = ANDA
        fields = ['dosage_form', 'cmc_section', 'deficiency_type', 'category_of_deficiency','search_deficiency']

    def __init__(self, *args, **kwargs):
        main_category = kwargs.pop('main_category', None)
        super().__init__(*args, **kwargs)

        queryset = ANDA.objects.filter(main_cateogry=main_category) if main_category else ANDA.objects.all()
        # print("dosage form options",queryset.values_list('dosage_form', flat=True).distinct())
        self.filters['dosage_form'].extra['choices'] = [(df, df) for df in queryset.values_list('dosage_form', flat=True).distinct()]
        self.filters['cmc_section'].extra['choices'] = [(cmc, cmc) for cmc in queryset.values_list('cmc_section', flat=True).distinct()]
        self.filters['deficiency_type'].extra['choices'] = [(dt, dt) for dt in queryset.values_list('deficiency_type', flat=True).distinct()]
        self.filters['category_of_deficiency'].extra['choices'] = [(cod, cod) for cod in queryset.values_list('category_of_deficiency', flat=True).distinct()]

        self.filters['dosage_form'].field.widget.attrs.update({'class': 'form-select'}),
        self.filters['cmc_section'].field.widget.attrs.update({'class': 'form-select'}),
        self.filters['deficiency_type'].field.widget.attrs.update({'class': 'form-select'}),
        self.filters['category_of_deficiency'].field.widget.attrs.update({'class': 'form-select'}),


    def filter_combined_search(self, queryset, name, value):
        if not value:
            return queryset

        # Get synonyms from ChatGPT for all fields
        # print("value",value)
        # search_terms, dosage_terms, cmc_terms, deficiency_terms, category_terms, type_of_dosage_terms = get_synonyms_from_chatgpt(value)

        # Create Q objects for each field
        # dosage_q = Q()
        # cmc_section_q = Q()
        # category_of_deficiency_q = Q()
        # deficiency_type_q = Q()
        # deficiency_q = Q()

        # Populate Q objects with AND conditions
        # for term in dosage_terms:
        #     dosage_q &= Q(dosage__icontains=term)

        # for term in cmc_terms:
        #     cmc_section_q &= Q(cmc_section__icontains=term)

        # for term in deficiency_terms:
        #     deficiency_type_q &= Q(deficiency_type__icontains=term)

        # for term in category_terms:
        #     category_of_deficiency_q &= Q(category_of_deficiency__icontains=term)

        # for term in search_terms:
        #     deficiency_q |= Q(deficiency__icontains=term)
            # print("deficiency_q>>>>>>>",deficiency_q)

        # Combine all Q objects with AND operation
        # combined_q = dosage_q | cmc_section_q | category_of_deficiency_q | deficiency_type_q | deficiency_q
        # print("combined_q>>>>>",combined_q)

        # Apply the combined filter
        return queryset.filter(Q(deficiency__icontains=value))


    # def filter_search_deficiency(self, queryset, name, value):
    #     if not value:
    #         return queryset

    #     search_terms = get_synonyms_from_chatgpt(value)
    #     print(f"Search terms for '{value}':", search_terms)

    #     q_objects = Q()
    #     for term in search_terms:
    #         q_objects |= (Q(deficiency__icontains=term))

    #     return queryset.filter(q_objects)

# in one method only
class ANDAeCTDFilter(django_filters.FilterSet):
    dosage = django_filters.ChoiceFilter(
        field_name='dosage',
        label='Dosage',
        empty_label="Select Dosage",
    )
    dosage_search = django_filters.CharFilter(
        field_name='dosage',
        label='Search Dosage',
        method='filter_combined_search',
        widget=forms.HiddenInput()  # Hide this field in the form
    )
    cmc_clinic = django_filters.ChoiceFilter(
        field_name='cmc_clinic',
        label='CMC Clinical',
        empty_label="Select CMC Clinical",
    )
    cmc_clinic_search = django_filters.CharFilter(
        field_name='cmc_clinic',
        label='Search CMC Clinical',
        method='filter_combined_search',
        widget=forms.HiddenInput()  # Hide this field in the form
    )
    deficiency_type = django_filters.ChoiceFilter(
        field_name='deficiency_type',
        label='Deficiency Type',
        empty_label="Select Deficiency Type",
    )
    deficiency_type_search = django_filters.CharFilter(
        field_name='deficiency_type',
        label='Search Deficiency Type',
        method='filter_combined_search',
        widget=forms.HiddenInput()  # Hide this field in the form
    )
    search_deficiency = django_filters.CharFilter(
        field_name='deficiency',
        label='Search Deficiency',
        method='filter_combined_search'
    )

    class Meta:
        model = ANDAeCTD
        fields = ['dosage', 'cmc_clinic', 'deficiency_type', 'search_deficiency']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Populate choices for ChoiceFilters
        self.filters['dosage'].extra['choices'] = [(d, d) for d in ANDAeCTD.objects.values_list('dosage', flat=True).distinct()]
        self.filters['cmc_clinic'].extra['choices'] = [(c, c) for c in ANDAeCTD.objects.values_list('cmc_clinic', flat=True).distinct()]
        self.filters['deficiency_type'].extra['choices'] = [(dt, dt) for dt in ANDAeCTD.objects.values_list('deficiency_type', flat=True).distinct()]

        # Add CSS classes to the form fields
        self.filters['dosage'].field.widget.attrs.update({'class': 'form-select'})
        self.filters['cmc_clinic'].field.widget.attrs.update({'class': 'form-select'})
        self.filters['deficiency_type'].field.widget.attrs.update({'class': 'form-select'})

    def filter_combined_search(self, queryset, name, value):
        if not value:
            return queryset

        # Get synonyms from ChatGPT for all fields
        # search_terms, dosage_terms, cmc_terms, deficiency_terms, category_terms, type_of_dosage_terms = get_synonyms_from_chatgpt(value)

        # Create Q objects for each field
        # dosage_q = Q()
        # cmc_q = Q()
        # deficiency_type_q = Q()
        # deficiency_q = Q()

        # Populate Q objects with AND conditions
        # for term in dosage_terms:
        #     dosage_q &= Q(dosage__icontains=term)

        # for term in cmc_terms:
        #     cmc_q &= Q(cmc_clinic__icontains=term)

        # for term in deficiency_terms:
        #     deficiency_type_q &= Q(deficiency_type__icontains=term)

        # for term in search_terms:
        #     deficiency_q |= Q(deficiency__icontains=term)

        # Combine all Q objects with AND operation
        # combined_q = dosage_q | cmc_q | deficiency_type_q | deficiency_q

        # Apply the combined filter
        return queryset.filter(Q(deficiency__icontains=value))

# class ANDAeCTDFilter(django_filters.FilterSet):
#     dosage = django_filters.ChoiceFilter(
#         field_name='dosage',
#         label='Dosage',
#         empty_label="Select Dosage",
#     )
#     dosage_search = django_filters.CharFilter(
#         field_name='dosage',
#         label='Search Dosage',
#         method='filter_dosage_search',
#         widget=forms.HiddenInput()  # Hide this field in the form
#     )
#     cmc_clinic = django_filters.ChoiceFilter(
#         field_name='cmc_clinic',
#         label='CMC Clinical',
#         empty_label="Select CMC Clinical",
#     )
#     cmc_clinic_search = django_filters.CharFilter(
#         field_name='cmc_clinic',
#         label='Search CMC Clinical',
#         method='filter_cmc_clinic_search',
#         widget=forms.HiddenInput()  # Hide this field in the form
#     )
#     deficiency_type = django_filters.ChoiceFilter(
#         field_name='deficiency_type',
#         label='Deficiency Type',
#         empty_label="Select Deficiency Type",
#     )
#     deficiency_type_search = django_filters.CharFilter(
#         field_name='deficiency_type',
#         label='Search Deficiency Type',
#         method='filter_deficiency_type_search',
#         widget=forms.HiddenInput()  # Hide this field in the form
#     )
#     search_deficiency = django_filters.CharFilter(
#         field_name='deficiency',
#         label='Search Deficiency',
#         method='filter_search_deficiency_ectd'
#     )

#     class Meta:
#         model = ANDAeCTD
#         fields = ['dosage', 'cmc_clinic', 'deficiency_type', 'search_deficiency']

#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)

#         # Populate choices for ChoiceFilters
#         self.filters['dosage'].extra['choices'] = [(d, d) for d in ANDAeCTD.objects.values_list('dosage', flat=True).distinct()]
#         self.filters['cmc_clinic'].extra['choices'] = [(c, c) for c in ANDAeCTD.objects.values_list('cmc_clinic', flat=True).distinct()]
#         self.filters['deficiency_type'].extra['choices'] = [(dt, dt) for dt in ANDAeCTD.objects.values_list('deficiency_type', flat=True).distinct()]

#         # Add CSS classes to the form fields
#         self.filters['dosage'].field.widget.attrs.update({'class': 'form-select'})
#         self.filters['cmc_clinic'].field.widget.attrs.update({'class': 'form-select'})
#         self.filters['deficiency_type'].field.widget.attrs.update({'class': 'form-select'})

#     def filter_search_deficiency_ectd(self, queryset, name, value):
#         if not value:
#             return queryset

#         search_terms, _, _, _ = get_synonyms_from_chatgpt(value)
#         q_objects = Q()
#         for term in search_terms:
#             q_objects |= Q(deficiency__icontains=term)

#         return queryset.filter(q_objects)

#     def filter_dosage_search(self, queryset, name, value):
#         if not value:
#             return queryset

#         # Get synonyms and related terms for the dosage
#         _, dosage_terms, _, _ = get_synonyms_from_chatgpt(value)

#         # Create Q objects to search across dosage terms
#         q_objects = Q()
#         for term in dosage_terms:
#             q_objects |= Q(dosage__icontains=term)

#         return queryset.filter(q_objects)

#     def filter_cmc_clinic_search(self, queryset, name, value):
#         if not value:
#             return queryset

#         # Get synonyms and related terms for CMC
#         _, _, cmc_terms, _ = get_synonyms_from_chatgpt(value)

#         # Create Q objects to search across CMC terms
#         q_objects = Q()
#         for term in cmc_terms:
#             q_objects |= Q(cmc_clinic__icontains=term)

#         return queryset.filter(q_objects)

#     def filter_deficiency_type_search(self, queryset, name, value):
#         if not value:
#             return queryset

#         # Get synonyms and related terms for deficiency
#         _, _, _, deficiency_terms = get_synonyms_from_chatgpt(value)

#         # Create Q objects to search across deficiency terms
#         q_objects = Q()
#         for term in deficiency_terms:
#             q_objects |= Q(deficiency_type__icontains=term)

#         return queryset.filter(q_objects)

# class ANDAeCTDFilter(django_filters.FilterSet):
#     dosage = django_filters.ChoiceFilter(
#         field_name='dosage',
#         label='Dosage',
#         empty_label="Select Dosage",
#     )
#     cmc_clinic = django_filters.ChoiceFilter(
#         field_name='cmc_clinic',
#         label='CMC Clinical',
#         empty_label="Select CMC Clinical",
#         method='filter_cmc_clinic'
#     )
#     deficiency_type = django_filters.ChoiceFilter(
#         field_name='deficiency_type',
#         label='Deficiency Type',
#         empty_label="Select Deficiency Type",
#         method='filter_deficiency_type'
#     )
#     search_deficiency = django_filters.CharFilter(
#         field_name='deficiency',
#         label='Search Deficiency',
#         method='filter_search_deficiency_ectd'
#     )

#     class Meta:
#         model = ANDAeCTD
#         fields = ['dosage', 'cmc_clinic', 'deficiency_type','search_deficiency']

#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)

#         self.filters['dosage'].extra['choices'] = [(d, d) for d in ANDAeCTD.objects.values_list('dosage', flat=True).distinct()]
#         self.filters['cmc_clinic'].extra['choices'] = [(c, c) for c in ANDAeCTD.objects.values_list('cmc_clinic', flat=True).distinct()]
#         self.filters['deficiency_type'].extra['choices'] = [(dt, dt) for dt in ANDAeCTD.objects.values_list('deficiency_type', flat=True).distinct()]

#         self.filters['dosage'].field.widget.attrs.update({'class': 'form-select'})
#         self.filters['cmc_clinic'].field.widget.attrs.update({'class': 'form-select'})
#         self.filters['deficiency_type'].field.widget.attrs.update({'class': 'form-select'})

#     def filter_search_deficiency_ectd(self, queryset, name, value):
#         if not value:
#             return queryset

#         search_terms,_,_,_ = get_synonyms_from_chatgpt(value)
#         # print(f"Search terms for '{value}':", search_terms)  # Debug print
#         q_objects = Q()
#         for term in search_terms:
#             q_objects |=( Q(deficiency__icontains=term))

#         return queryset.filter(q_objects)

#     def filter_dosage(self, queryset, name, value):
#         if not value:
#             return queryset

#         # Get synonyms and related terms for the dosage
#         _, dosage_terms, _, _ = get_synonyms_from_chatgpt(value)

#         # Create Q objects to search across dosage terms
#         q_objects = Q()
#         for term in dosage_terms:
#             q_objects |= Q(dosage__icontains=term)
#         print("q objects", q)
#         print("dosage term ====>",queryset.filter(q_objects))
#         return queryset.filter(q_objects)

#     def filter_cmc_clinic(self, queryset, name, value):
#         if not value:
#             return queryset

#         # Get synonyms and related terms for CMC
#         _, _, cmc_terms, _ = get_synonyms_from_chatgpt(value)

#         # Create Q objects to search across CMC terms
#         q_objects = Q()
#         for term in cmc_terms:
#             q_objects |= Q(cmc_clinic__icontains=term)

#         return queryset.filter(q_objects)

#     def filter_deficiency_type(self, queryset, name, value):
#         if not value:
#             return queryset

#         # Get synonyms and related terms for deficiency
#         _, _, _, deficiency_terms = get_synonyms_from_chatgpt(value)

#         # Create Q objects to search across deficiency terms
#         q_objects = Q()
#         for term in deficiency_terms:
#             q_objects |= Q(deficiency_type__icontains=term)

#         return queryset.filter(q_objects)

class ANDATechnicalAcceptanceFilter(django_filters.FilterSet):
    dosage_form = django_filters.ChoiceFilter(
        field_name='dosage_form',
        label='Dosage Form',
        empty_label="Select Dosage Form"
    )
    dosage_search = django_filters.CharFilter(
        field_name='dosage_form',
        label='Search Dosage',
        method='filter_combined_search',
        widget=forms.HiddenInput()  # Hide this field in the form
    )
    type_of_dosage_form = django_filters.ChoiceFilter(
        field_name='type_of_dosage_form',
        label='Type of Dosage Form',
        empty_label="Select Type of Dosage Form"
    )
    type_of_dosage_form = django_filters.CharFilter(
        field_name='type_of_dosage_form',
        label='Search Type of Dosage Form',
        method='filter_combined_search',
        widget=forms.HiddenInput()  # Hide this field in the form
    )
    deficiency_type = django_filters.ChoiceFilter(
        field_name='deficiency_type',
        label='Deficiency Type',
        empty_label="Select Deficiency Type"
    )
    deficiency_type_search = django_filters.CharFilter(
        field_name='deficiency_type',
        label='Search Deficiency Type',
        method='filter_combined_search',
        widget=forms.HiddenInput()  # Hide this field in the form
    )
    search_deficiency = django_filters.CharFilter(
        field_name='deficiency',
        label='Search Deficiency',
        method='filter_combined_search'
    )

    class Meta:
        model = ANDATechnicalAcceptance
        fields = ['dosage_form', 'type_of_dosage_form', 'deficiency_type','search_deficiency']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.filters['dosage_form'].extra['choices'] = [(df, df) for df in ANDATechnicalAcceptance.objects.values_list('dosage_form', flat=True).distinct()]
        self.filters['deficiency_type'].extra['choices'] = [(dt, dt) for dt in ANDATechnicalAcceptance.objects.values_list('deficiency_type', flat=True).distinct()]

        self.filters['dosage_form'].field.widget.attrs.update({'class': 'form-select'})
        self.filters['deficiency_type'].field.widget.attrs.update({'class': 'form-select'})

    def filter_combined_search(self, queryset, name, value):
        if not value:
            return queryset

        # Get synonyms from ChatGPT for all fields
        # search_terms, dosage_terms, cmc_terms, deficiency_terms, category_terms, type_of_dosage_terms = get_synonyms_from_chatgpt(value)

        # Create Q objects for each field
        # dosage_q = Q()
        # type_of_dosage_q = Q()
        # deficiency_type_q = Q()
        # deficiency_q = Q()

        # # Populate Q objects with AND conditions
        # for term in dosage_terms:
        #     dosage_q &= Q(dosage__icontains=term)

        # for term in type_of_dosage_terms:
        #     type_of_dosage_q &= Q(type_of_dosage_form__icontains=term)

        # for term in deficiency_terms:
        #     deficiency_type_q &= Q(deficiency_type__icontains=term)

        # for term in search_terms:
        #     deficiency_q |= Q(deficiency__icontains=term)

        # Combine all Q objects with AND operation
        # combined_q = dosage_q | type_of_dosage_q | deficiency_type_q | deficiency_q

        # Apply the combined filter
        return queryset.filter(Q(deficiency__icontains=value))

    # def filter_technical_deficiecny(self, queryset, name, value):
    #     if not value:
    #         return queryset

    #     search_terms = get_synonyms_from_chatgpt(value)
    #     for term in search_terms:
    #         q_objects |= (Q(deficiency__icontains=term) |
    #             Q(dosage_form__icontains=term) |
    #             Q(type_of_dosage_form__icontains=term) |
    #             Q(deficiency_type__icontains=term)
    #         )

    #     return queryset.filter(q_objects)


class MajorCRFilter(django_filters.FilterSet):
    dosage_form = django_filters.ChoiceFilter(
        field_name='dosage_form',
        label='Dosage Form',
        empty_label="Select Dosage Type"
    )
    dosage_search = django_filters.CharFilter(
        field_name='dosage_form',
        label='Search Dosage',
        method='filter_combined_search',
        widget=forms.HiddenInput()
    )
    cmc_section = django_filters.ChoiceFilter(
        field_name='cmc_section',
        label='CMC Section',
        empty_label="Select CMC Section"
    )
    cmc_section_search = django_filters.CharFilter(
        field_name='cmc_section',
        label='Search CMC Section',
        method = 'filter_combined_search',
        widget=forms.HiddenInput()
    )
    deficiency_type = django_filters.ChoiceFilter(
        field_name='deficiency_type',
        label='Deficiency Type',
        empty_label="Select Deficiency Type"
    )
    deficiency_type_search = django_filters.CharFilter(
        field_name='deficiency_type',
        label='Search Deficiency Type',
        method='filter_combined_search',
        widget=forms.HiddenInput()  # Hide this field in the form
    )
    category_of_deficiency = django_filters.ChoiceFilter(
        field_name='category_of_deficiency',
        label='Category of Deficiency',
        empty_label="Select Category of Deficiency"
    )
    category_of_deficiency_search = django_filters.CharFilter(
        field_name='category_of_deficiency',
        label='Search Category of Deficiency Type',
        method='filter_combined_search',
        widget=forms.HiddenInput()  # Hide this field in the form
    )
    search_deficiency = django_filters.CharFilter(
        field_name='deficiency',
        label='Search Deficiency',
        method='filter_combined_search'
    )

    class Meta:
        model = MajorCR
        fields = ['dosage_form', 'cmc_section', 'deficiency_type', 'category_of_deficiency','search_deficiency']

    def __init__(self, *args, **kwargs):
        main_category = kwargs.pop('main_category', None)
        super().__init__(*args, **kwargs)

        queryset = MajorCR.objects.filter(main_cateogry=main_category) if main_category else MajorCR.objects.all()

        self.filters['dosage_form'].extra['choices'] = [(df, df) for df in queryset.values_list('dosage_form', flat=True).distinct()]
        self.filters['cmc_section'].extra['choices'] = [(cmc, cmc) for cmc in queryset.values_list('cmc_section', flat=True).distinct()]
        self.filters['deficiency_type'].extra['choices'] = [(dt, dt) for dt in queryset.values_list('deficiency_type', flat=True).distinct()]
        self.filters['category_of_deficiency'].extra['choices'] = [(cod, cod) for cod in queryset.values_list('category_of_deficiency', flat=True).distinct()]

        self.filters['dosage_form'].field.widget.attrs.update({'class': 'form-select'}),
        self.filters['cmc_section'].field.widget.attrs.update({'class': 'form-select'}),
        self.filters['deficiency_type'].field.widget.attrs.update({'class': 'form-select'}),
        self.filters['category_of_deficiency'].field.widget.attrs.update({'class': 'form-select'}),

    def filter_combined_search(self, queryset, name, value):
        if not value:
            return queryset

        # Get synonyms from ChatGPT for all fields
        # search_terms, dosage_terms, cmc_terms, deficiency_terms, category_terms, type_of_dosage_terms = get_synonyms_from_chatgpt(value)

        # Create Q objects for each field
        # dosage_q = Q()
        # cmc_section_q = Q()
        # category_of_deficiency_q = Q()
        # deficiency_type_q = Q()
        # deficiency_q = Q()

        # Populate Q objects with AND conditions
        # for term in dosage_terms:
        #     dosage_q &= Q(dosage__icontains=term)

        # for term in cmc_terms:
        #     cmc_section_q &= Q(cmc_section__icontains=term)

        # for term in deficiency_terms:
        #     deficiency_type_q &= Q(deficiency_type__icontains=term)

        # for term in category_terms:
        #     category_of_deficiency_q &= Q(category_of_deficiency__icontains=term)

        # for term in search_terms:
        #     deficiency_q |= Q(deficiency__icontains=term)

        # Combine all Q objects with AND operation
        # combined_q = dosage_q | cmc_section_q | category_of_deficiency_q | deficiency_type_q | deficiency_q

        # Apply the combined filter
        return queryset.filter(Q(deficiency__icontains=value))

    # def filter_search_deficiency(self, queryset, name, value):
    #     if not value:
    #         return queryset

    #     search_terms = get_synonyms_from_chatgpt(value)
    #     print("search terms",search_terms)
    #     q_objects = Q()
    #     for term in search_terms:
    #         q_objects |= (Q(deficiency__icontains=term) |
    #             Q(dosage_form__icontains=term) |
    #             Q(cmc_section__icontains=term) |
    #             Q(deficiency_type__icontains=term) |
    #             Q(category_of_deficiency__icontains=term)
    #         )

    #     return queryset.filter(q_objects)


#filter for 483
class Form483Filter(django_filters.FilterSet):

    company_name = django_filters.ChoiceFilter(
        field_name='company_name',
        label='Company Name',
        choices=lambda: [(name, name) for name in Form483Master.objects.values_list('company_name', flat=True).distinct() if name],
        empty_label="Select Company Name",

    )

    city = django_filters.ChoiceFilter(
        field_name='city',
        label='City',
        choices=lambda: [(city, city) for city in Form483Master.objects.values_list('city', flat=True).distinct() if city],
        empty_label="Select City"
    )

    state = django_filters.ChoiceFilter(
        field_name='state',
        label='State',
        choices=lambda: [(state, state) for state in Form483Master.objects.values_list('state', flat=True).distinct() if state],
        empty_label="Select State"
    )

    type_of_establishment = django_filters.ChoiceFilter(
        field_name='type_of_establishment',
        label='Type of Establishment',
        choices=lambda: [(type_, type_) for type_ in Form483Master.objects.values_list('type_of_establishment', flat=True).distinct() if type_],
        empty_label="Select Type of Establishment"
    )

    # Date range filters
    start_date = DateFilter(
        field_name='date_of_inspection',
        lookup_expr='gte',
        label='Start Date',
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=False
    )

    end_date = DateFilter(
        field_name='date_of_inspection',
        lookup_expr='lte',
        label='End Date',
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=False
    )

    investigator_name = django_filters.ChoiceFilter(
        field_name='investigator_name',
        label='Investigator Name',
        choices=lambda: [(inv, inv) for inv in Form483Master.objects.values_list('investigator_name', flat=True).distinct() if inv],
        empty_label="Select Investigator"
    )

    year_of_inspection = django_filters.ChoiceFilter(
        field_name='year_of_inspection',
        label='Year of Inspection',
        choices=lambda: [(year, year) for year in Form483Master.objects.values_list('year_of_inspection', flat=True).distinct() if year],
        empty_label="Select Year"
    )

    system = django_filters.ChoiceFilter(
        field_name='form483system__system',
        label='System',
        choices=lambda: [(sys, sys) for sys in Form483System.objects.values_list('system', flat=True).distinct() if sys],
        empty_label="Select System",
    )

    search = django_filters.CharFilter(
        label='Search Observations',
        method='filter_observation_content',

    )

    def filter_observation_content(self, queryset, name, value):
        if not value:
            return queryset

        # get_synonyms_from_chatgpt returns six lists; only the first (keywords
        # + synonyms + related terms) applies to observation content.
        search_terms, *_ = get_synonyms_from_chatgpt(value)

        # Always include the literal query, and fall back to it alone when the
        # expansion is unavailable -- an empty Q() would match every row.
        terms = [value] + [t for t in search_terms if t]

        q_objects = Q()
        for term in terms:
            q_objects |= Q(form483system__form483observation__form483obeservationcontent__content__icontains=term)

        # Return filtered queryset with distinct results
        return queryset.filter(q_objects).distinct()

    # def filter_observation_content(self, queryset, name, value):
    #     value_new = Q(form483system__form483observation__form483obeservationcontent__content__icontains=value)
    #     print("***",value_new)
    #     if value:
    #         return queryset.filter(
    #             value_new
    #         ).distinct()
    #     else:
    #         print(">>>>>>>>>")
    #     return queryset

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if start_date and end_date and start_date > end_date:
            raise forms.ValidationError("End date must be after start date")

        return cleaned_data

    def __init__(self, data=None, queryset=None, *, request=None, prefix=None):
            super(Form483Filter, self).__init__(data=data, queryset=queryset, request=request, prefix=prefix)
            self.filters['company_name'].field.widget.attrs.update({'class': 'form-select'})
            self.filters['city'].field.widget.attrs.update({'class': 'form-select'})
            self.filters['state'].field.widget.attrs.update({'class': 'form-select'})
            self.filters['type_of_establishment'].field.widget.attrs.update({'class': 'form-select'})
            self.filters['investigator_name'].field.widget.attrs.update({'class': 'form-select'})
            self.filters['year_of_inspection'].field.widget.attrs.update({'class': 'form-select'})
            self.filters['system'].field.widget.attrs.update({'class': 'form-select'})
            self.filters['start_date'].field.widget.attrs.update({'class': 'form-control'})
            self.filters['end_date'].field.widget.attrs.update({'class': 'form-control'})
            self.filters['search'].field.widget.attrs.update({'class': 'form-control'})



    class Meta:
        model = Form483Master
        fields = [
            'company_name', 'city', 'state', 'type_of_establishment',
            'start_date', 'end_date', 'investigator_name', 'year_of_inspection',
            'system','search'
        ]
