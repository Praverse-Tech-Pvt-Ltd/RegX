from rest_framework import serializers

from .models import AttributeSource, ComparisonAttribute, ProductComparison, ProductType


class ComparisonAttributeSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = ComparisonAttribute
        fields = ["id", "attribute", "source", "value", "document_reference"]
        read_only_fields = ["id"]


class ProductComparisonSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    attributes = ComparisonAttributeSerializer(many=True, read_only=True)
    known_attributes = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = ProductComparison
        fields = [
            "id", "product_type", "rld_product_name", "company_product_name",
            "notes", "known_attributes", "attributes", "created_at",
        ]
        read_only_fields = ["id", "known_attributes", "attributes", "created_at"]


class ProductComparisonWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductComparison
        fields = ["product_type", "rld_product_name", "company_product_name", "notes"]


class ComparisonAttributeWriteSerializer(serializers.Serializer):
    """One attribute value. Upserted on (attribute, source), which is the unique
    constraint, so re-sending a value corrects it rather than erroring."""

    attribute = serializers.CharField(max_length=100)
    source = serializers.ChoiceField(choices=AttributeSource.choices)
    value = serializers.CharField(allow_blank=True, required=False, default="")
    document_reference = serializers.UUIDField(required=False, allow_null=True)


class ComparisonMatrixSerializer(serializers.Serializer):
    """The attribute-by-source grid the UI renders.

    Built server-side because the shape depends on `product_type`, and the
    client should not have to know which attributes belong to a capsule.
    """

    product_type = serializers.ChoiceField(choices=ProductType.choices)
    sources = serializers.ListField(child=serializers.CharField())
    rows = serializers.ListField(child=serializers.DictField())
