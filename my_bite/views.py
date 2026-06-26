from datetime import datetime, timedelta
import bcrypt
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import random
import re
import uuid
import string
import requests
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
import json, os, urllib.request 
from .decorators import admin_required, login_required, owner_required
from .models import MenuItem, MenuOptionGroup, Order, OrderOption, Restaurant, User, PasswordResetToken
from voice_config import VOICE, normalize, number_to_arabic, pick
from django.core.mail import send_mail
from django.conf import settings





ACTIVE_ORDER_STATUSES = ['pending', 'confirmed', 'preparing', 'ready']
GROQ_TTS_TIMEOUT_SECONDS = 2
ELEVENLABS_TTS_TIMEOUT_SECONDS = 8
ELEVENLABS_STT_TIMEOUT_SECONDS = 30
GREETING_PHRASES = ["مرحبا", "اهلا", "كيفك", "شو الاخبار"]
REPEAT_PHRASES = ["عيد", "كرر", "ما سمعت", "اعيد", "مفهمتش", "مش سامع", "مرة ثانية", "كمان مرة"]
SHOW_ITEMS_PHRASES = ["شو في", "شو عندكم", "شو المتوفر", "ايش في"]
THANKS_PHRASES = ["شكرا", "يسلمو", "سلامتك", "مشكور", "يعطيك العافية", "لا شكرا", "غلبتك"]
YES_MORE_PHRASES = ["اه", "نعم", "ايوه", "بدّي", "اه بدي", "اكيد", "طبعا", "صحيح"]
NO_MORE_PHRASES = ["لا", "خلص", "لا شكرا", "مش حاب", "يخلف", "تؤ", "نو", "يسلموا لا"]
RESET_ORDER_PHRASES = ["الغي", "إلغي", "بلاش", "وقف", "ارجع", "رجوع", "ابدأ من جديد", "من اول", "غير الطلب", "بدل الطلب"]
CHANGE_ITEM_PHRASES = ["غير الصنف", "غير الطلب", "بدّي اشي ثاني", "بدي اشي ثاني", "اشي ثاني", "شي ثاني"]
CHANGE_SIZE_PHRASES = ["غير الحجم", "بدل الحجم", "حجم ثاني"]
CHANGE_QUANTITY_PHRASES = ["غير الكمية", "بدل الكمية", "كمية ثانية"]


def _parse_menu_option_groups(post_data):
    option_groups = []
    errors = []

    for group_index in post_data.getlist('option_group_index'):
        group_name = post_data.get(f'option_group_name_{group_index}', '').strip()
        option_names = post_data.getlist(f'option_name_{group_index}')
        option_prices = post_data.getlist(f'option_price_{group_index}')
        options = []

        for index, option_name in enumerate(option_names):
            option_name = option_name.strip()
            option_price = option_prices[index].strip() if index < len(option_prices) else '0'

            if not option_name:
                continue

            try:
                price_delta = Decimal(option_price or '0')
            except InvalidOperation:
                errors.append(f"Invalid option price for {option_name}")
                continue

            if price_delta < 0:
                errors.append(f"Option price for {option_name} cannot be negative")
                continue

            options.append({
                'name': option_name,
                'price_delta': price_delta
            })

        if not group_name and not options:
            continue

        if not group_name:
            errors.append("Every option group needs a name")
            continue

        if re.search(r'\+\s*\d+(?:\.\d+)?\s*$', group_name):
            errors.append(f"Put the extra price inside a choice, not in the group name: {group_name}")
            continue

        if not options:
            errors.append(f"{group_name} needs at least one option")
            continue

        option_groups.append({
            'name': group_name,
            'is_required': f'option_group_required_{group_index}' in post_data,
            'allow_multiple': f'option_group_multiple_{group_index}' in post_data,
            'options': options
        })

    return option_groups, errors


def _get_selected_order_options(item, post_data):
    selected_options = []
    errors = {}

    for group in item.option_groups.all():
        field_name = f'option_group_{group.id}'
        selected_ids = [
            option_id for option_id in post_data.getlist(field_name) if option_id
        ]

        if not selected_ids:
            if group.is_required:
                errors[item.id] = f"Please choose {group.name}"
            continue

        if not group.allow_multiple and len(selected_ids) > 1:
            errors[item.id] = f"Please choose only one option for {group.name}"
            continue

        available_options = {str(option.id): option for option in group.options.all()}

        for option_id in selected_ids:
            option = available_options.get(option_id)

            if not option:
                errors[item.id] = "Invalid menu option selected"
                continue

            selected_options.append(option)

    return selected_options, errors


def _build_orders_by_table(active_orders):
    grouped_orders = []
    tables = {}

    for order in active_orders:
        table_key = order.table_number if order.table_number is not None else "No table"
        customer_key = order.customer_session or "No session"

        if table_key not in tables:
            tables[table_key] = {
                'table_number': table_key,
                'orders': [],
                'sessions': {}
            }
            grouped_orders.append(tables[table_key])

        table_group = tables[table_key]
        table_group['orders'].append(order)

        if customer_key not in table_group['sessions']:
            table_group['sessions'][customer_key] = {
                'customer_session': customer_key,
                'orders': []
            }

        table_group['sessions'][customer_key]['orders'].append(order)

    for table_group in grouped_orders:
        table_group['sessions'] = list(table_group['sessions'].values())

    return grouped_orders


def index(request):
    return render(request, 'index.html')


def forgot_password(request):
    if request.method == "POST":
        email = request.POST.get("email", "").strip()

        user = User.objects.filter(email__iexact=email).first()

        if user:
            reset_token = PasswordResetToken.objects.create(user=user)

            reset_link = (
                f"http://127.0.0.1:8000/reset-password/{reset_token.token}/"
            )

            send_mail(
                "BiteMenu Password Reset",
                f"Click this link to reset your password:\n\n{reset_link}",
                settings.EMAIL_HOST_USER,
                [user.email],
                fail_silently=False,
            )

        messages.success(
            request,
            "If the email exists, a reset link has been sent."
        )

        return redirect("index")

    return render(request, "forgot_password.html")

