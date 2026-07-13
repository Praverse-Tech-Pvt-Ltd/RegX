from decouple import config

def base_url(request):
    print("BASE_URL from os.environ:",config('BASE_URL'))
    return {'base_url': config('BASE_URL')}
