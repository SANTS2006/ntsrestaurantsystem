from django.urls import path

from . import builder
from . import views as v

urlpatterns = [
    path("public/contact/", v.ContactSubmitView.as_view()),
    path("public/content/", v.PublicContentView.as_view()),
    path("messages/", v.MessageList.as_view()),
    path("messages/<int:pk>/", v.MessageDetail.as_view()),
    path("public/pages/", builder.PublicPagesView.as_view()),
    path("builder/", builder.BuilderView.as_view()),
    path("builder/images/", builder.BuilderImageView.as_view()),
    path("builder/pages/<slug:page>/", builder.BuilderPageView.as_view()),
    path("content/", v.ContentView.as_view()),
    path("content/images/<slug:slot>/", v.ContentImageView.as_view()),
]