def reset_password(request, token):

    reset_token = PasswordResetToken.objects.filter(
        token=token
    ).first()

    if not reset_token:
        messages.error(request, "Invalid reset link")
        return redirect('index')

    if request.method == "POST":

        new_password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")

        if new_password != confirm_password:
            messages.error(request, "Passwords do not match")
            return redirect(request.path)

        hashed_pw = bcrypt.hashpw(
            new_password.encode(),
            bcrypt.gensalt()
        ).decode()

        user = reset_token.user
        user.password = hashed_pw
        user.save()

        reset_token.delete()

        messages.success(
            request,
            "Password updated successfully"
        )

        return redirect('index')

    return render(
        request,
        "reset_password.html",
        {"token": token}
    )

def login(request):
    if request.method == "POST":
        email = request.POST.get('email', '').strip()

        user = User.objects.filter(email__iexact=email).first()
        print("LOGIN EMAIL:", email)
        print("USER FOUND:", user)
        if not user:
            messages.error(request, "Invalid email or password")
            return redirect('index')
        print(
                bcrypt.checkpw(
                    request.POST['password'].encode(),
                    user.password.encode()
                )
            )
        if not bcrypt.checkpw(request.POST['password'].encode(), user.password.encode()):
            messages.error(request, "Invalid email or password")
            return redirect('index')

        request.session['user_id'] = user.id
        request.session['role'] = user.role.strip()

        if user.role == 'admin':
            return redirect('admin_dashboard')
        return redirect('owner_dashboard')

    return redirect('index')



@login_required
def logout(request):

#   if customer mode
    if request.session.get('customer_mode'):
        request.session.pop('customer_mode', None)
        request.session.pop('table_number', None)
        return redirect('restaurants')

    # normal logout
    request.session.pop('user_id', None)
    request.session.pop('role', None)
    request.session.pop('admin_id', None)

    return redirect('index')


@login_required
@owner_required
def open_customer_mode(request):
    user = User.objects.get(id=request.session['user_id'])
    restaurant = Restaurant.objects.filter(owner=user).first()
    return redirect(f"/menu/{restaurant.id}?mode=customer")


@login_required
@owner_required
def exit_customer_mode(request):
    if request.method == "POST":
        pin = request.POST.get('pin')

        if pin != "1234":
            messages.error(request, "Wrong PIN")
            return redirect(request.META.get('HTTP_REFERER', '/'))

        request.session.pop('customer_mode', None)
        return redirect('owner_dashboard')

    return redirect('restaurants')


@login_required
@admin_required
def admin_dashboard(request):
    restaurants = Restaurant.objects.all()
    return render(request, 'admin_dashboard.html', {'restaurants': restaurants})


@login_required
@admin_required
def login_as_owner(request, restaurant_id):
    request.session['admin_id'] = request.session['user_id']

    restaurant = Restaurant.objects.get(id=restaurant_id)
    owner = restaurant.owner

    request.session['user_id'] = owner.id
    request.session['role'] = owner.role

    return redirect('owner_dashboard')


def back_to_admin(request):
    if 'admin_id' not in request.session:
        return redirect('index')

    request.session['user_id'] = request.session['admin_id']
    request.session['role'] = 'admin'
    del request.session['admin_id']

    return redirect('admin_dashboard')


@login_required
@admin_required
def create_restaurant(request):
    if request.method == "POST":
        name = request.POST.get('name')
        description = request.POST.get('description')

        owner_name = request.POST.get('owner_name')
        owner_email = request.POST.get('owner_email')
        owner_password = request.POST.get('owner_password')

        errors = {}

        if not name:
            errors['name'] = "Restaurant name is required"
        if not owner_name:
            errors['owner_name'] = "Owner name is required"
        if not owner_email:
            errors['owner_email'] = "Owner email is required"
        if not owner_password or len(owner_password) < 6:
            errors['owner_password'] = "Password must be at least 6 characters"
        if User.objects.filter(email=owner_email).first():
            errors['email'] = "Email already exists"

        if errors:
            for value in errors.values():
                messages.error(request, value)
            return redirect('create_restaurant')

        hashed_pw = bcrypt.hashpw(
            owner_password.encode(), bcrypt.gensalt()
        ).decode()

        owner = User.objects.create(
            first_name=owner_name,
            last_name="Owner",
            email=owner_email,
            password=hashed_pw,
            role="owner"
        )

        Restaurant.objects.create(
            name=name,
            description=description,
            owner=owner,
            public_token=str(uuid.uuid4())
        )

        messages.success(request, "Restaurant created successfully")
        return redirect('admin_dashboard')

    return render(request, 'create_restaurant.html', {
        'owners': User.objects.filter(role='owner')
    })


@login_required
@admin_required
def delete_restaurant(request, restaurant_id):
    restaurant = Restaurant.objects.get(id=restaurant_id)
    owner = restaurant.owner
    restaurant.delete()
    owner.delete()
    return redirect('admin_dashboard')



@login_required
@owner_required
def owner_dashboard(request):
    print("SESSION:", dict(request.session))
    request.session.pop('customer_mode', None)

    user = User.objects.get(id=request.session['user_id'])
    restaurant = Restaurant.objects.filter(owner=user).first()

    menu_items = MenuItem.objects.filter(restaurant=restaurant).prefetch_related(
        'option_groups__options'
    )

    active_orders = Order.objects.filter(
        restaurant=restaurant,
        status__in=ACTIVE_ORDER_STATUSES
    ).select_related('menu_item').prefetch_related('selected_options').order_by(
        'table_number',
        'customer_session',
        'created_at'
    )

    # session â†’ Customer A / B / C _ Not implemneted yed
    session_map = {}

    for order in active_orders:
        session = order.customer_session

        if session not in session_map:
            session_map[session] = string.ascii_uppercase[len(session_map)]

        order.customer_label = session_map[session]

    orders_by_table = _build_orders_by_table(active_orders)

    order_history = Order.objects.filter(
        restaurant=restaurant,
        status__in=['completed', 'cancelled']
    ).select_related('menu_item').prefetch_related('selected_options').order_by('-created_at')

    context = {
        'restaurant': restaurant,
        'menu_items': menu_items,
        'orders': active_orders,
        'orders_by_table': orders_by_table,
        'history': order_history
    }

    return render(request, 'owner_dashboard.html', context)


