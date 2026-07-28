import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.conf import settings
from django.utils.html import escape, strip_tags

from .models import ContactMessage, Promotion, AdminNote

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ContactMessage)
def contact_message_notification(sender, instance, created, **kwargs):
    """
    Send notification email when a new contact message is received.
    """
    if kwargs.get("raw"):
        return
    if created and settings.SEND_CONTACT_EMAILS:
        try:
            subject = f"New Contact Message: {instance.subject}"

            html_message = f"""
            <h3>New Contact Message Received</h3>
            <p><strong>Name:</strong> {escape(instance.name)}</p>
            <p><strong>Email:</strong> {escape(instance.email)}</p>
            <p><strong>Phone:</strong> {escape(instance.phone or 'Not provided')}</p>
            <p><strong>Subject:</strong> {escape(instance.subject)}</p>
            <p><strong>Message:</strong></p>
            <p>{escape(instance.message)}</p>
            <p><strong>Received:</strong> {instance.created_at.strftime('%Y-%m-%d %H:%M:%S')}</p>
            """

            plain_message = strip_tags(html_message)

            send_mail(
                subject,
                plain_message,
                settings.DEFAULT_FROM_EMAIL,
                [settings.ADMIN_EMAIL],
                html_message=html_message,
                fail_silently=False,
            )

        except Exception:
            # The message remains safely stored for the dashboard. Production
            # logging/alerting must surface this delivery failure.
            logger.exception("Failed to send contact message notification.")


@receiver(post_save, sender=ContactMessage)
def send_auto_reply(sender, instance, created, **kwargs):
    """
    Send automatic reply to user when contact message is received.
    """
    if kwargs.get("raw"):
        return
    if created and settings.SEND_CONTACT_EMAILS:
        try:
            subject = f"Thank you for contacting us - {instance.subject}"

            message = f"""
            Dear {instance.name},
            
            Thank you for contacting us. We have received your message and will get back to you as soon as possible.
            
            Your message details:
            Subject: {instance.subject}
            Message: {instance.message}
            
            We typically respond within 24-48 hours.
            
            Best regards,
            The Team
            """

            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [instance.email],
                fail_silently=False,
            )

        except Exception:
            logger.exception("Failed to send contact auto-reply.")


@receiver(pre_save, sender=Promotion)
def promotion_validation(sender, instance, **kwargs):
    """
    Additional validation before saving promotion.
    """
    if kwargs.get("raw"):
        return

    # Ensure at least one discount type is provided
    if not instance.discount_percentage and not instance.discount_amount:
        from django.core.exceptions import ValidationError

        raise ValidationError(
            "Either discount percentage or discount amount must be provided."
        )

    # Ensure dates are valid
    if instance.start_date and instance.end_date:
        if instance.start_date > instance.end_date:
            from django.core.exceptions import ValidationError

            raise ValidationError("Start date cannot be later than end date.")


@receiver(post_save, sender=Promotion)
def promotion_status_change(sender, instance, created, **kwargs):
    """
    Log promotion status changes or send notifications.
    """
    if kwargs.get("raw"):
        return
    if not created:  # Only for updates
        try:
            # You can add logic here to track promotion changes
            # For example, log when a promotion becomes active/inactive
            import logging

            logger = logging.getLogger(__name__)

            if instance.is_active:
                logger.info(f"Promotion '{instance.title}' is now active.")
            else:
                logger.info(f"Promotion '{instance.title}' has been deactivated.")

        except Exception:
            logger.exception("Error in promotion status change signal.")


@receiver(post_save, sender=AdminNote)
def important_note_notification(sender, instance, created, **kwargs):
    """
    Send notification when an important admin note is created.
    """
    if kwargs.get("raw"):
        return
    if created and instance.is_important:
        try:
            # Notify other admin users about important notes
            from django.contrib.auth import get_user_model

            User = get_user_model()

            admin_users = User.objects.filter(is_staff=True).exclude(
                id=instance.created_by.id
            )
            admin_emails = [user.email for user in admin_users if user.email]

            if admin_emails:
                subject = f"Important Admin Note: {instance.title}"
                message = f"""
                An important admin note has been created by {instance.created_by.get_full_name() or instance.created_by.email}.
                
                Title: {instance.title}
                Content: {instance.content}
                Created: {instance.created_at.strftime('%Y-%m-%d %H:%M:%S')}
                
                Please log in to the admin panel to view more details.
                """

                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    admin_emails,
                    fail_silently=False,
                )

        except Exception:
            logger.exception("Failed to send important note notification.")
