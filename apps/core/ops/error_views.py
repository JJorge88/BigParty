from django.shortcuts import render


def response(request, code):
    return render(request,'errors/error.html',{'code':code,'reference':getattr(request,'support_reference','')},status=code)
def bad_request(request,exception=None):return response(request,400)
def forbidden(request,exception=None):return response(request,403)
def not_found(request,exception=None):return response(request,404)
def server_error(request):return response(request,500)