@login_required
@owner_required
def add_item(request, restaurant_id):
    if request.session.get('customer_mode'):
        return redirect('restaurants')

    user = User.objects.get(id=request.session['user_id'])
    restaurant = Restaurant.objects.get(id=restaurant_id)

    if restaurant.owner != user:
        return redirect('index')

    return render(request, 'add_item.html', {'restaurant': restaurant})

@login_required
@owner_required
def create_menu_item(request, restaurant_id):

    if request.method == "POST":

        if request.session.get('customer_mode'):
            return redirect('restaurants')

        user = User.objects.get(id=request.session['user_id'])
        restaurant = Restaurant.objects.get(id=restaurant_id)

        if restaurant.owner != user:
            return redirect('index')

        errors = MenuItem.objects.item_validator(request.POST)

        if errors:
            for value in errors.values():
                messages.error(request, value)
            return redirect(f'/add_item/{restaurant_id}')

        quantity = int(request.POST['quantity'])

        option_groups, option_errors = _parse_menu_option_groups(request.POST)

        if option_errors:
            for value in option_errors:
                messages.error(request, value)
            return redirect(f'/add_item/{restaurant_id}')

        item = MenuItem.objects.create(
            name=request.POST['name'],
            price=request.POST['price'],
            quantity=quantity,
            status='sold_out' if quantity == 0 else 'available',
            restaurant=restaurant
        )

        for group_data in option_groups:
            group = MenuOptionGroup.objects.create(
                item=item,
                name=group_data['name'],
                is_required=group_data['is_required'],
                allow_multiple=group_data['allow_multiple']
            )

            for option_data in group_data['options']:
                group.options.create(
                    name=option_data['name'],
                    price_delta=option_data['price_delta']
                )

        messages.success(request, f"{request.POST['name']} was added to the menu")

    return redirect('owner_dashboard')


@login_required
@owner_required
def edit_item(request, item_id):
    item = MenuItem.objects.get(id=item_id)
    return render(request, 'edit_item.html', {'item': item})


@login_required
@owner_required
def update_item(request, item_id):
    if request.method == "POST":
        item = MenuItem.objects.get(id=item_id)
        user = User.objects.get(id=request.session['user_id'])

        if item.restaurant.owner != user:
            return redirect('owner_dashboard')

        item.name = request.POST.get('name')
        item.price = request.POST.get('price')
        item.quantity = request.POST.get('quantity')
        item.status = 'sold_out' if int(item.quantity) == 0 else 'available'
        item.save()

        return redirect('owner_dashboard')


def restaurants(request):


    if 'user_id' in request.session and request.session.get('role') == 'owner':
        user = User.objects.get(id=request.session['user_id'])
        restaurant = Restaurant.objects.filter(owner=user)
    elif 'user_id' in request.session and request.session.get('role') == 'admin':
        restaurant = Restaurant.objects.all()
    else:
        restaurant = Restaurant.objects.all()

    return render(request, 'restaurants.html', {'restaurants': restaurant})

def menu(request, restaurant_id):
    if request.GET.get('mode') == 'customer':
        request.session['customer_mode'] = True
    else:
        # Exit customer mode when rendering the normal owner/admin view.
        request.session.pop('customer_mode', None)

    restaurant = Restaurant.objects.get(id=restaurant_id)

    if 'user_id' in request.session and request.session.get('role') == 'owner':
        user = User.objects.get(id=request.session['user_id'])
        if restaurant.owner != user:
            return redirect('owner_dashboard')

    request.session['voice_restaurant_id'] = restaurant.id
    items = MenuItem.objects.filter(restaurant_id=restaurant_id).prefetch_related(
        'option_groups__options'
    )

    return render(request, 'menu.html', {
        'restaurant': restaurant,
        'items': items,
        'available_items_count': items.filter(status='available').count(),
    })


@login_required
@owner_required
def owner_menu_redirect(request):
    restaurant = Restaurant.objects.filter(owner_id=request.session['user_id']).first()

    if not restaurant:
        return redirect('owner_dashboard')

    return redirect(f"/menu/{restaurant.id}")


def my_orders(request):
    customer_session = request.session.get('customer_id')

    if not customer_session:
        orders = Order.objects.none()
    else:
        orders = Order.objects.filter(
            customer_session=customer_session,
            status__in=ACTIVE_ORDER_STATUSES
        ).select_related('menu_item', 'restaurant').prefetch_related(
            'selected_options'
        ).order_by('-created_at')


    return render(request, 'my_orders.html', {'orders': orders})



def customer_menu(request, token):

    restaurant = Restaurant.objects.filter(public_token=token).first()

    if not restaurant:
        return HttpResponse("Invalid link")

    request.session['customer_mode'] = True

    previous_table_number = request.session.get('table_number')
    table_number = request.GET.get('table') or previous_table_number

    if not table_number:
        return HttpResponse("Table number is required")

    #  SESSION LOGIC (FINAL FIX)
    current_customer_session = request.session.get('customer_id')
    is_new = request.GET.get('new')

    #  NEW CUSTOMER
    if is_new and not request.session.get('new_used'):
        customer_session = str(uuid.uuid4())

        request.session['new_used'] = True
        request.session['customer_id'] = customer_session
        request.session['table_number'] = table_number


        return redirect(f"/menu/{token}?table={table_number}")

    #  SAME CUSTOMER
    elif current_customer_session:
        customer_session = current_customer_session

    #  FIRST TIME
    else:
        customer_session = str(uuid.uuid4())

    #  SAVE SESSION
    request.session['table_number'] = table_number
    request.session['customer_id'] = customer_session
    request.session['voice_restaurant_id'] = restaurant.id

    # DATA
    items = MenuItem.objects.filter(restaurant=restaurant).prefetch_related(
        'option_groups__options'
    )


    orders = Order.objects.filter(
        restaurant=restaurant,
        customer_session=customer_session,
        table_number=table_number
    ).select_related('menu_item').prefetch_related('selected_options').order_by('-created_at')

    return render(request, 'menu.html', {
        'restaurant': restaurant,
        'items': items,
        'orders': orders,
        'available_items_count': items.filter(status='available').count(),
    })

