from django.db.models import Q

from django.contrib.auth import get_user_model

from .models import ChatMessage, Organization, OrganizationContact, UserProfile
from .navbar_notifications import get_navbar_notifications


def crm_access(request):
    access = {
        "role": "",
        "role_label": "",
        "can_access_finance": False,
        "can_close_documents": False,
        "can_delete_records": False,
        "can_view_personal_data": False,
        "can_manage_personal_data": False,
        "can_export_personal_data": False,
    }
    if not request.user.is_authenticated:
        return {"crm_access": access}
    if request.user.is_staff or request.user.is_superuser:
        access.update(
            {
                "role": UserProfile.Role.ADMIN,
                "role_label": UserProfile.Role.ADMIN.label,
                "can_access_finance": True,
                "can_close_documents": True,
                "can_delete_records": True,
                "can_view_personal_data": True,
                "can_manage_personal_data": True,
                "can_export_personal_data": True,
            }
        )
        return {"crm_access": access}
    profile, _created = UserProfile.objects.get_or_create(user=request.user)
    access.update(
        {
            "role": profile.role,
            "role_label": profile.get_role_display(),
            "can_access_finance": profile.can_access_finance,
            "can_close_documents": profile.can_close_documents,
            "can_delete_records": profile.can_delete_records,
            "can_view_personal_data": profile.can_view_personal_data,
            "can_manage_personal_data": profile.can_manage_personal_data,
            "can_export_personal_data": profile.can_export_personal_data,
        }
    )
    return {"crm_access": access}


def chat_unread(request):
    if not request.user.is_authenticated:
        return {"chat_unread_count": 0}
    unread_count = ChatMessage.objects.filter(
        Q(conversation__user_low=request.user)
        | Q(conversation__user_high=request.user),
        read_at__isnull=True,
    ).exclude(sender=request.user).count()
    return {"chat_unread_count": unread_count}


def navbar_notifications(request):
    items = get_navbar_notifications(request.user)
    return {
        "navbar_notifications": items[:8],
        "navbar_notification_count": sum(not item["is_read"] for item in items),
    }


def mail_recipient_suggestions(request):
    """Addresses offered by the compose field, without exposing mailbox contents."""
    if not request.user.is_authenticated:
        return {"mail_recipient_suggestions": []}

    current_email = (request.user.email or "").strip().casefold()
    entries = []

    for contact in OrganizationContact.objects.exclude(email="").filter(is_active=True).select_related("organization"):
        entries.append((contact.email, f"{contact.full_name} · {contact.organization.name}"))
    for organization in Organization.objects.exclude(email=""):
        entries.append((organization.email, organization.name))
    for user in get_user_model().objects.exclude(email=""):
        entries.append((user.email, user.get_full_name() or user.username))

    seen = set()
    suggestions = []
    for email, label in entries:
        normalized = email.strip().casefold()
        if not normalized or normalized == current_email or normalized in seen:
            continue
        seen.add(normalized)
        suggestions.append({"email": email.strip(), "label": label})
    return {"mail_recipient_suggestions": sorted(suggestions, key=lambda item: item["email"].casefold())}
