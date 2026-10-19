
from django.conf import settings
from django.utils import timezone
from django.utils.http import urlencode
from rest_framework import status
from rest_framework import generics
from rest_framework.response import Response
from paynet import exceptions
from paynet.models import PaynetTransaction as Transaction
from paynet.views import PaynetCallbackAPIView
from orders.models import Order
from .serializers import OrderCreateSerializer
from paynet.serializers import PerformTransactionSerializer
from .kafka_sender import send_payment_event
from django.utils import timezone
from django.db import transaction
import os
from dotenv import load_dotenv

load_dotenv()

class PaynetWebhookAPIView(PaynetCallbackAPIView):
    allowed_services = [188]
    def post(self, request):
        data = request.data

        rpc_id = data.get("id")

        credentials = request.headers.get("Authorization")

        if not self.authenticate_request(credentials):
            return Response(
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {
                        "code": 401,
                        "message": "Unauthorized",
                    },
                },
                status=401,
            )

        if not self.validate_request_format(data):
            raise exceptions.InvalidRPCRequest(
                rpc_id=rpc_id
            )

        service_id = data.get("params", {}).get("serviceId")

        if not self.is_service_enabled(service_id):
            return Response({
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {
                    "code": 305,
                    "message": "Xizmat topilmadi",
                },
            })


        return super().post(request)

    def get_information(self, params, rpc_id):
        client_id = params["fields"]["client_id"]

        order = (
            Order.objects
            .filter(
                client_id=client_id,
                is_paid=False,
            )
            .order_by("-created_at")
            .first()
        )

        if not order:
            raise exceptions.ClientNotFound(
                rpc_id=rpc_id
            )

        return Response({
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "status": str(Transaction.CREATED),
                "timestamp": timezone.localtime().strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "fields": {
                    "amount": order.amount,
                    "name": order.customer_name,
                },
            },
        })

    def perform_transaction(self, params, rpc_id):
        client_id = params["fields"]["client_id"]

        order = (
            Order.objects
            .filter(client_id=client_id)
            .order_by("-created_at")
            .first()
        )

        if not order:
            raise exceptions.ClientNotFound(
                rpc_id=rpc_id
            )

        amount_tiyin = int(params["amount"])

        max_amount_tiyin = settings.PAYNET_MAX_AMOUNT * 100

        if amount_tiyin > max_amount_tiyin:
            return Response({
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {
                    "code": 415,
                    "message": "Сумма превышает максимальный лимит",
                },
            })


        expected_amount_tiyin = order.amount * 100

        if amount_tiyin != expected_amount_tiyin:
            return Response({
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {
                    "code": 415,
                    "message": (
                        "Сумма платежа не соответствует "
                        "сумме заказа"
                    ),
                },
            })

        serializer = PerformTransactionSerializer(
            data=params
        )
        serializer.is_valid(
            raise_exception=True
        )

        transaction, created = Transaction.objects.get_or_create(
            transaction_id=serializer.validated_data[
                "transactionId"
            ],
            defaults={
                "service_id": serializer.validated_data[
                    "serviceId"
                ],
                "account_id": serializer.validated_data[
                    "fields"
                ][settings.PAYNET_ACCOUNT_FIELD],
                "amount": serializer.validated_data[
                    "amount"
                ],
                "status": Transaction.SUCCESSFUL,
            },
        )

        if not created:
            raise exceptions.TransactionAlreadyExists(
                rpc_id=rpc_id
            )

        self.successfully_payment(params)

        timestamp = timezone.localtime(
            transaction.created_at
        ).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        return Response({
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "providerTrnId": transaction.id,
                "timestamp": timestamp,
                "fields": {
                    settings.PAYNET_ACCOUNT_FIELD:
                        transaction.account_id,
                },
            },
        })

    def successfully_payment(self, params):
        client_id = params["fields"]["client_id"]

        order = (
            Order.objects
            .filter(
                client_id=client_id,
                is_paid=False,
            )
            .order_by("-created_at")
            .first()
        )

        if not order:
            return

        order.is_paid = True
        order.paid_at = timezone.now()

        order.save(
            update_fields=[
                "is_paid",
                "paid_at",
            ]
        )

    def get_statement(self, params, rpc_id):
        from paynet.serializers import GetStatementSerializer

        serializer = GetStatementSerializer(
            data=params
        )
        serializer.is_valid(
            raise_exception=True
        )

        transactions = (
            Transaction.objects
            .filter(
                service_id=serializer.validated_data[
                    "serviceId"
                ],
                created_at__range=[
                    serializer.validated_data["dateFrom"],
                    serializer.validated_data["dateTo"],
                ],
            )
            .exclude(
                status=Transaction.CANCELLED
            )
        )

        statements = [
            {
                "amount": int(tx.amount),

                "providerTrnId": int(tx.id),

                "transactionId": int(
                    tx.transaction_id
                ),

                "timestamp": timezone.localtime(
                    tx.created_at
                ).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            }
            for tx in transactions
        ]

        return Response({
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "statements": statements
            },
        })

    def cancelled_payment(self, params):
        transaction_id = params["transactionId"]
        service_id = params["serviceId"]

        transaction = (
            Transaction.objects
            .filter(
                transaction_id=transaction_id,
                service_id=service_id,
            )
            .first()
        )

        if not transaction:
            return

        client_id = transaction.account_id

        order = (
            Order.objects
            .filter(
                client_id=str(client_id),
                is_paid=True,
            )
            .order_by("-created_at")
            .first()
        )

        if not order:
            return

        order.is_paid = False
        order.paid_at = None

        order.save(
            update_fields=[
                "is_paid",
                "paid_at",
            ]
        )

class OrderCreateAPIView(generics.CreateAPIView):
    queryset = Order.objects.all()
    serializer_class = OrderCreateSerializer

    PAYNET_MERCHANT_ID = os.getenv('PAYNET_MERCHANT_ID')
    PAYNET_BASE_URL = "https://app.paynet.uz"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = serializer.save()

        params = {
            "m": self.PAYNET_MERCHANT_ID,
            "c": order.client_id,
            "a": int(order.amount),
        }

        payment_url = f"{self.PAYNET_BASE_URL}/?{urlencode(params)}"

        response_data = {
            **serializer.data,
            "payment_url": payment_url,
        }

        headers = self.get_success_headers(serializer.data)

        return Response(
            response_data,
            status=status.HTTP_201_CREATED,
            headers=headers,
        )