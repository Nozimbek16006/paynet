from django.db import models


class Order(models.Model):
    order_id = models.CharField(max_length=100,)
    client_id = models.CharField(max_length=100,db_index=True,)
    customer_name = models.CharField(max_length=255,)
    balance = models.PositiveBigIntegerField(default=0,)
    amount = models.PositiveBigIntegerField()
    is_paid = models.BooleanField(default=False,)
    paid_at = models.DateTimeField(null=True,blank=True,)
    created_at = models.DateTimeField(auto_now_add=True,)
    updated_at = models.DateTimeField(auto_now=True,)

    def __str__(self):
        return f"{self.order_id} - {self.client_id}"