def create_order(request):
    if request.method == "POST":

        errors = Order.objects.order_validator(request.POST)

        restaurant_id = request.POST.get('restaurant_id')

        item = MenuItem.objects.prefetch_related('option_groups__options').filter(
            id=request.POST['item_id'],
            restaurant_id=restaurant_id
        ).first()

        # ITEM NOT FOUND
        if not item:
            messages.error(request, "Item not found")
            return redirect('restaurants')

        table_number = request.session.get('table_number')
        customer_session = request.session.get('customer_id')

        if not table_number:
            messages.error(request, "Please enter your table number first")
            return redirect(f'/menu/{item.restaurant.public_token}/')

        if not customer_session:
            customer_session = str(uuid.uuid4())
            request.session['customer_id'] = customer_session

        # VALIDATE QUANTITY
        try:
            quantity = int(request.POST.get('quantity', 0))
        except:
            messages.error(request, "Invalid quantity")
            return redirect(f'/menu/{item.restaurant.public_token}/?table={table_number}')

        if quantity <= 0:
            messages.error(request, "Invalid quantity")
            return redirect(f'/menu/{item.restaurant.public_token}/?table={table_number}')

        selected_options, option_errors = _get_selected_order_options(item, request.POST)

        if option_errors:
            items = MenuItem.objects.filter(restaurant=item.restaurant).prefetch_related(
                'option_groups__options'
            )

            return render(request, "menu.html", {
                "restaurant": item.restaurant,
                "items": items,
                "errors": option_errors
            })

        if quantity > item.quantity:

            items = MenuItem.objects.filter(restaurant=item.restaurant).prefetch_related(
                'option_groups__options'
            )

            context = {
                "restaurant": item.restaurant,
                "items": items,
                "errors": {
                    item.id: "Sold out / Not enough quantity"
                }
            }

            return render(request, "menu.html", context)

        selected_options_total = sum(
            (option.price_delta for option in selected_options),
            Decimal('0')
        )
        total_price = (item.price + selected_options_total) * quantity

        # CREATE ORDER
        order = Order.objects.create(
            restaurant=item.restaurant,
            menu_item=item,
            quantity=quantity,
            total_price=total_price,
            note=request.POST.get('note', ''),
            status="pending",
            customer_session=customer_session,
            table_number=table_number
        )

        for option in selected_options:
            OrderOption.objects.create(
                order=order,
                option_group_name=option.group.name,
                option_name=option.name,
                option_price=option.price_delta
            )

        messages.success(request, "Order placed successfully")

        # update quantity
        item.quantity -= quantity
        if item.quantity == 0:
            item.status = 'sold_out'
        item.save()

        return redirect(f'/menu/{item.restaurant.public_token}/?table={table_number}')

    return redirect('restaurants')

def set_table(request):
    if request.method == "POST":
        table_number = request.POST.get('table_number')
        if table_number:
            request.session['table_number'] = table_number

    token = request.POST.get('token')
    if token:
        return redirect(f'/menu/{token}/?table={request.session.get("table_number")}')
    return redirect('restaurants')


def cancel_order(request, order_id):
    order = Order.objects.get(id=order_id)

    item = order.menu_item
    item.quantity += order.quantity

    if item.quantity > 0:
        item.status = 'available'

    item.save()

    order.status = 'cancelled'
    order.save()

    return redirect('restaurants')

@login_required
@owner_required
def delete_item(request, item_id):

    item = MenuItem.objects.get(id=item_id)
    user = User.objects.get(id=request.session['user_id'])

    if item.restaurant.owner != user:
        return redirect('owner_dashboard')

    item.delete()

    return redirect('owner_dashboard')

@login_required
@owner_required
def update_order(request, order_id):
    if request.method == "POST":
        if request.session.get('customer_mode'):
            return redirect('restaurants')

        order = Order.objects.get(id=order_id)
        user = User.objects.get(id=request.session['user_id'])

        if order.restaurant.owner != user:
            return redirect('index')

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


@login_required
@owner_required
def owner_cancel_order(request, order_id):
    order = Order.objects.get(id=order_id)
    user = User.objects.get(id=request.session['user_id'])

    if order.restaurant.owner != user:
        return redirect('index')

    item = order.menu_item
    item.quantity += order.quantity
    item.status = 'available'
    item.save()

    order.status = 'cancelled'
    order.save()

    return redirect('owner_dashboard')


@login_required
@owner_required
def update_restaurant_note(request):
    user = User.objects.get(id=request.session['user_id'])
    restaurant = Restaurant.objects.filter(owner=user).first()
    restaurant.note = request.POST['note']
    restaurant.save()
    return redirect('owner_dashboard')


@login_required
@owner_required
def delete_order(request, order_id):
    if request.method == "POST":
        order = Order.objects.get(id=order_id)
        user = User.objects.get(id=request.session['user_id'])

        if order.restaurant.owner != user:
            return JsonResponse({'success': False})

        order.delete()
        return JsonResponse({'success': True})

    return JsonResponse({'success': False})

def _read_json_body(request):
    # Voice JS sends JSON, so keep this parser separate from normal form orders.
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _voice_response(request, message, status=200):
    # Store every spoken reply so the customer can say "عيد" or "كرر".
    request.session["last_message"] = message
    return JsonResponse({"message": message}, status=status)


def _reset_voice_invalid_attempts(request):
    request.session["voice_invalid_attempts"] = 0


def _bump_voice_invalid_attempts(request):
    attempts = request.session.get("voice_invalid_attempts", 0) + 1
    request.session["voice_invalid_attempts"] = attempts
    return attempts


def _clear_voice_state(request, next_state="awaiting_item"):
    for key in ["item_id", "size", "quantity", "candidates", "voice_invalid_attempts"]:
        request.session.pop(key, None)

    request.session["state"] = next_state


