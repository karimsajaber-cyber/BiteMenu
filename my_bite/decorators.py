from django.shortcuts import redirect

def login_required(func):
    def wrapper(request, *args, **kwargs):
        print("LOGIN CHECK:", dict(request.session))
        if 'user_id' not in request.session:
            return redirect('index')
        return func(request, *args, **kwargs)
    return wrapper


def admin_required(func):
    def wrapper(request, *args, **kwargs):
        if request.session.get('role') != 'admin':
            return redirect('index')
        return func(request, *args, **kwargs)
    return wrapper


def owner_required(func):
    def wrapper(request, *args, **kwargs):
        print("ROLE CHECK:", request.session.get('role'))
        if request.session.get('role') != 'owner':
            return redirect('index')
        return func(request, *args, **kwargs)
    return wrapper