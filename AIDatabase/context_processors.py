from decouple import config

def base_url(request):
    return {'base_url': config('BASE_URL', default=request.build_absolute_uri('/').rstrip('/'))}
