from rest_framework import serializers


class TripRequestSerializer(serializers.Serializer):
    start = serializers.CharField(
        help_text="Start location in the USA (e.g. 'New York, NY' or 'Los Angeles, CA')",
        max_length=512,
    )
    end = serializers.CharField(
        help_text="End location in the USA (e.g. 'Chicago, IL')",
        max_length=512,
    )

    def validate_start(self, value: str) -> str:
        return value.strip()

    def validate_end(self, value: str) -> str:
        return value.strip()
