from django.db.models import Q

from .models import ChatMessage, UserProfile
from .navbar_notifications import get_navbar_notifications


def crm_access(request):
    access = {
        "role": "",
        "role_label": "",
        "can_access_finance": False,
        "can_close_documents": False,
        "can_delete_records": False,
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
