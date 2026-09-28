from django import forms
from django.contrib.auth.forms import AdminUserCreationForm as DjangoAdminUserCreationForm
from django.contrib.auth.forms import UserChangeForm

from .models import User, validate_pin


class AdminUserCreationForm(DjangoAdminUserCreationForm):
    class Meta(DjangoAdminUserCreationForm.Meta):
        model = User
        fields = ("username", "role")


class AdminUserChangeForm(UserChangeForm):
    new_pin = forms.CharField(
        label="Nuevo PIN",
        required=False,
        strip=False,
        validators=[validate_pin],
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "inputmode": "numeric"}),
        help_text="Deja vacío para conservar el PIN actual. Usa entre 4 y 12 dígitos.",
    )
    confirm_pin = forms.CharField(
        label="Confirmar nuevo PIN",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "inputmode": "numeric"}),
    )

    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("new_pin", "") != cleaned.get("confirm_pin", ""):
            self.add_error("confirm_pin", "Los PIN no coinciden.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("new_pin"):
            user.set_pin(self.cleaned_data["new_pin"])
        if commit:
            user.save()
            self.save_m2m()
        return user
