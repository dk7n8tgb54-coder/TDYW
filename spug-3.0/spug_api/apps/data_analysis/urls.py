from django.urls import path
from . import views

app_name = 'data_analysis'

urlpatterns = [
    path('overview/', views.overview_view, name='overview'),
    path('fault/', views.fault_view, name='fault'),
    path('interference/', views.interference_view, name='interference'),
    path('device/', views.device_view, name='device'),
    path('upgrade/', views.upgrade_view, name='upgrade'),
]
