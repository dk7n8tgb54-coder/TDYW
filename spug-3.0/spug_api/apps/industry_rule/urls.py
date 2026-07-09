# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import path

from .views import (
    IndustryRuleListView,
    IndustryRuleCreateView,
    IndustryRuleDetailView,
    IndustryRuleRetireView,
    IndustryRuleAttachView,
    IndustryRuleCategoriesView,
)

urlpatterns = [
    path('', IndustryRuleListView.as_view()),
    path('create/', IndustryRuleCreateView.as_view()),
    path('categories/', IndustryRuleCategoriesView.as_view()),
    path('<int:r_id>/', IndustryRuleDetailView.as_view()),
    path('<int:r_id>/retire/', IndustryRuleRetireView.as_view()),
    path('<int:r_id>/attachments/', IndustryRuleAttachView.as_view()),
    path('<int:r_id>/attach/', IndustryRuleAttachView.as_view()),
    path('<int:r_id>/attach/<int:att_id>/', IndustryRuleAttachView.as_view()),
]
