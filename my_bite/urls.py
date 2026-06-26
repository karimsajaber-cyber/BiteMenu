from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [

    # AUTH 
    path('', views.index, name='index'),
    #path('register', views.register, name='register'),
    path('login', views.login, name='login'),
    path('logout', views.logout, name='logout'),
    path('open_customer_mode', views.open_customer_mode),
    path('exit_customer_mode', views.exit_customer_mode),

    # ADMIN 
    path('admin_dashboard', views.admin_dashboard, name='admin_dashboard'),
    path('create_restaurant', views.create_restaurant, name='create_restaurant'),
    path('delete_restaurant/<int:restaurant_id>', views.delete_restaurant, name='delete_restaurant'),
    path('login_as_owner/<int:restaurant_id>', views.login_as_owner),
    path('back_to_admin', views.back_to_admin),

    # OWNER 
    path('owner_dashboard', views.owner_dashboard, name='owner_dashboard'),
    path('add_item/<int:restaurant_id>', views.add_item, name='add_item'),
    path('create_item/<int:restaurant_id>', views.create_menu_item, name='create_menu_item'),
    path('update_restaurant_note', views.update_restaurant_note, name='update_restaurant_note'),
    path('owner_cancel/<int:order_id>', views.owner_cancel_order, name='owner_cancel_order'),
    path('owner/menu', views.owner_menu_redirect, name='owner_menu_redirect'),

    # CUSTOMER 
    path('restaurants', views.restaurants, name='restaurants'),
    path('menu/<int:restaurant_id>', views.menu, name='menu'),
    path('cancel_order/<int:order_id>', views.cancel_order),

    # ORDER 
    path('create_order', views.create_order, name='create_order'),
    path('update_order/<int:order_id>', views.update_order, name='update_order'),
    path('my_orders', views.my_orders, name='my_orders'),
    path('delete_order/<int:order_id>', views.delete_order),

    # MENU_ITEMS
    
    path('delete_item/<int:item_id>', views.delete_item, name='delete_item'),
    path('edit_item/<int:item_id>', views.edit_item, name='edit_item'),
    path('update_item/<int:item_id>', views.update_item, name='update_item'),
    path('menu/<str:token>/', views.customer_menu, name='customer_menu'),
    path('set_table', views.set_table, name='set_table'),

    path("voice_order/", views.voice_order),
    path("stt/", views.stt),
    path("tts/", views.tts),
    
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(),
        name="password_reset"
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(),
        name="password_reset_done"
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(),
        name="password_reset_confirm"
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete"
    ),
    
    path(
    "forgot-password/",
    views.forgot_password,
    name="forgot_password"
),
    path(
    "reset-password/<uuid:token>/",
    views.reset_password,
    name="reset_password"
),
    ]
