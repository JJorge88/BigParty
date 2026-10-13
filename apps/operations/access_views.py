from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods


@never_cache
@sensitive_post_parameters('credential')
@require_http_methods(['GET', 'POST'])
def unified(request):
    if request.method == 'GET':
        return render(request, 'operations/unified_access.html')
    username = request.POST.get('username', '').strip()[:150]
    user = get_user_model().objects.filter(username__iexact=username, is_active=True).only('role').first()
    if not user or user.role not in ('CAJERO', 'GERENTE', 'PROPIETARIO'):
        return render(request, 'operations/unified_access.html', {
            'error': 'No pudimos ingresar. Revisa tu usuario y credencial.', 'username': username}, status=400)
    target = 'cash_operations:access' if user.role == 'CAJERO' else 'management:login'
    # 307 conserva el POST y CSRF dentro del mismo origen HTTPS; la vista final
    # valida la credencial y aplica su bloqueo de intentos habitual.
    response = HttpResponse(status=307)
    response['Location'] = reverse(target)
    return response
