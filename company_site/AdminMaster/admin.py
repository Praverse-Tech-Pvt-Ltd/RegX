from django.contrib import admin
from .models import *
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .forms import CustomUserCreationForm, CustomUserChangeForm
from .models import CustomUser

class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = CustomUser
    list_display = ['username', 'email', 'role', 'is_staff']

    fieldsets = (
        (None, {'fields': ('username',)}),
        ('Personal info', {'fields': (
            'first_name', 'last_name', 'email',
            'contact_number', 'address_line', 'city', 'state', 'country', 'pincode',
            'company_name', 'designation', 'description', 'location', 'reports',

          'role', 'logo', 'footprint_ID','login_token','internal_team','fda_deficiency_database','complete_response_database','subscription_end_date'
        )}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'username', 'password1', 'password2', 'email',
                'contact_number', 'address_line', 'city', 'state', 'country', 'pincode',
                'company_name', 'designation', 'description', 'location', 'reports',
                'role', 'logo', 'footprint_ID','login_token','internal_team',
                'fda_deficiency_database','complete_response_database',
                'is_staff', 'is_superuser'
            ),
        }),
    )

admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(AssignChecker)
