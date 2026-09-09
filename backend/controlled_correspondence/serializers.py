from rest_framework import serializers

from .models import BestPractice, CorrespondenceDraft


class BestPracticeSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = BestPractice
        fields = ["id", "category", "sub_category", "guidance"]
        read_only_fields = fields


class CorrespondenceDraftSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = CorrespondenceDraft
        fields = [
            "id",
            "status",
            "proposed_drug_product_name",
            "brand_or_generic_name",
            "strength",
            "anda_applicant_name",
            "nda_applicant_name",
            "nda_number",
            "company_name",
            "responsible_person_name",
            "designation",
            "email_address",
            "telephone",
            "mobile",
            "fax",
            "us_agent_company_name",
            "us_regulatory_agent_company_name",
            "correspondence_date",
            "notes",
            "company_logo_document",
            "signature_document",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class CorrespondenceDraftWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = CorrespondenceDraft
        fields = [
            "status",
            "proposed_drug_product_name",
            "brand_or_generic_name",
            "strength",
            "anda_applicant_name",
            "nda_applicant_name",
            "nda_number",
            "company_name",
            "responsible_person_name",
            "designation",
            "email_address",
            "telephone",
            "mobile",
            "fax",
            "us_agent_company_name",
            "us_regulatory_agent_company_name",
            "correspondence_date",
            "notes",
            "company_logo_document",
            "signature_document",
        ]
