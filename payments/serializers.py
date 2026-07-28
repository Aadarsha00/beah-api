# payments/serializers.py
from rest_framework import serializers
from decimal import Decimal
from .models import Payment, PaymentRefund


class PaymentSerializer(serializers.ModelSerializer):
    appointment_details = serializers.SerializerMethodField()
    client_name = serializers.CharField(source="client.get_full_name", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "stripe_payment_intent_id",
            "appointment",
            "appointment_details",
            "client",
            "client_name",
            "payment_type",
            "payment_method",
            "amount",
            "currency",
            "status",
            "description",
            "failure_reason",
            "created_at",
            "updated_at",
            "processed_at",
        ]
        read_only_fields = [
            "id",
            "stripe_payment_intent_id",
            "client",
            "status",
            "failure_reason",
            "created_at",
            "updated_at",
            "processed_at",
        ]

    def get_appointment_details(self, obj):
        if obj.appointment:
            return {
                "id": obj.appointment.id,
                "service_name": obj.appointment.service.name,
                "appointment_date": obj.appointment.appointment_date,
                "appointment_time": obj.appointment.appointment_time,
                "client_name": obj.appointment.client_name,
            }
        return None


class PaymentIntentCreateSerializer(serializers.Serializer):
    appointment_id = serializers.IntegerField()
    payment_type = serializers.ChoiceField(choices=Payment.PAYMENT_TYPE_CHOICES)
    amount = serializers.DecimalField(max_digits=8, decimal_places=2, required=False)

    def validate_appointment_id(self, value):
        from appointments.models import Appointment

        try:
            appointment = Appointment.objects.get(id=value)
        except Appointment.DoesNotExist:
            raise serializers.ValidationError("Appointment not found.")

        # Check if appointment can accept payments
        if appointment.status in ["cancelled", "no_show"]:
            raise serializers.ValidationError(
                "Cannot process payment for cancelled or no-show appointments."
            )

        return value

    def validate(self, data):
        from appointments.models import Appointment

        appointment_id = data.get("appointment_id")
        payment_type = data.get("payment_type")
        amount = data.get("amount")

        appointment = Appointment.objects.get(id=appointment_id)

        if payment_type == "deposit":
            if appointment.deposit_amount <= 0:
                raise serializers.ValidationError(
                    "This service does not require a deposit."
                )

            # Check if deposit already paid
            existing_deposit = Payment.objects.filter(
                appointment=appointment, payment_type="deposit", status="succeeded"
            ).first()

            if existing_deposit:
                raise serializers.ValidationError(
                    "Deposit has already been paid for this appointment."
                )

            # Set amount to deposit amount if not provided
            if not amount:
                data["amount"] = appointment.deposit_amount
            elif amount != appointment.deposit_amount:
                raise serializers.ValidationError(
                    f"Deposit amount must be ${appointment.deposit_amount}"
                )

        elif payment_type == "full_payment":
            # Calculate remaining amount after deposit
            paid_amount = Payment.objects.filter(
                appointment=appointment, status="succeeded"
            ).aggregate(total=serializers.models.Sum("amount"))["total"] or Decimal(
                "0.00"
            )

            remaining_amount = appointment.total_amount - paid_amount

            if remaining_amount <= 0:
                raise serializers.ValidationError(
                    "This appointment has already been paid in full."
                )

            # Set amount to remaining amount if not provided
            if not amount:
                data["amount"] = remaining_amount
            elif amount > remaining_amount:
                raise serializers.ValidationError(
                    f"Payment amount cannot exceed remaining balance of ${remaining_amount}"
                )

        return data


class PaymentConfirmSerializer(serializers.Serializer):
    stripe_payment_intent_id = serializers.CharField()


class PaymentRefundSerializer(serializers.ModelSerializer):
    original_payment_details = serializers.SerializerMethodField()

    class Meta:
        model = PaymentRefund
        fields = [
            "id",
            "stripe_refund_id",
            "original_payment",
            "original_payment_details",
            "amount",
            "reason",
            "status",
            "notes",
            "created_at",
            "updated_at",
            "processed_at",
        ]
        read_only_fields = [
            "id",
            "stripe_refund_id",
            "status",
            "created_at",
            "updated_at",
            "processed_at",
        ]

    def get_original_payment_details(self, obj):
        return {
            "id": obj.original_payment.id,
            "amount": obj.original_payment.amount,
            "payment_type": obj.original_payment.payment_type,
            "appointment_id": obj.original_payment.appointment.id,
        }

    def validate_original_payment(self, value):
        if not value.can_be_refunded:
            raise serializers.ValidationError("This payment cannot be refunded.")
        return value

    def validate_amount(self, value):
        if hasattr(self, "initial_data") and "original_payment" in self.initial_data:
            original_payment_id = self.initial_data["original_payment"]
            try:
                original_payment = Payment.objects.get(id=original_payment_id)

                # Calculate total already refunded
                total_refunded = PaymentRefund.objects.filter(
                    original_payment=original_payment, status="succeeded"
                ).aggregate(total=serializers.models.Sum("amount"))["total"] or Decimal(
                    "0.00"
                )

                available_for_refund = original_payment.amount - total_refunded

                if value > available_for_refund:
                    raise serializers.ValidationError(
                        f"Refund amount cannot exceed available amount of ${available_for_refund}"
                    )

            except Payment.DoesNotExist:
                pass

        return value
