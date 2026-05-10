from django.shortcuts import render


def landing(request):
    """Landing page view"""
    return render(request, 'landing.html')