def _selected_size_option(item, size_text):
    normalized_size = normalize(size_text)

    for group in item.option_groups.all():
        for option in group.options.all():
            normalized_option = normalize(option.name)

            if normalized_size in normalized_option or normalized_option in normalized_size:
                return option

    return None


def _create_voice_order_from_session(request, note=""):
    item_id = request.session.get("item_id")
    quantity = request.session.get("quantity")
    size_text = request.session.get("size")

    if not item_id or not quantity:
        return None, "خلينا نرجع من أول. شو بتحب تطلب؟"

    item = MenuItem.objects.prefetch_related("option_groups__options").filter(id=item_id).first()

    if not item or item.status != "available":
        return None, "هاد الصنف مش متوفر هلا. شو بتحب تطلب بدل عنه؟"

    if quantity > item.quantity:
        return None, f"المتوفر من {item.name} بس {number_to_arabic(item.quantity)}. {VOICE['ASK_QUANTITY']}"

    selected_options = []

    if size_text:
        selected_option = _selected_size_option(item, size_text)

        if not selected_option:
            return None, f"ما لقيت هالحجم لـ {item.name}. {VOICE['ASK_SIZE']}"

        selected_options.append(selected_option)

    selected_options_total = sum(
        (option.price_delta for option in selected_options),
        Decimal('0')
    )
    total_price = (item.price + selected_options_total) * quantity

    order = Order.objects.create(
        restaurant=item.restaurant,
        menu_item=item,
        quantity=quantity,
        total_price=total_price,
        status="pending",
        note=note or "",
        customer_session=request.session.get("customer_id"),
        table_number=request.session.get("table_number"),
    )

    for option in selected_options:
        OrderOption.objects.create(
            order=order,
            option_group_name=option.group.name,
            option_name=option.name,
            option_price=option.price_delta
        )

    item.quantity -= quantity
    item.status = 'sold_out' if item.quantity <= 0 else 'available'
    item.save()

    return order, None


def _voice_available_items_text(limit=3):
    items = list(MenuItem.objects.filter(status="available")[:limit])

    if not items:
        return ""

    return "، ".join(item.name for item in items)


def _voice_requested_item_label(text):
    normalized_text = normalize(text)
    if not normalized_text:
        return ""

    tokens = normalized_text.split()
    filtered_tokens = [
        token for token in tokens
        if token not in {
            "صغير", "وسط", "متوسط", "كبير",
            "واحد", "واحدة", "اثنين", "اتنين", "تنين",
            "ثلاثة", "اربعة", "خمسة",
        }
    ]

    return " ".join(filtered_tokens[:3]).strip() or normalized_text


def _voice_menu_items(request, status="available"):
    restaurant_id = request.session.get("voice_restaurant_id")
    items = MenuItem.objects.all()

    if restaurant_id:
        items = items.filter(restaurant_id=restaurant_id)

    if status:
        items = items.filter(status=status)

    return items


def _voice_available_items_text_for_request(request, limit=3):
    items = list(_voice_menu_items(request, status="available")[:limit])

    if not items:
        return ""

    return "، ".join(item.name for item in items)


def _voice_item_aliases(item):
    aliases = {normalize(item.name)}

    raw_keywords = item.voice_keywords or ""
    for keyword in raw_keywords.split(","):
        normalized_keyword = normalize(keyword)
        if normalized_keyword:
            aliases.add(normalized_keyword)

    expanded_aliases = set()
    for alias in aliases:
        expanded_aliases.add(alias)
        expanded_aliases.update(part for part in alias.split() if part)

    return expanded_aliases


def _voice_match_score(text, item):
    normalized_text = normalize(text)
    words = normalized_text.split()
    aliases = _voice_item_aliases(item)
    score = 0

    for alias in aliases:
        if not alias:
            continue
        if alias == normalized_text:
            score += 5
        elif alias in normalized_text or normalized_text in alias:
            score += 3

    for word in words:
        for alias in aliases:
            if word and (word == alias or word in alias or alias in word):
                score += 1

    return score


def _matches_any_phrase(text, phrases):
    # Normalize both sides so voice commands are less sensitive to spacing and punctuation.
    normalized_text = normalize(text)
    return any(normalize(phrase) in normalized_text for phrase in phrases)


def _item_has_voice_specs(item):
    # Voice flow only: specs are menu option groups with at least one option.
    return item.option_groups.filter(options__isnull=False).distinct().exists()


def _continue_after_voice_item_found(request, item, parsed_size=None):
    # After item matching, ask specs only when the menu item actually has specs.
    request.session["item_id"] = item.id
    item_found = VOICE["ITEM_FOUND"].format(item=item.name)

    if _item_has_voice_specs(item):
        if parsed_size:
            request.session["size"] = parsed_size
            request.session["state"] = "awaiting_quantity"
            return _voice_response(request, f"{item_found} {parsed_size}. {VOICE['ASK_QUANTITY']}")

        request.session["state"] = "awaiting_size"
        return _voice_response(request, f"{item_found}. {VOICE['ASK_SIZE']}")

    request.session["state"] = "awaiting_quantity"
    return _voice_response(request, f"{item_found}. {VOICE['ASK_QUANTITY']}")

def find_similar_items(text):
    text = normalize(text)
    items = MenuItem.objects.all()
    scored = []

    for item in items:
        score = _voice_match_score(text, item)

        if score > 0:
            scored.append((score, item))

    # ترتيب حسب التشابه
    scored.sort(reverse=True, key=lambda x: x[0])

    # نرجع أفضل 3
    return [item for score, item in scored[:3]]


def find_best_match(text):
    text = normalize(text)
    items = MenuItem.objects.all()
    scored = []

    for item in items:
        score = _voice_match_score(text, item)

        if score > 0:
            scored.append((score, item))

    if not scored:
        partial_matches = []
        for item in items:
            if any(alias in text or text in alias for alias in _voice_item_aliases(item) if alias):
                partial_matches.append(item)

        if partial_matches:
            return None, partial_matches[:3]

        return None, []

   
    scored.sort(reverse=True, key=lambda x: x[0])

    best_score = scored[0][0]

    best_items = [item for score, item in scored if score == best_score]


    if len(best_items) == 1:
        return best_items[0], []


    return None, best_items[:3]


