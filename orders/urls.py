from django.urls import path
from .views import *

urlpatterns = [
    path('create/', OrderCreateAPIView.as_view()),
    path('webhook/', PaynetWebhookAPIView.as_view()),
]