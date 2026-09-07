from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .accounting import sync_payment_movement
from .models import Carrier, CompanyProfile, Customer, Payment, Shipment, UserProfile
from .sync import sync_legacy_organization, sync_shipment_to_transportation


@receiver(post_save, sender=CompanyProfile)
@receiver(post_save, sender=Customer)
@receiver(post_save, sender=Carrier)
def keep_unified_organization_current(sender, instance, raw=False, **kwargs):
    if not raw:
        sync_legacy_organization(instance)


@receiver(post_save, sender=Shipment)
def keep_transportation_current(sender, instance, raw=False, **kwargs):
    if not raw:
        sync_shipment_to_transportation(instance)


@receiver(post_save, sender=Payment)
def keep_payment_register_current(sender, instance, raw=False, **kwargs):
    if not raw:
        sync_payment_movement(instance)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_user_profile(sender, instance, raw=False, **kwargs):
    if raw:
        return
    profile, _created = UserProfile.objects.get_or_create(user=instance)
    if (instance.is_staff or instance.is_superuser) and profile.role != UserProfile.Role.ADMIN:
        profile.role = UserProfile.Role.ADMIN
        profile.save(update_fields=["role", "updated_at"])
