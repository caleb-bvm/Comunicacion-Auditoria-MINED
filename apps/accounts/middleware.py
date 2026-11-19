from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse


class MustChangePasswordMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.user.must_change_password:
            try:
                allowed_paths = {
                    reverse("password_change"),
                    reverse("logout"),
                    reverse("service_worker"),
                    reverse("offline"),
                }
            except NoReverseMatch:
                allowed_paths = set()
            if request.path not in allowed_paths and not request.path.startswith("/static/"):
                return redirect("password_change")
        return self.get_response(request)

