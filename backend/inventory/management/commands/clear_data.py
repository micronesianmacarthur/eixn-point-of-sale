from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission, Group
from django.contrib.contenttypes.models import ContentType
from django.contrib.admin.models import LogEntry
from django.contrib.sessions.models import Session as DjangoSession
from django_q.models import Task, Success, Failure, Schedule, OrmQ

from inventory.models import Vendor, Category, Product, PurchaseOrder, PurchaseOrderItem, InventoryReceipt, InventoryReceiptItem, RecipeIngredient
from customers.models import Customer, CreditProfile
from sales.models import Session as SaleSession, Transaction, TransactionLineItem
from accounting.models import OwnerCapitalLedger, Ledger

User = get_user_model()


class Command(BaseCommand):
    help = 'Remove all transactional data while preserving system defaults (admin user, permissions, content types)'

    def handle(self, *args, **options):
        delete_order = [
            InventoryReceiptItem,
            InventoryReceipt,
            PurchaseOrderItem,
            PurchaseOrder,
            TransactionLineItem,
            Ledger,
            OwnerCapitalLedger,
            Transaction,
            SaleSession,
            CreditProfile,
            Customer,
            RecipeIngredient,
            Product,
            Category,
            Vendor,
            Task, Success, Failure, Schedule, OrmQ,
            LogEntry,
            Group,
        ]
        for model in delete_order:
            qs = model.objects.all()
            count = qs.count()
            if count:
                qs.delete()
                self.stdout.write(f'  Deleted {count} {model.__name__} record(s)')
            else:
                self.stdout.write(f'  No {model.__name__} records to delete')

        kept = User.objects.exclude(username='admin').count()
        User.objects.exclude(username='admin').delete()
        self.stdout.write(f'  Deleted {kept} non-admin user(s)')

        admin_count = User.objects.filter(username='admin').count()
        self.stdout.write(self.style.SUCCESS(f'Done. Preserved {admin_count} admin user, {Permission.objects.count()} permissions, {ContentType.objects.count()} content types.'))
