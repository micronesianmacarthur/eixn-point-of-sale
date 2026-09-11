from django.urls import path

from . import views

app_name = 'sales'

urlpatterns = [
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('checkout/', views.CheckoutView.as_view(), name='checkout'),
    path('checkout/search-products/', views.ProductSearchView.as_view(), name='product_search'),
    path('checkout/cart-add/', views.CartAddView.as_view(), name='cart_add'),
    path('checkout/cart-remove/<int:product_id>/', views.CartRemoveView.as_view(), name='cart_remove'),
    path('checkout/cart-update/<int:product_id>/', views.CartUpdateQtyView.as_view(), name='cart_update'),
    path('checkout/complete/', views.CheckoutCompleteView.as_view(), name='checkout_complete'),
    path('checkout/credit-check/', views.CreditCheckView.as_view(), name='credit_check'),
    path('top-products-today/', views.TopProductsTodayView.as_view(), name='top_products_today'),
    path('void/', views.VoidSaleView.as_view(), name='void_sale'),
    path('receipt/<int:pk>/', views.ReceiptView.as_view(), name='receipt'),
    path('<int:pk>/', views.TransactionDetailView.as_view(), name='transaction_detail'),
    path('<int:pk>/return/', views.ReturnSaleView.as_view(), name='return_sale'),
    path('offline-recovery/', views.OfflineRecoveryView.as_view(), name='offline_recovery'),
    path('backup/', views.BackupTriggerView.as_view(), name='backup_trigger'),
    path('sessions/create/', views.SessionCreateView.as_view(), name='session_create'),
    path('sessions/<int:pk>/close/', views.StepCountView.as_view(), name='close_step1'),
    path('sessions/<int:pk>/close/remove/', views.StepRemoveView.as_view(), name='close_step2'),
    path('sessions/<int:pk>/close/review/', views.StepReviewView.as_view(), name='close_step3'),
    path('sessions/<int:pk>/close/pdf/', views.ZReportPDFView.as_view(), name='close_pdf'),
    path('sessions/<int:pk>/close/legacy/', views.SessionCloseView.as_view(), name='session_close'),
    path('table/', views.SaleListTableView.as_view(), name='sale_table'),
    path('', views.SaleListView.as_view(), name='sale_list'),
]
