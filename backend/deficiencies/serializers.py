from rest_framework import serializers

from .models import DeficiencyRecord


class DeficiencyRecordSerializer(serializers.ModelSerializer):
    """Read-only projection. `id` is the public UUID; the integer PK never leaves."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    corpus_display = serializers.CharField(source="get_corpus_display", read_only=True)

    class Meta:
        model = DeficiencyRecord
        fields = [
            "id",
            "corpus",
            "corpus_display",
            "main_category",
            "dosage_form",
            "cmc_section",
            "deficiency_type",
            "category_of_deficiency",
            "deficiency",
            "source_row_number",
            "created_at",
        ]
        read_only_fields = fields


class DeficiencyFacetsSerializer(serializers.Serializer):
    """The distinct values behind each filter, so the UI can build its dropdowns
    from the corpus actually loaded rather than a hardcoded list that drifts."""

    corpora = serializers.ListField(child=serializers.CharField())
    main_categories = serializers.ListField(child=serializers.CharField())
    dosage_forms = serializers.ListField(child=serializers.CharField())
    cmc_sections = serializers.ListField(child=serializers.CharField())
    deficiency_types = serializers.ListField(child=serializers.CharField())