def words_to_number(text):
    mapping = {
        "واحد": 1,
        "واحدة": 1,

        "اثنين": 2,
        "اتنين": 2,
        "تنين": 2,

        "ثلاثة": 3,
        "تلاتة" : 3,
        "اربعة": 4,

        "خمسة": 5,
        "ستة": 6,
        "سبعة": 7,
        "ثمانية": 8,
        "تمانية": 8,
        "احداش" : 11,
        "اثناش" : 12,
        "اتْناش" : 12,
        "ثلاثطاش" : 13,
        "تلاتّاش" : 13,
        "أربعْتاش" : 14,
        "خَمَسْطاش" : 15,
        "ستّاش": 16,
        "سبعتاش" : 17,
        "ثمنتاش": 18,
        "تمنطاش" : 18,
        "تسعطاش": 19,
        "عشرين" : 20,
        
    }

    for word, number in mapping.items():
        if word in text:
            return number

    return None


def is_negative(text):
    negatives = [
        "لا",
        "ما بدي",
        "مش",
        "بدون",
        "خلص",
        "ما في",
        "لا شكرا",
        "بالعكس",
    ]

    return any(word in text for word in negatives)

def parse_order_text(text):
    text = normalize(text)

    result = {
        "item": None,
        "size": None,
        "quantity": 1,
        "extras": []
    }


    if "صغير" in text:
        result["size"] = "صغير"
    elif "وسط" in text:
        result["size"] = "وسط"
    elif "كبير" in text:
        result["size"] = "كبير"

    for word, num in {
        "واحد":1, "اثنين":2, "ثلاثة":3, "اربعة":4
    }.items():
        if word in text:
            result["quantity"] = num


    items = MenuItem.objects.filter(status="available")

    for item in items:
        if _voice_match_score(text, item) > 0:
            result["item"] = item
            break


    if "كولا" in text:
        result["extras"].append("كولا")
    if "ببسي" in text:
        result["extras"].append("ببسي")
    if "بطاطا" in text:
        result["extras"].append("بطاطا")
    return result


