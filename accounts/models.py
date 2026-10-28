from datetime import timedelta

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models, transaction
from django.utils import timezone

from core.provinces import PROVINCE_CHOICES


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email).lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", User.Role.CUSTOMER)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        """Used by `createsuperuser` to create the first admin (FR-X13)."""
        extra_fields["role"] = User.Role.ADMIN
        return self._create_user(email, password, **extra_fields)

    def get_by_natural_key(self, email):
        return self.get(email__iexact=email)


class User(AbstractBaseUser):
    """One account table for every role; signs in with email (FR-X01).

    Permissions are not configurable per module (out of scope #05): the role
    alone decides what an account can do.
    """

    class Role(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Customer"
        STAFF = "STAFF", "Staff"
        ADMIN = "ADMIN", "Admin"

    LOCKOUT_THRESHOLD = 5
    LOCKOUT_DURATION = timedelta(minutes=15)

    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, blank=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CUSTOMER)
    is_active = models.BooleanField(default=True)
    failed_login_count = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        ordering = ["email"]

    def __str__(self):
        return self.email

    # ---- names --------------------------------------------------------
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.first_name

    # ---- roles --------------------------------------------------------
    @property
    def is_customer(self):
        return self.role == self.Role.CUSTOMER

    @property
    def is_backoffice(self):
        return self.role in (self.Role.STAFF, self.Role.ADMIN)

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN

    # Django admin compatibility: only Admin-role accounts may open it.
    @property
    def is_staff(self):
        return self.is_active and self.is_admin_role

    @property
    def is_superuser(self):
        return self.is_staff

    def has_perm(self, perm, obj=None):
        return self.is_staff

    def has_perms(self, perm_list, obj=None):
        return self.is_staff

    def has_module_perms(self, app_label):
        return self.is_staff

    # ---- lockout (FR-C01) ----------------------------------------------
    def is_locked(self, now=None):
        now = now or timezone.now()
        return self.locked_until is not None and self.locked_until > now

    def register_failed_login(self, now=None):
        """Count a failed attempt; lock the account on the fifth."""
        now = now or timezone.now()
        if self.locked_until and self.locked_until <= now:
            # A previous lock has expired: start counting again.
            self.failed_login_count = 0
            self.locked_until = None
        self.failed_login_count += 1
        if self.failed_login_count >= self.LOCKOUT_THRESHOLD:
            self.locked_until = now + self.LOCKOUT_DURATION
        self.save(update_fields=["failed_login_count", "locked_until"])

    def reset_failed_logins(self):
        if self.failed_login_count or self.locked_until:
            self.failed_login_count = 0
            self.locked_until = None
            self.save(update_fields=["failed_login_count", "locked_until"])


class Address(models.Model):
    """A delivery address in a customer's address book (FR-C02)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    recipient = models.CharField(max_length=150)
    phone = models.CharField(max_length=30)
    province = models.CharField(max_length=50, choices=PROVINCE_CHOICES)
    district = models.CharField(max_length=100)
    line_1 = models.CharField("Address line", max_length=255)
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_default", "id"]
        verbose_name_plural = "addresses"

    def __str__(self):
        return f"{self.recipient}, {self.line_1}, {self.district}, {self.province}"

    @transaction.atomic
    def make_default(self):
        """Exactly one default address per customer."""
        Address.objects.filter(user=self.user).exclude(pk=self.pk).update(is_default=False)
        if not self.is_default:
            self.is_default = True
            self.save(update_fields=["is_default"])
