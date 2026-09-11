from django.db.models import Q

from .models import NotificationRead, PlannerTask, Transportation


def get_navbar_notifications(user):
    """Return live operational notifications with each user's read state."""
    if not user.is_authenticated:
        return []

    from .views import automatic_planner_tasks

    automatic = automatic_planner_tasks(
        list(
            Transportation.objects.exclude(status=Transportation.Status.CANCELLED)
            .select_related("manager")
            .prefetch_related("stops", "execution_links", "vehicle_assignments", "settlement_movements")
            .order_by("planned_start_date", "pk")
        )
    )
    items = [
        {
            "key": f"auto:{item['transportation'].pk}:{item['kind']}:{item['title']}",
            "title": item["title"],
            "description": item["description"],
            "url": item["url"],
            "priority": item["priority"],
            "due_date": item["due_date"],
        }
        for item in automatic
    ]
    tasks = PlannerTask.objects.filter(
        Q(assignee=user) | Q(assignee__isnull=True),
        status__in=(PlannerTask.Status.TODO, PlannerTask.Status.IN_PROGRESS),
    ).select_related("transportation")
    for task in tasks:
        items.append(
            {
                "key": f"task:{task.pk}",
                "title": task.title,
                "description": task.description or "Задача планировщика",
                "url": task.get_absolute_url(),
                "priority": task.priority,
                "due_date": task.due_date,
            }
        )
    read_keys = set(
        NotificationRead.objects.filter(user=user, notification_key__in=[item["key"] for item in items])
        .values_list("notification_key", flat=True)
    )
    for item in items:
        item["is_read"] = item["key"] in read_keys
    priority_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    items.sort(key=lambda item: (item["is_read"], priority_order.get(item["priority"], 4), item["due_date"] is None, item["due_date"] or "9999-12-31"))
    return items


def mark_all_navbar_notifications_read(user):
    items = get_navbar_notifications(user)
    NotificationRead.objects.bulk_create(
        [NotificationRead(user=user, notification_key=item["key"]) for item in items if not item["is_read"]],
        ignore_conflicts=True,
    )
