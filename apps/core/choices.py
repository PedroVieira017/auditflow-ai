from django.db import models


class Severity(models.TextChoices):
    LOW = "low", "Baixo"
    MEDIUM = "medium", "Medio"
    HIGH = "high", "Alto"
    CRITICAL = "critical", "Critico"

