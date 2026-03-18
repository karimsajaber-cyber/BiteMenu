from django.db import models
import re

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9.+_-]+@[a-zA-Z0-9._-]+\.[a-zA-Z]+$')



# USER MANAGER

class UserManager(models.Manager):

    def register_validator(self, postData):
        errors = {}

        if len(postData['first_name']) < 2:
            errors['first_name'] = "First name must be at least 2 characters"

        if len(postData['last_name']) < 2:
            errors['last_name'] = "Last name must be at least 2 characters"

        if not EMAIL_REGEX.match(postData['email']):
            errors['email'] = "Invalid email address"

        if User.objects.filter(email=postData['email']).exists():
            errors['email'] = "Email already exists"

        if len(postData['password']) < 8:
            errors['password'] = "Password must be at least 8 characters"

        if postData['password'] != postData['confirm_password']:
            errors['password'] = "Passwords do not match"

        return errors



# USER MODEL

class User(models.Model):

    ROLE_CHOICES = (
        ('admin', 'Admin'),
        ('owner', 'Owner'),
    )

    first_name = models.CharField(max_length=45)
    last_name = models.CharField(max_length=45)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)

    role = models.CharField(max_length=10, choices=ROLE_CHOICES)

    #  FUTURE (Social Login)
    provider = models.CharField(max_length=20, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()


# RESTAURANT MODEL

class Restaurant(models.Model):

    STATUS_CHOICES = (
        ('open', 'Open'),
        ('busy', 'Busy'),
        ('closed', 'Closed'),
        ('maintenance', 'Maintenance'),
    )

    name = models.CharField(max_length=100)
    description = models.TextField()
    average_rating = models.FloatField(null=True, blank=True)
    owner = models.ForeignKey(User, related_name="restaurants", on_delete=models.CASCADE)
    # Restaurant Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')

    # Owner → Admin communication
    note = models.TextField(null=True, blank=True)

    #  Subscription System
    subscription_active = models.BooleanField(default=True)
    subscription_end_date = models.DateTimeField(null=True, blank=True)
    subscription_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)



# MENU ITEM MANAGER

class MenuItemManager(models.Manager):

    def item_validator(self, postData):
        errors = {}

        if len(postData['name']) < 2:
            errors['name'] = "Item name must be at least 2 characters"

        if float(postData['price']) <= 0:
            errors['price'] = "Price must be greater than 0"

        if int(postData['quantity']) < 0:
            errors['quantity'] = "Quantity cannot be negative"

        return errors


# MENU ITEM MODEL

class MenuItem(models.Model):

    STATUS_CHOICES = (
        ('available', 'Available'),
        ('sold_out', 'Sold Out'),
    )

    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    quantity = models.IntegerField()

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')

    restaurant = models.ForeignKey(Restaurant, related_name="menu_items", on_delete=models.CASCADE)


    low_stock_threshold = models.IntegerField(default=5)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = MenuItemManager()



# ORDER MANAGER

class OrderManager(models.Manager):

    def order_validator(self, postData):
        errors = {}

        if int(postData['quantity']) <= 0:
            errors['quantity'] = "Quantity must be greater than zero"

        return errors



# ORDER MODEL

class Order(models.Model):

    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('preparing', 'Preparing'),
        ('ready', 'Ready'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    )

    restaurant = models.ForeignKey(Restaurant, related_name="orders", on_delete=models.CASCADE)

    menu_item = models.ForeignKey(MenuItem, related_name="orders", on_delete=models.CASCADE)

    quantity = models.IntegerField()

    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    
    note = models.TextField(null=True, blank=True)


    expected_time = models.DateTimeField(null=True, blank=True)

    #  Payment Method
    payment_method = models.CharField(
        max_length=10,
        choices=(
            ('cash', 'Cash'),
            ('visa', 'Visa'),
        ),
        default='cash'
    )

    # Customer Feedback
    rating = models.IntegerField(null=True, blank=True)
    feedback = models.TextField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    modification_request = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OrderManager()
