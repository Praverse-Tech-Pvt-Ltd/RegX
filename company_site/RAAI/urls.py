from django.contrib import admin
from django.conf.urls.static import static
from django.conf import settings
from django.urls import path, include
from RATools.views import about_alpesh, home,terms_of_use,privacy_policy
from django.conf.urls.static import static
from django.conf import settings

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home),
    path('about-alpesh/', about_alpesh),
    path("termsofuse/",terms_of_use),
    path("privacy-policy/",privacy_policy),
    path('ratools/', include('RATools.urls')),
    path('aidatabase/', include('AIDatabase.urls')),
    path('adminmaster/', include('AdminMaster.urls')),
] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT) + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
