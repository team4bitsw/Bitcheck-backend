from django.dispatch import receiver

from apps.verifications.signals import verification_completed


@receiver(verification_completed)
def on_verification_completed(sender, verification, **kwargs):
    if verification.source != 'connector':
        return
    from apps.connectors.tasks import send_connector_result

    send_connector_result.delay(str(verification.id))
