from django.urls import path
from debugdna import views
from skillradar import views as radar_views
from growthplan import views as plan_views
from skillradar import diagnosis_views
from growthplan import diagnosis_views as diagnosis_plan_views
from dashboard import views as dashboard_views
from growthplan import task_views

urlpatterns = [path('', dashboard_views.index, name='dashboard'), path('api/dashboard/', dashboard_views.data),
               path('debugdna/', views.index, name='debugdna'), path('api/analyze/', views.analyze),
               path('api/debugdna/history/', views.history),
               path('api/debugdna/analyses/<uuid:pk>/', views.detail),
               path('api/debugdna/insights/', views.insights),
               path('api/debugdna/skills/', views.skills),
               path('skillradar/', radar_views.index, name='skillradar'),
               path('api/skillradar/analyze/', radar_views.analyze, name='skillradar-analyze'),
               path('api/skillradar/collect/', radar_views.collect, name='skillradar-collect'),
               path('api/skillradar/evaluate/', radar_views.evaluate, name='skillradar-evaluate'),
               path('api/skillradar/diagnoses/', diagnosis_views.create),
               path('api/skillradar/diagnoses/history/', diagnosis_views.history),
               path('api/skillradar/diagnoses/<uuid:pk>/', diagnosis_views.detail),
               path('api/skillradar/diagnoses/<uuid:pk>/questions/', diagnosis_views.questions),
               path('api/skillradar/diagnoses/<uuid:pk>/attempts/', diagnosis_views.create_attempt),
               path('api/skillradar/attempts/<uuid:pk>/', diagnosis_views.attempt_detail),
               path('api/skillradar/attempts/<uuid:pk>/evaluate/', diagnosis_views.evaluate),
               path('growthplan/', plan_views.index, name='growthplan'),
               path('api/growthplan/from-diagnosis/', diagnosis_plan_views.generate),
               path('api/growthplan/roadmaps/', diagnosis_plan_views.history),
               path('api/growthplan/roadmaps/<uuid:pk>/', diagnosis_plan_views.detail),
               path('api/growthplan/tasks/<uuid:pk>/completion/', task_views.completion),
               path('api/growthplan/generate/', plan_views.generate, name='growthplan-generate')]
