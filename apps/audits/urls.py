from django.urls import path

from . import views


urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("mi-historial/", views.institution_history, name="institution_history"),
    path("direccion/", views.DirectorDashboardView.as_view(), name="director_dashboard"),
    path(
        "direccion/estadisticas/",
        views.DirectorStatisticsView.as_view(),
        name="director_statistics",
    ),
    path(
        "direccion/estadisticas/exportar.xlsx",
        views.DirectorStatisticsXlsxView.as_view(),
        name="director_statistics_xlsx",
    ),
    path(
        "direccion/centros-educativos/",
        views.DirectorEducationalCenterListView.as_view(),
        name="director_educational_centers",
    ),
    path(
        "direccion/centros-educativos/<int:pk>/",
        views.DirectorEducationalCenterDetailView.as_view(),
        name="director_educational_center_detail",
    ),
    path(
        "direccion/centros-educativos/<int:pk>/activar/",
        views.director_activate_educational_center,
        name="director_activate_educational_center",
    ),
    path("direccion/decisiones/", views.director_decision_list, name="director_decisions"),
    path(
        "direccion/decisiones/<int:pk>/",
        views.director_decision_detail,
        name="director_decision_detail",
    ),
    path(
        "direccion/expedientes/<int:pk>/reasignar/",
        views.director_reassign_case,
        name="director_reassign_case",
    ),
    path("expedientes/", views.CaseListView.as_view(), name="case_list"),
    path("expedientes/nuevo/", views.case_create, name="case_create"),
    path("expedientes/<int:pk>/", views.case_detail, name="case_detail"),
    path("expedientes/<int:pk>/editar/", views.case_edit, name="case_edit"),
    path("expedientes/<int:pk>/contenido/", views.case_builder, name="case_builder"),
    path(
        "expedientes/<int:pk>/informe/cargar/",
        views.case_report_upload,
        name="case_report_upload",
    ),
    path(
        "expedientes/<int:pk>/importar-recomendaciones/",
        views.case_import_recommendations,
        name="case_import_recommendations",
    ),
    path("expedientes/<int:pk>/publicar/", views.case_publish, name="case_publish"),
    path(
        "expedientes/<int:pk>/solicitar-cierre/",
        views.request_case_closure,
        name="request_case_closure",
    ),
    path("expedientes/<int:pk>/informe/", views.download_report, name="download_report"),
    path(
        "documentos/<int:pk>/descargar/",
        views.download_audit_document,
        name="download_audit_document",
    ),
    path(
        "documentos-historicos/",
        views.historical_document_list,
        name="historical_document_list",
    ),
    path(
        "documentos-historicos/nuevo/",
        views.historical_document_create,
        name="historical_document_create",
    ),
    path(
        "documentos-historicos/<int:pk>/",
        views.historical_document_detail,
        name="historical_document_detail",
    ),
    path(
        "documentos-historicos/<int:document_pk>/recomendaciones/nueva/",
        views.historical_recommendation_create,
        name="historical_recommendation_create",
    ),
    path("expedientes/<int:case_pk>/hallazgos/nuevo/", views.finding_create, name="finding_create"),
    path("hallazgos/<int:pk>/editar/", views.finding_edit, name="finding_edit"),
    path("hallazgos/<int:pk>/eliminar/", views.finding_delete, name="finding_delete"),
    path(
        "hallazgos/<int:finding_pk>/recomendaciones/nueva/",
        views.recommendation_create,
        name="recommendation_create",
    ),
    path("recomendaciones/<int:pk>/editar/", views.recommendation_edit, name="recommendation_edit"),
    path(
        "recomendaciones/<int:pk>/eliminar/",
        views.recommendation_delete,
        name="recommendation_delete",
    ),
    path("recomendaciones/<int:pk>/responder/", views.respond_recommendation, name="respond_recommendation"),
    path(
        "recomendaciones/<int:pk>/prorroga/",
        views.grant_deadline_extension,
        name="grant_deadline_extension",
    ),
    path("respuestas/<int:pk>/revisar/", views.review_response, name="review_response"),
    path("respuestas/<int:pk>/constancia/", views.response_receipt, name="response_receipt"),
    path("evidencias/<int:pk>/descargar/", views.download_evidence, name="download_evidence"),
]
