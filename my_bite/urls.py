from django.urls import path
from . import views

urlpatterns = [
    #  AUTH 
    path('', views.index, name='index'),
    path('register', views.register, name='register'),
    path('login', views.login, name='login'),
    path('logout', views.logout, name='logout'),

    #  ADMIN 
    path('admin_dashboard', views.admin_dashboard, name='admin_dashboard'),
    path('create_restaurant', views.create_restaurant, name='create_restaurant'),

    #  OWNER 
    path('owner_dashboard', views.owner_dashboard, name='owner_dashboard'),
    path('add_item/<int:restaurant_id>', views.add_menu_item, name='add_menu_item'),
    path('create_item/<int:restaurant_id>', views.create_menu_item, name='create_menu_item'),
    path('update_restaurant_note', views.update_restaurant_note),
    path('owner_cancel/<int:order_id>', views.owner_cancel_order),

    #  CUSTOMER 
    path('restaurants', views.restaurants, name='restaurants'),
    path('menu/<int:restaurant_id>', views.menu, name='menu'),
    path('cancel_order/<int:order_id>', views.cancel_order),
    path('delete_restaurant/<int:restaurant_id>', views.delete_restaurant, name='delete_restaurant'),  # إضافة

    #  ORDER 
    path('create_order', views.create_order, name='create_order'),
    path('update_order/<int:order_id>', views.update_order, name='update_order'),
    path('my_orders', views.my_orders, name='my_orders'),  # إضافة


]