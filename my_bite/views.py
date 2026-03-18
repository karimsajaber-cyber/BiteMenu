from django.shortcuts import render, redirect
from .models import User, Restaurant, MenuItem, Order
from django.contrib import messages
import bcrypt
import random
from datetime import datetime, timedelta


def index(request):
    return render(request, 'index.html')


# ====== REGISTER AND LOGIN =======
def register(request):
    if request.method == "POST":

        errors = User.objects.register_validator(request.POST)

        if errors:
            for key, value in errors.items():
                messages.error(request, value)
            return redirect('index')

        hashed_pw = bcrypt.hashpw(
            request.POST['password'].encode(), bcrypt.gensalt()
        ).decode()

        user = User.objects.create(
            first_name=request.POST['first_name'],
            last_name=request.POST['last_name'],
            email=request.POST['email'],
            password=hashed_pw,
            role=request.POST['role']
        )

        request.session['user_id'] = user.id
        request.session['role'] = user.role

        if user.role == 'admin':
            return redirect('admin_dashboard')
        else:
            return redirect('owner_dashboard')

    return redirect('index')


def login(request):
    if request.method == "POST":

        user = User.objects.filter(email=request.POST['email']).first()

        if not user:
            messages.error(request, "Invalid email or password")
            return redirect('index')

        if not bcrypt.checkpw(request.POST['password'].encode(), user.password.encode()):
            messages.error(request, "Invalid email or password")
            return redirect('index')

        request.session['user_id'] = user.id
        request.session['role'] = user.role

        if user.role == 'admin':
            return redirect('admin_dashboard')
        else:
            return redirect('owner_dashboard')

    return redirect('index')


def logout(request):
    request.session.flush()
    return redirect('index')


# ===== ADMIN DASHBOARD =====
def admin_dashboard(request):

    if 'user_id' not in request.session:
        return redirect('index')

    restaurants = Restaurant.objects.all()

    return render(request, 'admin_dashboard.html', {'restaurants': restaurants})


def create_restaurant(request):

    if request.method == "POST":

        owner = User.objects.get(id=request.POST['owner_id'])

        Restaurant.objects.create(
            name=request.POST['name'],
            description=request.POST['description'],
            owner=owner
        )

    return redirect('admin_dashboard')


# ✅ FIX: إضافة delete restaurant
def delete_restaurant(request, restaurant_id):
    Restaurant.objects.get(id=restaurant_id).delete()
    return redirect('admin_dashboard')


# ===== OWNER DASHBOARD =====
def owner_dashboard(request):

    if 'user_id' not in request.session:
        return redirect('index')

    user = User.objects.get(id=request.session['user_id'])

    restaurant = Restaurant.objects.filter(owner=user).first()

    menu_items = MenuItem.objects.filter(restaurant=restaurant)

    orders = Order.objects.filter(restaurant=restaurant)

    context = {
        'restaurant': restaurant,
        'menu_items': menu_items,
        'orders': orders
    }

    return render(request, 'owner_dashboard.html', context)


# ===== ADD ITEM =====
def add_menu_item(request, restaurant_id):
    return render(request, 'add_item.html', {'restaurant_id': restaurant_id})


# ===== CREATE ITEM =====
def create_menu_item(request, restaurant_id):

    if request.method == "POST":

        errors = MenuItem.objects.item_validator(request.POST)

        if errors:
            for key, value in errors.items():
                messages.error(request, value)
            return redirect(f'/add_item/{restaurant_id}')

        restaurant = Restaurant.objects.get(id=restaurant_id)

        MenuItem.objects.create(
            name=request.POST['name'],
            price=request.POST['price'],
            quantity=request.POST['quantity'],
            restaurant=restaurant
        )

    return redirect('owner_dashboard')


# ===== CUSTOMER =====
def restaurants(request):
    restaurants = Restaurant.objects.all()
    return render(request, 'restaurants.html', {'restaurants': restaurants})


def menu(request, restaurant_id):

    restaurant = Restaurant.objects.get(id=restaurant_id)
    items = MenuItem.objects.filter(restaurant=restaurant)

    return render(request, 'menu.html', {
        'restaurant': restaurant,
        'items': items
    })



def my_orders(request):
    orders = Order.objects.filter(status__in=['pending', 'confirmed', 'preparing'])
    return render(request, 'my_orders.html', {'orders': orders})


# ===== CREATE ORDER =====
def create_order(request):

    if request.method == "POST":

        errors = Order.objects.order_validator(request.POST)

        if errors:
            for key, value in errors.items():
                messages.error(request, value)
            return redirect('restaurants')

    
        item = MenuItem.objects.filter(id=request.POST['item_id']).first()

        if not item:
            messages.error(request, "Item not found")
            return redirect('restaurants')


        try:
            quantity = int(request.POST.get('quantity', 0))
        except:
            messages.error(request, "Invalid quantity")
            return redirect(f'/menu/{item.restaurant.id}')

        if quantity <= 0:
            messages.error(request, "Invalid quantity")
            return redirect(f'/menu/{item.restaurant.id}')

        if quantity > item.quantity:
            messages.error(request, "Sold out / Not enough quantity")
            return redirect(f'/menu/{item.restaurant.id}')

        total_price = item.price * quantity


        Order.objects.create(
            restaurant=item.restaurant,
            menu_item=item,
            quantity=quantity,
            total_price=total_price,
            note=request.POST.get('note', '')
        )


        item.quantity -= quantity

        if item.quantity == 0:
            item.status = 'sold_out'

        item.save()

        return redirect(f'/menu/{item.restaurant.id}')

    return redirect('restaurants')



def update_order(request, order_id):

    if 'user_id' not in request.session:
        return redirect('index')

    if request.method == "POST":

        order = Order.objects.get(id=order_id)

        new_status = request.POST.get('status')
        manual_time = request.POST.get('expected_time')

        if manual_time:
            order.expected_time = manual_time
        else:
            prep_minutes = 5 + random.randint(0, 10)
            order.expected_time = datetime.now() + timedelta(minutes=prep_minutes)

        order.status = new_status
        order.save()

        return redirect('owner_dashboard')

    return redirect('owner_dashboard')



def cancel_order(request, order_id):

    if 'user_id' not in request.session:
        return redirect('index')

    order = Order.objects.get(id=order_id)

    item = order.menu_item
    item.quantity += order.quantity

    if item.quantity > 0:
        item.status = 'available'

    item.save()

    order.status = 'cancelled'
    order.save()

    return redirect('restaurants')



def owner_cancel_order(request, order_id):

    if 'user_id' not in request.session:
        return redirect('index')

    order = Order.objects.get(id=order_id)

    item = order.menu_item
    item.quantity += order.quantity
    item.status = 'available'
    item.save()

    order.status = 'cancelled'
    order.save()

    return redirect('owner_dashboard')



def update_restaurant_note(request):

    if 'user_id' not in request.session:
        return redirect('index')

    user = User.objects.get(id=request.session['user_id'])
    restaurant = Restaurant.objects.filter(owner=user).first()

    restaurant.note = request.POST['note']
    restaurant.save()

    return redirect('owner_dashboard')