def voice_order(request):
    if request.method != "POST":
        return _voice_response(request, VOICE["INVALID"], status=405)

    data = _read_json_body(request)
    text = normalize(data.get("text") or request.POST.get("text", ""))

    if not text:
        return _voice_response(request, VOICE["INVALID"])

    if any(word in text for word in ["نور", "noor", "nor"]):
        reply = ai_chat_reply(text)
        return _voice_response(request, reply)

    state = request.session.get("state", "awaiting_item")

    if _matches_any_phrase(text, RESET_ORDER_PHRASES):
        _clear_voice_state(request)
        return _voice_response(request, "تمام، رجعنا من أول. شو بتحب تطلب؟")

    # Greeting
    if _matches_any_phrase(text, GREETING_PHRASES):
        return _voice_response(request, pick("GREETING"))


    if _matches_any_phrase(text, REPEAT_PHRASES):
        last = request.session.get("last_message")

        if last:
            return _voice_response(request, last)

        return _voice_response(request, VOICE["INVALID"])

    
    # Item suggestion
    if _matches_any_phrase(text, SHOW_ITEMS_PHRASES):
        items = MenuItem.objects.filter(status="available")[:3]

        if items:
            names = [item.name for item in items]
            names_text = "، ".join(names)

            message = f"ممكن تجرب {names_text}. إذا حاب، بقدر أوجهك على القائمة تختار اللي بدك إياه وترجعلي"
            return _voice_response(request, message)

        return _voice_response(request, "حاليًا ما في أصناف متوفرة على المنيو")

    # Thanks handling
    if _matches_any_phrase(text, THANKS_PHRASES):
        return _voice_response(request, pick("THANKS"))
    
    
    # Handle candidate selection
    if "candidates" in request.session:
        candidates_ids = request.session.get("candidates")

        if candidates_ids:
            options_map = {
                "الأولى": 0, "اول": 0, "واحد": 0,
                "الثانية": 1, "ثاني": 1, "اثنين": 1,
                "الثالثة": 2, "ثالث": 2, "ثلاثة": 2,
            }

            for word, index in options_map.items():
                if word in text and index < len(candidates_ids):
                    item = MenuItem.objects.get(id=candidates_ids[index])

                    request.session.pop("candidates", None)
                    return _continue_after_voice_item_found(request, item)

            # إذا قال "هاي"
            if "هاي" in text or "هذا" in text:
                item = MenuItem.objects.get(id=candidates_ids[0])

                request.session.pop("candidates", None)
                return _continue_after_voice_item_found(request, item)

            item, _ = find_best_match(text)
            if item:
                request.session.pop("candidates", None)
                return _continue_after_voice_item_found(request, item)

            return _voice_response(request, "اختار الأولى أو الثانية أو الثالثة، أو احكي اسم الصنف من جديد")
            
    # Handle "add more"
    if request.session.get("state") == "done":

        if _matches_any_phrase(text, YES_MORE_PHRASES):
            request.session["state"] = "awaiting_item"
            return _voice_response(request, VOICE["ASK_ITEM"])

        # لا → إنهاء
        if _matches_any_phrase(text, NO_MORE_PHRASES):
            return _voice_response(request, pick("THANKS"))

        # If the customer says a new item after a finished order, search items again.
        request.session["state"] = "awaiting_item"
        state = "awaiting_item"

    # Main flow
    if state == "awaiting_item":
        parsed = parse_order_text(text)

    if parsed["item"]:
        _reset_voice_invalid_attempts(request)
        item = parsed["item"]

        if item.status != "available":
            _clear_voice_state(request)

            return _voice_response(
                request,
                f"للأسف {item.name} مخلص حالياً. شو بتحب تطلب بدل عنه؟"
            )

        if parsed["extras"]:
            message = f"تمام {item.name} مع {' و '.join(parsed['extras'])}"
            request.session["item_id"] = item.id
            request.session["state"] = "awaiting_quantity"

            return _voice_response(
                request,
                f"{message}. {VOICE['ASK_QUANTITY']}"
            )

        return _continue_after_voice_item_found(
            request,
            item,
            parsed["size"]
        )

        # ❌ fallback
        item, candidates = find_best_match(text)

        if not item:
            if candidates:
                request.session["candidates"] = [i.id for i in candidates]
                _reset_voice_invalid_attempts(request)

                names = [i.name for i in candidates]
                names_text = "، ".join(names)

                return _voice_response(request, f"قصدك {names_text}؟")

            attempts = _bump_voice_invalid_attempts(request)
            suggestions = _voice_available_items_text()
            available_count = MenuItem.objects.filter(status="available").count()
            requested_label = _voice_requested_item_label(text)

            if available_count == 0:
                return _voice_response(
                    request,
                    "حاليًا ما في أصناف متوفرة على المنيو"
                )

            if available_count == 1 and suggestions:
                return _voice_response(
                    request,
                    f"ما عنا {requested_label or 'هاد الصنف'}. المتوفر هلا بس {suggestions}. احكي {suggestions} إذا بدك تطلبه"
                )

            if attempts >= 2 and suggestions:
                _reset_voice_invalid_attempts(request)
                return _voice_response(
                    request,
                    f"ما عنا {requested_label or 'هاد الصنف'}. المتوفر هلا {suggestions}. أو احكي شو في"
                )

            if suggestions:
                return _voice_response(
                    request,
                    f"ما عنا {requested_label or 'هاد الصنف'}. احكي صنف موجود مثل {suggestions}"
                )

            return _voice_response(request, VOICE["ASK_ITEM"])

        return _continue_after_voice_item_found(request, item)

    if state == "awaiting_size":
        # Specification answer: currently supports the existing small/medium/large flow.
        if _matches_any_phrase(text, CHANGE_ITEM_PHRASES):
            _clear_voice_state(request)
            return _voice_response(request, "تمام، غيرنا الصنف. شو بتحب تطلب؟")

        parsed = parse_order_text(text)
        if parsed["item"]:
            request.session.pop("size", None)
            request.session.pop("quantity", None)
            return _continue_after_voice_item_found(request, parsed["item"], parsed["size"])

        selected_size = None
        size_aliases = {
            "صغير": ["صغير", "سمول"],
            "وسط": ["وسط", "متوسط", "ميديم"],
            "كبير": ["كبير", "لارج"],
        }

        for canonical_size, aliases in size_aliases.items():
            if any(alias in text for alias in aliases):
                selected_size = canonical_size
                break

        if not selected_size:
            attempts = _bump_voice_invalid_attempts(request)
            if attempts >= 2:
                _clear_voice_state(request)
                return _voice_response(request, "خلينا نرجع للصنف من أول. احكي اسم الصنف اللي بدك إياه")

            return _voice_response(request, "احكي الحجم: صغير، وسط، أو كبير. وإذا بدك تغيّر الصنف احكي اسمه")

        request.session["size"] = selected_size
        request.session["state"] = "awaiting_quantity"
        _reset_voice_invalid_attempts(request)

        return _voice_response(request, f"تمام {selected_size}. {VOICE['ASK_QUANTITY']}")

    if state == "awaiting_quantity":
        # Quantity answer: continue toward the existing note and confirmation steps.
        if _matches_any_phrase(text, CHANGE_ITEM_PHRASES):
            _clear_voice_state(request)
            return _voice_response(request, "تمام، غيرنا الصنف. شو بتحب تطلب؟")

        if _matches_any_phrase(text, CHANGE_SIZE_PHRASES):
            request.session["state"] = "awaiting_size"
            request.session.pop("size", None)
            _reset_voice_invalid_attempts(request)
            return _voice_response(request, VOICE["ASK_SIZE"])

        parsed = parse_order_text(text)
        if parsed["item"]:
            request.session.pop("size", None)
            request.session.pop("quantity", None)
            return _continue_after_voice_item_found(request, parsed["item"], parsed["size"])

        try:
            quantity = int(text)
        except ValueError:
            quantity = words_to_number(text)

        if not quantity:
            attempts = _bump_voice_invalid_attempts(request)
            if attempts >= 2:
                _clear_voice_state(request)
                return _voice_response(request, "خلينا نرجع من أول. احكي اسم الصنف وبعدين الكمية")

            return _voice_response(request, "احكي الكمية برقم أو كلمة، مثل واحد أو اثنين")

        request.session["quantity"] = quantity
        request.session["state"] = "awaiting_note"
        _reset_voice_invalid_attempts(request)

        return _voice_response(request, VOICE["ASK_NOTE"])

    if state == "awaiting_note":
        if _matches_any_phrase(text, CHANGE_ITEM_PHRASES):
            _clear_voice_state(request)
            return _voice_response(request, "تمام، غيرنا الصنف. شو بتحب تطلب؟")

        if _matches_any_phrase(text, CHANGE_SIZE_PHRASES):
            request.session["state"] = "awaiting_size"
            request.session.pop("size", None)
            request.session.pop("quantity", None)
            _reset_voice_invalid_attempts(request)
            return _voice_response(request, VOICE["ASK_SIZE"])

        if _matches_any_phrase(text, CHANGE_QUANTITY_PHRASES):
            request.session["state"] = "awaiting_quantity"
            request.session.pop("quantity", None)
            _reset_voice_invalid_attempts(request)
            return _voice_response(request, VOICE["ASK_QUANTITY"])

        note = "" if is_negative(text) else text
        order, error_message = _create_voice_order_from_session(request, note)

        if error_message:
            if VOICE["ASK_QUANTITY"] in error_message:
                request.session["state"] = "awaiting_quantity"
            elif VOICE["ASK_SIZE"] in error_message:
                request.session["state"] = "awaiting_size"
            else:
                _clear_voice_state(request)

            return _voice_response(request, error_message)

        _clear_voice_state(request, next_state="done")
        request.session["state"] = "done"

        message = f"{VOICE['CONFIRM']}. طلبك صار جاهز بالنظام. بدك تضيف اشي تاني؟"
        return _voice_response(request, message)

    # 🔴 fallback
    return _voice_response(request, VOICE["INVALID"])

