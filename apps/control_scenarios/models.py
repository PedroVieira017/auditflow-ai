from datetime import timezone as datetime_timezone

from django.conf import settings
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.core.validators import MinLengthValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import OrganizationScopedModel, OrganizationScopedQuerySet
from apps.organizations.models import Membership

from .contracts import (
    CONTROL_SCENARIO_CONTRACT,
    ControlScenarioContractError,
    calculate_payload_hash,
    validate_configuration,
)


CREATOR_ROLE_CHOICES = (
    (Membership.Role.OWNER, "Proprietário"),
    (Membership.Role.ANALYST, "Analista"),
)

APPROVED_IMMUTABLE_FIELDS = {
    "approval_note",
    "approved_at",
    "approved_by_email",
    "approved_by_role",
    "approved_by_user_id",
    "change_reason",
    "config_hash",
    "control",
    "description",
    "effective_from",
    "limitations",
    "monitoring",
    "name",
    "objective",
    "organization_name",
    "risk",
    "rules",
    "state",
}

VERSION_IDENTITY_FIELDS = {
    "created_by_email",
    "created_by_role",
    "created_by_user_id",
    "organization_id",
    "scenario_id",
    "supersedes_id",
    "version",
}

VERSION_IDENTITY_UPDATE_FIELDS = VERSION_IDENTITY_FIELDS | {
    "organization",
    "scenario",
    "supersedes",
}


def _format_datetime(value):
    if value is None:
        return None
    if timezone.is_naive(value):
        raise ValidationError("As datas da configuração devem incluir fuso horário.")
    value = value.astimezone(datetime_timezone.utc)
    timespec = "microseconds" if value.microsecond else "seconds"
    return value.isoformat(timespec=timespec).replace("+00:00", "Z")


class ControlScenarioVersionQuerySet(OrganizationScopedQuerySet):
    def update(self, **kwargs):
        if kwargs.get("state") == "approved":
            raise ValidationError(
                "A aprovação deve validar e guardar o snapshot completo."
            )
        if VERSION_IDENTITY_UPDATE_FIELDS.intersection(kwargs):
            raise ValidationError(
                "A identidade e a linhagem da versão são imutáveis."
            )
        if APPROVED_IMMUTABLE_FIELDS.intersection(kwargs) and self.filter(
            state="approved"
        ).exists():
            raise ValidationError(
                "Uma versão aprovada do cenário não pode ser alterada."
            )
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        objs = list(objs)
        for obj in objs:
            obj.full_clean()
        return super().bulk_create(objs, **kwargs)

    def delete(self):
        if self.filter(state="approved").exists():
            raise ValidationError(
                "Uma versão aprovada do cenário não pode ser eliminada."
            )
        return super().delete()


class ControlScenario(OrganizationScopedModel):
    key = models.CharField(
        max_length=100,
        validators=[
            RegexValidator(
                regex=r"^[A-Z][A-Z0-9_]*$",
                message=(
                    "A chave deve usar letras maiúsculas, números e underscores."
                ),
            )
        ],
    )
    active_version = models.ForeignKey(
        "ControlScenarioVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="active_for_scenarios",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "key"),
                name="uniq_control_scenario_org_key",
            )
        ]
        ordering = ("key",)

    def clean(self):
        super().clean()
        errors = {}
        if not self._state.adding:
            previous = ControlScenario.objects.filter(id=self.id).values(
                "key",
                "organization_id",
            ).first()
            if previous and previous["key"] != self.key:
                errors["key"] = "A chave do cenário é imutável."
            if previous and previous["organization_id"] != self.organization_id:
                errors["organization"] = "A organização do cenário é imutável."

        if self.active_version_id:
            active_version = self.active_version
            if active_version.scenario_id != self.id:
                errors["active_version"] = (
                    "A versão ativa pertence a outro cenário."
                )
            elif active_version.organization_id != self.organization_id:
                errors["active_version"] = (
                    "A versão ativa pertence a outra organização."
                )
            elif active_version.state != ControlScenarioVersion.State.APPROVED:
                errors["active_version"] = "A versão ativa tem de estar aprovada."
            elif active_version.effective_from > timezone.localdate():
                errors["active_version"] = (
                    "A versão ainda não atingiu a data de entrada em vigor."
                )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.key


