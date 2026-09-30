from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("api/webhooks", views.WebhookViewSet)

urlpatterns = [
    path("api/webhooks/events", views.webhook_events),  # must come before the router's detail route
    path("webhooks", views.webhooks_page),
    *router.urls,
]
