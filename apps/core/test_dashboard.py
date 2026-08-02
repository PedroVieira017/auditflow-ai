from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.alerts.models import Alert
from apps.core.choices import Severity
from apps.imports.models import ImportBatch
from apps.organizations.models import Membership, Organization
from apps.rules.models import RuleDefinition, RuleRun


class OrganizationDashboardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="leitor-dashboard@example.com",
            password="password",
        )
        self.organization = Organization.objects.create(
            name="Empresa Dashboard",
            slug="empresa-dashboard",
        )
        self.membership = Membership.objects.create(
            organization=self.organization,
            user=self.user,
            role=Membership.Role.VIEWER,
        )
        self.rule_definition = RuleDefinition.objects.create(
            key="DASHBOARD_RULE",
            version=1,
            name="Regra do dashboard",
            description="Regra usada para testar o resumo operacional.",
            default_severity=Severity.MEDIUM,
        )

        self.completed_import = self.create_import(
            organization=self.organization,
            uploaded_by=self.user,
            filename="concluida.csv",
            file_hash="a" * 64,
            status=ImportBatch.Status.COMPLETED,
        )
        self.create_import(
            organization=self.organization,
            uploaded_by=self.user,
            filename="com-erros.csv",
            file_hash="b" * 64,
            status=ImportBatch.Status.FAILED,
        )
        self.create_import(
            organization=self.organization,
            uploaded_by=self.user,
            filename="pendente.csv",
            file_hash="c" * 64,
            status=ImportBatch.Status.PENDING,
        )
        self.create_import(
            organization=self.organization,
            uploaded_by=self.user,
            filename="processamento.csv",
            file_hash="d" * 64,
            status=ImportBatch.Status.PROCESSING,
        )
        self.rule_run = RuleRun.objects.create(
            organization=self.organization,
            import_batch=self.completed_import,
            rule_definition=self.rule_definition,
            status=RuleRun.Status.COMPLETED,
            alert_count=5,
        )
        alert_definitions = (
            ("Novo de prioridade alta", Alert.Status.NEW, Severity.HIGH),
            ("Novo de prioridade crítica", Alert.Status.NEW, Severity.CRITICAL),
            ("Exceção válida", Alert.Status.VALID, Severity.MEDIUM),
            (
                "Exceção classificada como falso positivo",
                Alert.Status.FALSE_POSITIVE,
                Severity.LOW,
            ),
            ("Ocorrência resolvida", Alert.Status.RESOLVED, Severity.HIGH),
        )
        self.alerts = []
        for index, (title, status, severity) in enumerate(alert_definitions, start=1):
            self.alerts.append(
                Alert.objects.create(
                    organization=self.organization,
                    rule_run=self.rule_run,
                    fingerprint=f"{index:064x}",
                    title=title,
                    explanation="Resultado usado no dashboard.",
                    status=status,
                    severity=severity,
                )
            )

        self.other_organization = Organization.objects.create(
            name="Empresa Confidencial",
            slug="empresa-confidencial-dashboard",
        )
        other_user = get_user_model().objects.create_user(
            email="confidencial-dashboard@example.com",
            password="password",
        )
        other_import = self.create_import(
            organization=self.other_organization,
            uploaded_by=other_user,
            filename="ficheiro-secreto.csv",
            file_hash="a" * 64,
            status=ImportBatch.Status.COMPLETED,
        )
        other_run = RuleRun.objects.create(
            organization=self.other_organization,
            import_batch=other_import,
            rule_definition=self.rule_definition,
            status=RuleRun.Status.COMPLETED,
            alert_count=1,
        )
        Alert.objects.create(
            organization=self.other_organization,
            rule_run=other_run,
            fingerprint="9" * 64,
            title="Alerta confidencial",
            explanation="Este resultado pertence a outra organização.",
            status=Alert.Status.NEW,
            severity=Severity.CRITICAL,
        )

        self.dashboard_url = reverse(
            "core:dashboard",
            kwargs={"organization_id": self.organization.id},
        )

    def create_import(
        self,
        *,
        organization,
        uploaded_by,
        filename,
        file_hash,
        status,
    ):
        return ImportBatch.objects.create(
            organization=organization,
            uploaded_by=uploaded_by,
            original_filename=filename,
            file_sha256=file_hash,
            status=status,
            row_count=10,
            valid_row_count=10 if status == ImportBatch.Status.COMPLETED else 0,
        )

    def test_unauthenticated_user_is_redirected_to_login(self):
        response = self.client.get(self.dashboard_url)

        expected_url = f"{reverse('login')}?next={self.dashboard_url}"
        self.assertRedirects(response, expected_url)

    def test_viewer_sees_scoped_operational_summary(self):
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        dashboard = response.context["dashboard"]
        self.assertEqual(
            dashboard["import_counts"],
            {
                "total": 4,
                "completed": 1,
                "failed": 1,
                "in_progress": 2,
            },
        )
        self.assertEqual(
            dashboard["alert_counts"],
            {
                "total": 5,
                "new": 2,
                "valid": 1,
                "false_positive": 1,
                "resolved": 1,
                "low": 1,
                "medium": 1,
                "high": 2,
                "critical": 1,
            },
        )
        self.assertContains(response, "Não representa uma avaliação global")
        alert_list_url = reverse(
            "alerts:list",
            kwargs={"organization_id": self.organization.id},
        )
        self.assertContains(response, alert_list_url)
        self.assertNotContains(response, "Alerta confidencial")
        self.assertNotContains(response, "ficheiro-secreto.csv")

    def test_recent_activity_is_limited_to_five_items(self):
        for index in range(6, 9):
            Alert.objects.create(
                organization=self.organization,
                rule_run=self.rule_run,
                fingerprint=f"{index:064x}",
                title=f"Alerta recente {index}",
                explanation="Resultado recente.",
                status=Alert.Status.NEW,
                severity=Severity.LOW,
            )
        for character in ("e", "f"):
            self.create_import(
                organization=self.organization,
                uploaded_by=self.user,
                filename=f"recente-{character}.csv",
                file_hash=character * 64,
                status=ImportBatch.Status.COMPLETED,
            )
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)

        dashboard = response.context["dashboard"]
        self.assertEqual(len(dashboard["recent_alerts"]), 5)
        self.assertEqual(len(dashboard["recent_imports"]), 5)
        self.assertEqual(dashboard["recent_alerts"][0].title, "Alerta recente 8")
        self.assertEqual(
            dashboard["recent_imports"][0].original_filename,
            "recente-f.csv",
        )

    def test_user_without_membership_cannot_access_dashboard(self):
        outsider = get_user_model().objects.create_user(
            email="fora-dashboard@example.com",
            password="password",
        )
        self.client.force_login(outsider)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 404)

    def test_inactive_organization_cannot_be_accessed(self):
        self.organization.is_active = False
        self.organization.save()
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 404)

    def test_empty_organization_shows_zero_counts_and_next_action(self):
        empty_organization = Organization.objects.create(
            name="Empresa Vazia",
            slug="empresa-vazia-dashboard",
        )
        Membership.objects.create(
            organization=empty_organization,
            user=self.user,
            role=Membership.Role.OWNER,
        )
        empty_url = reverse(
            "core:dashboard",
            kwargs={"organization_id": empty_organization.id},
        )
        self.client.force_login(self.user)

        response = self.client.get(empty_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard"]["import_counts"]["total"], 0)
        self.assertEqual(response.context["dashboard"]["alert_counts"]["total"], 0)
        self.assertContains(response, "Carregue um ficheiro CSV")

    def test_dashboard_rejects_post_requests(self):
        self.client.force_login(self.user)

        response = self.client.post(self.dashboard_url)

        self.assertEqual(response.status_code, 405)
