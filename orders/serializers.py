from rest_framework import serializers
from .models import Order

class OrderCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = [
            "order_id",
            "client_id",
            "customer_name",
            "amount",
            "is_paid",
            "paid_at",
        ]
        read_only_fields = [
            "order_id",
            "is_paid",
            "paid_at",
        ]