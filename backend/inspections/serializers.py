from rest_framework import serializers

from .models import Form483Inspection, Form483Observation, Form483System, WarningLetter


class Form483ObservationSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    system = serializers.CharField(source="system.system", read_only=True)
    company_name = serializers.CharField(source="system.inspection.company_name", read_only=True)

    class Meta:
        model = Form483Observation
        fields = ["id", "observation_number", "system", "company_name", "content", "summary"]
        read_only_fields = fields


class Form483SystemSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    observations = Form483ObservationSerializer(many=True, read_only=True)

    class Meta:
        model = Form483System
        fields = ["id", "system", "observations"]
        read_only_fields = fields


class Form483InspectionSerializer(serializers.ModelSerializer):
    """List projection. Systems and observations are nested on detail only --
    an inspection can carry dozens, and a list view does not need them."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    year_of_inspection = serializers.IntegerField(read_only=True)
    observation_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Form483Inspection
        fields = [
            "id", "company_name", "city", "state", "country",
            "type_of_establishment", "date_of_inspection", "year_of_inspection",
            "investigator_name", "observation_count",
        ]
        read_only_fields = fields


class Form483InspectionDetailSerializer(Form483InspectionSerializer):
    systems = Form483SystemSerializer(many=True, read_only=True)

    class Meta(Form483InspectionSerializer.Meta):
        fields = Form483InspectionSerializer.Meta.fields + ["systems"]
        read_only_fields = fields


class WarningLetterSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = WarningLetter
        fields = [
            "id", "company_name", "recipient_name", "date_of_issue", "location",
            "city_state", "country", "date_of_inspection", "investigator_names",
            "body", "summary",
        ]
        read_only_fields = fields


class InspectionFacetsSerializer(serializers.Serializer):
    """Filter values derived from the loaded corpus, not a hardcoded list."""

    companies = serializers.ListField(child=serializers.CharField())
    systems = serializers.ListField(child=serializers.CharField())
    investigators = serializers.ListField(child=serializers.CharField())
    establishment_types = serializers.ListField(child=serializers.CharField())
    years = serializers.ListField(child=serializers.IntegerField())