class ControlScenarioVersion(OrganizationScopedModel):
    class State(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        APPROVED = "approved", "Aprovada"

    scenario = models.ForeignKey(
        ControlScenario,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version = models.PositiveIntegerField()
    state = models.CharField(
        max_length=20,
        choices=State.choices,
        default=State.DRAFT,
    )
    organization_name = models.CharField(max_length=200)
    name = models.CharField(max_length=200)
    description = models.TextField()
    objective = models.JSONField(default=dict, blank=True)
    risk = models.JSONField(default=dict, blank=True)
    control = models.JSONField(default=dict, blank=True)
    monitoring = models.JSONField(default=dict, blank=True)
    rules = models.JSONField(default=list, blank=True)
    limitations = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_control_scenario_versions",
    )
    created_by_email = models.EmailField()
    created_by_user_id = models.UUIDField()
    created_by_role = models.CharField(
        max_length=20,
        choices=CREATOR_ROLE_CHOICES,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_control_scenario_versions",
    )
    approved_by_email = models.EmailField(blank=True)
    approved_by_user_id = models.UUIDField(null=True, blank=True)
    approved_by_role = models.CharField(
        max_length=20,
        choices=((Membership.Role.OWNER, "Proprietário"),),
        blank=True,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    effective_from = models.DateField(null=True, blank=True)
    approval_note = models.TextField(blank=True)
    change_reason = models.TextField()
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="superseded_by_versions",
    )
    config_hash = models.CharField(
        max_length=64,
        blank=True,
        validators=[
            MinLengthValidator(64),
            RegexValidator(
                regex=r"^[0-9a-f]{64}$",
                message="O hash deve ser um SHA-256 hexadecimal em minúsculas.",
            ),
        ],
    )

    objects = ControlScenarioVersionQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("scenario", "version"),
                name="uniq_control_scenario_version",
            ),
            models.UniqueConstraint(
                fields=("supersedes",),
                condition=Q(supersedes__isnull=False),
                name="uniq_control_scenario_superseder",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1),
                name="control_scenario_version_positive",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(created_by_email="")
                    & Q(
                        created_by_role__in=(
                            Membership.Role.OWNER,
                            Membership.Role.ANALYST,
                        )
                    )
                    & ~Q(organization_name="")
                    & ~Q(name="")
                    & ~Q(description="")
                    & ~Q(change_reason="")
                ),
                name="control_scenario_required_snapshots",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        state="draft",
                        approved_at__isnull=True,
                        approved_by_email="",
                        approved_by_role="",
                        approved_by_user_id__isnull=True,
                        approval_note="",
                        config_hash="",
                        effective_from__isnull=True,
                    )
                    | (
                        Q(
                            state="approved",
                            approved_at__isnull=False,
                            approved_by_role=Membership.Role.OWNER,
                            approved_by_user_id__isnull=False,
                            effective_from__isnull=False,
                        )
                        & ~Q(approved_by_email="")
                        & ~Q(approval_note="")
                        & ~Q(config_hash="")
                    )
                ),
                name="control_scenario_approval_consistent",
            ),
        ]
        ordering = ("scenario__key", "-version")

    def _persisted_values(self):
        if self._state.adding:
            return None
        fields = APPROVED_IMMUTABLE_FIELDS | VERSION_IDENTITY_FIELDS | {"state"}
        return ControlScenarioVersion.objects.filter(id=self.id).values(
            *fields
        ).first()

    def _validate_immutable_fields(self, previous, errors):
        if not previous:
            return
        for field in VERSION_IDENTITY_FIELDS:
            if previous[field] != getattr(self, field):
                error_field = {
                    "organization_id": "organization",
                    "scenario_id": "scenario",
                    "supersedes_id": "supersedes",
                }.get(field, field)
                errors[error_field] = (
                    "A identidade e a linhagem da versão são imutáveis."
                )
        if previous["state"] == self.State.APPROVED:
            for field in APPROVED_IMMUTABLE_FIELDS:
                if previous[field] != getattr(self, field):
                    errors[field] = (
                        "Uma versão aprovada do cenário não pode ser alterada."
                    )

    def _validate_creator(self, errors):
        if not self._state.adding:
            return
        if self.created_by is None:
            errors["created_by"] = "O criador do rascunho é obrigatório."
            return
        membership_exists = Membership.objects.filter(
            organization_id=self.organization_id,
            user=self.created_by,
            is_active=True,
            role=self.created_by_role,
            role__in=(Membership.Role.OWNER, Membership.Role.ANALYST),
        ).exists()
        if not membership_exists:
            errors["created_by"] = (
                "O criador deve ser proprietário ou analista ativo da organização."
            )
        if self.created_by_email != self.created_by.email:
            errors["created_by_email"] = (
                "O email guardado não corresponde ao criador."
            )
        if self.created_by_user_id != self.created_by_id:
            errors["created_by_user_id"] = (
                "O UUID guardado não corresponde ao criador."
            )

    def _validate_approval(self, *, previous, errors):
        if self.state != self.State.APPROVED:
            return
        if self._state.adding:
            errors["state"] = (
                "Uma versão deve ser guardada como rascunho antes da aprovação."
            )
            return
        is_approval_transition = previous and previous["state"] == self.State.DRAFT
        if is_approval_transition:
            if self.approved_by is None:
                errors["approved_by"] = "O aprovador é obrigatório."
            else:
                is_active_owner = Membership.objects.filter(
                    organization_id=self.organization_id,
                    user=self.approved_by,
                    is_active=True,
                    role=Membership.Role.OWNER,
                ).exists()
                if not is_active_owner:
                    errors["approved_by"] = (
                        "O aprovador deve ser proprietário ativo da organização."
                    )
                if self.approved_by_email != self.approved_by.email:
                    errors["approved_by_email"] = (
                        "O email guardado não corresponde ao aprovador."
                    )
                if self.approved_by_user_id != self.approved_by_id:
                    errors["approved_by_user_id"] = (
                        "O UUID guardado não corresponde ao aprovador."
                    )
        if self.approved_by_role != Membership.Role.OWNER:
            errors["approved_by_role"] = (
                "A aprovação exige o papel de proprietário."
            )
        if self.approved_at and self.effective_from:
            if timezone.is_naive(self.approved_at):
                errors["approved_at"] = "A aprovação deve incluir fuso horário."
            elif self.effective_from < self.approved_at.astimezone(
                datetime_timezone.utc
            ).date():
                errors["effective_from"] = (
                    "A entrada em vigor não pode anteceder a aprovação."
                )
        try:
            validate_configuration(
                objective=self.objective,
                risk=self.risk,
                control=self.control,
                monitoring=self.monitoring,
                rules=self.rules,
                limitations=self.limitations,
            )
        except ControlScenarioContractError as exc:
            errors[NON_FIELD_ERRORS] = str(exc)

    def _validate_lineage(self, errors):
        if self.scenario_id and self.organization_id:
            if self.scenario.organization_id != self.organization_id:
                errors["scenario"] = (
                    "O cenário pertence a outra organização."
                )
        if self.version == 1:
            if self.supersedes_id is not None:
                errors["supersedes"] = (
                    "A primeira versão não pode substituir outra versão."
                )
            return
        if self.version and self.version > 1:
            if self.supersedes_id is None:
                errors["supersedes"] = (
                    "Uma versão posterior deve identificar a versão anterior."
                )
                return
            if self.supersedes_id == self.id:
                errors["supersedes"] = "Uma versão não pode substituir-se a si própria."
            elif self.supersedes.scenario_id != self.scenario_id:
                errors["supersedes"] = (
                    "A versão anterior pertence a outro cenário."
                )
            elif self.supersedes.organization_id != self.organization_id:
                errors["supersedes"] = (
                    "A versão anterior pertence a outra organização."
                )
            elif self.supersedes.state != self.State.APPROVED:
                errors["supersedes"] = "A versão anterior deve estar aprovada."
            elif self.supersedes.version != self.version - 1:
                errors["supersedes"] = (
                    "As versões do cenário devem ser consecutivas."
                )

    def clean(self):
        super().clean()
        errors = {}
        previous = self._persisted_values()
        self._validate_immutable_fields(previous, errors)
        self._validate_creator(errors)
        self._validate_lineage(errors)

        if self._state.adding and self.organization_id:
            if self.organization_name != self.organization.name:
                errors["organization_name"] = (
                    "O nome guardado não corresponde à organização."
                )
        if self.state == self.State.DRAFT:
            approval_values = (
                self.approved_by_id,
                self.approved_by_email,
                self.approved_by_role,
                self.approved_by_user_id,
                self.approved_at,
                self.effective_from,
                self.approval_note,
                self.config_hash,
            )
            if any(approval_values):
                errors["state"] = (
                    "Um rascunho não pode conter dados de aprovação."
                )
        else:
            if self.organization_name != self.organization.name:
                errors["organization_name"] = (
                    "O nome da organização deve ser atualizado antes da aprovação."
                )
            self._validate_approval(previous=previous, errors=errors)
        if errors:
            raise ValidationError(errors)

    def to_contract_payload(self):
        if self.state != self.State.APPROVED:
            raise ValidationError(
                "Apenas versões aprovadas possuem um payload contratual."
            )
        payload = {
            "contract": CONTROL_SCENARIO_CONTRACT,
            "control": self.control,
            "governance": {
                "approval_note": self.approval_note,
                "approved_at": _format_datetime(self.approved_at),
                "approved_by": {
                    "email": self.approved_by_email,
                    "role": self.approved_by_role,
                    "user_id": (
                        str(self.approved_by_user_id)
                        if self.approved_by_user_id
                        else None
                    ),
                },
                "change_reason": self.change_reason,
                "created_at": _format_datetime(self.created_at),
                "created_by": {
                    "email": self.created_by_email,
                    "role": self.created_by_role,
                    "user_id": str(self.created_by_user_id),
                },
                "effective_from": (
                    self.effective_from.isoformat() if self.effective_from else None
                ),
                "state": self.state,
                "supersedes_version_id": (
                    str(self.supersedes_id) if self.supersedes_id else None
                ),
            },
            "limitations": self.limitations,
            "monitoring": self.monitoring,
            "objective": self.objective,
            "organization": {
                "id": str(self.organization_id),
                "name": self.organization_name,
            },
            "risk": self.risk,
            "rules": self.rules,
            "scenario": {
                "description": self.description,
                "id": str(self.scenario_id),
                "key": self.scenario.key,
                "name": self.name,
                "version": self.version,
                "version_id": str(self.id),
            },
        }
        payload["integrity"] = {
            "algorithm": "sha256",
            "payload_hash": calculate_payload_hash(payload),
        }
        return payload

    def save(self, *args, **kwargs):
        if self.state == self.State.APPROVED:
            if self._state.adding:
                raise ValidationError(
                    "Uma versão deve ser guardada como rascunho antes da aprovação."
                )
            payload = self.to_contract_payload()
            self.config_hash = payload["integrity"]["payload_hash"]
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {"config_hash"}
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.state == self.State.APPROVED:
            raise ValidationError(
                "Uma versão aprovada do cenário não pode ser eliminada."
            )
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.scenario.key} v{self.version}"
