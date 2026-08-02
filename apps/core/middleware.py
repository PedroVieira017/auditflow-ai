from django.conf import settings
from django.http import HttpResponse


class RequestBodySizeLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in {"POST", "PUT", "PATCH"}:
            content_length = request.META.get("CONTENT_LENGTH")
            if content_length:
                try:
                    request_size = int(content_length)
                except (TypeError, ValueError):
                    request_size = 0

                if request_size > settings.MAX_REQUEST_BODY_SIZE_BYTES:
                    return HttpResponse("Pedido demasiado grande.", status=413)

        return self.get_response(request)
