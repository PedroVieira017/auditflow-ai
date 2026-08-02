from django.db.models import Count, Q

from apps.alerts.models import Alert
from apps.core.choices import Severity
from apps.imports.models import ImportBatch


def build_dashboard(*, organization):
    imports = ImportBatch.objects.for_organization(organization)
    alerts = Alert.objects.for_organization(organization)

    import_counts = imports.aggregate(
        total=Count("id"),
        completed=Count(
            "id",
            filter=Q(status=ImportBatch.Status.COMPLETED),
        ),
        failed=Count(
            "id",
            filter=Q(status=ImportBatch.Status.FAILED),
        ),
        in_progress=Count(
            "id",
            filter=Q(
                status__in=(
                    ImportBatch.Status.PENDING,
                    ImportBatch.Status.PROCESSING,
                )
            ),
        ),
    )
    alert_counts = alerts.aggregate(
        total=Count("id"),
        new=Count("id", filter=Q(status=Alert.Status.NEW)),
        valid=Count("id", filter=Q(status=Alert.Status.VALID)),
        false_positive=Count(
            "id",
            filter=Q(status=Alert.Status.FALSE_POSITIVE),
        ),
        resolved=Count("id", filter=Q(status=Alert.Status.RESOLVED)),
        low=Count("id", filter=Q(severity=Severity.LOW)),
        medium=Count("id", filter=Q(severity=Severity.MEDIUM)),
        high=Count("id", filter=Q(severity=Severity.HIGH)),
        critical=Count("id", filter=Q(severity=Severity.CRITICAL)),
    )

    recent_imports = list(imports[:5])
    recent_alerts = list(
        alerts.select_related(
            "rule_run__import_batch",
        )[:5]
    )
    return {
        "import_counts": import_counts,
        "alert_counts": alert_counts,
        "recent_imports": recent_imports,
        "recent_alerts": recent_alerts,
    }