TASHKEEL_MAP = {
    "نورتنا": "نَوَّرْتَنا",
    "اهلا": "أَهْلًا",
    "وسهلا": "وَسَهْلًا",
    "شو": "شُو",
    "بدك": "بَدَّك",
    "تحب": "تُحِبّ",
    "تطلب": "تَطْلُب",
    "تمام": "تَمام",
}

def apply_tashkeel(text):
    words = text.split()
    new_words = []

    for word in words:
        clean_word = word.strip("،.؟!")

        if clean_word in TASHKEEL_MAP:
            word = word.replace(clean_word, TASHKEEL_MAP[clean_word])

        new_words.append(word)

    return " ".join(new_words)


@lru_cache(maxsize=256)
def ai_tashkeel(text):
    # Cache repeated short waiter prompts so they do not keep waiting on Groq.
    api_key = os.environ.get("GROQ_API_KEY")

    if not api_key:
        return text  # fallback

    prompt = f"""
        - Use a neutral falling tone (not a questioning tone)
        - Sentences should sound like statements, not questions
        - Only use questioning tone if the sentence actually contains a question
        - Speak at a calm, slightly slower pace
        - Do NOT speak fast
        - Keep smooth natural flow

        text:
        {text}

        return only text
        """

    try:
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3
            },
            timeout=GROQ_TTS_TIMEOUT_SECONDS
        )

        data = res.json()
        return data["choices"][0]["message"]["content"].strip()

    except:
        return text  # fallback إذا صار error
    
    
    
    
def ai_chat_reply(text):
    import requests
    import os

    api_key = os.environ.get("GROQ_API_KEY")

    if not api_key:
        return "مش سامعك منيح، احكي مرة ثانية"

    prompt = f"""
You are a young Palestinian female named Noor.

You are:
- friendly
- soft
- natural
- slightly playful

Rules:
- reply in Palestinian Arabic dialect
- keep reply short (max 1 sentence)
- sound like a real human, not AI
- NEVER use formal Arabic

User: {text}
Noor:
"""

    try:
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7
            },
            timeout=GROQ_TTS_TIMEOUT_SECONDS
        )

        data = res.json()
        return data["choices"][0]["message"]["content"].strip()

    except:
        return "مش واضح، احكي مرة ثانية"


def prepare_tts_text(text):
    # TTS rhythm only: preserve punctuation so ElevenLabs can create natural pauses.
    text = (text or "").strip()
    text = re.sub(r"\.{3,}", " … ", text)
    text = text.replace(",", "،")
    text = text.replace("?", "؟")

    # Keep pauses readable without flattening the sentence.
    text = re.sub(r"\s*([،.؟!])\s*", r"\1 ", text)
    text = re.sub(r"\s*…\s*", " … ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


def tts_voice_settings():
    # Slow the delivery slightly without changing the voice id or Palestinian recognition.
    return {
        "stability": 0.8,
        "similarity_boost": 1,
        "style": 1,
        "speed": 0.88,
    }


@lru_cache(maxsize=256)
def _generate_tts_audio(text, voice_id, api_key):
    # Cache repeated ElevenLabs responses for common menu prompts.
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = json.dumps({
        "text": text,
        "model_id": "eleven_flash_v2_5",
        "voice_settings": tts_voice_settings()
    }).encode("utf-8")

    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": api_key
    }

    req = urllib.request.Request(url, data=payload, headers=headers)

    with urllib.request.urlopen(req, timeout=ELEVENLABS_TTS_TIMEOUT_SECONDS) as res:
        return res.read()


def _transcribe_audio_with_elevenlabs(audio_file, api_key):
    audio_file.seek(0)
    audio_bytes = audio_file.read()
    filename = audio_file.name or "voice.webm"
    content_type = getattr(audio_file, "content_type", None) or "audio/webm"

    last_error = None

    for _ in range(2):
        try:
            response = requests.post(
                "https://api.elevenlabs.io/v1/speech-to-text",
                headers={
                    "xi-api-key": api_key,
                },
                data={
                    "model_id": "scribe_v1",
                    "language_code": "ara",
                },
                files={
                    "file": (
                        filename,
                        audio_bytes,
                        content_type,
                    ),
                },
                timeout=ELEVENLABS_STT_TIMEOUT_SECONDS,
            )

            response.raise_for_status()
            data = response.json()
            return (data.get("text") or "").strip()
        except requests.RequestException as exc:
            last_error = exc

    raise last_error


def stt(request):
    if request.method != "POST":
        return JsonResponse({"message": "invalid request"}, status=405)

    audio_file = request.FILES.get("audio")

    if not audio_file:
        return JsonResponse({"message": "no audio"}, status=400)

    api_key = os.environ.get("ELEVENLABS_API_KEY")

    if not api_key:
        return JsonResponse({"message": "env error"}, status=500)

    try:
        text = _transcribe_audio_with_elevenlabs(audio_file, api_key)
    except requests.RequestException:
        return JsonResponse({"message": "stt error"}, status=502)

    if not text:
        return JsonResponse({"message": "empty transcript"}, status=422)

    return JsonResponse({"text": text})


def tts(request):
    if request.method != "POST":
        return JsonResponse({"message": "invalid request"}, status=405)

    try:
        data = json.loads(request.body)
    except:
        return JsonResponse({"message": "bad json"}, status=400)

    text = prepare_tts_text(data.get("text", ""))

    text = ai_tashkeel(text)
    text = prepare_tts_text(text)

    if not text:
        return JsonResponse({"message": "no text"}, status=400)

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID")

    if not api_key or not voice_id:
        return JsonResponse({"message": "env error"}, status=500)

    try:
        audio = _generate_tts_audio(text, voice_id, api_key)
    except:
        return JsonResponse({"message": "tts error"}, status=500)

    return HttpResponse(audio, content_type="audio/mpeg")

