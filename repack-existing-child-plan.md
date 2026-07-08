# Repack Into Existing Product — Implementation Plan

## Problem

The repack "Add Child" form only creates a **new** `Product` record. There is no way to link an **existing** product as a child in the repack breakdown. This means you cannot repack a bulk product into a product that was imported via CSV, received through purchase order, or created outside the repack page.

## Goal

Allow users to select an existing `Product` and link it as a child of a bulk parent via `RecipeIngredient`, without creating a new product. The `execute_repack` service already handles any linked child — no changes needed there.

---

## Step 1: Add `link_existing` action to `RepackView.post`

**File:** `inventory/views.py` — inside `RepackView.post()`, after the existing `add_child` block.

### Pseudocode

```python
elif action == 'link_existing':
    """
    Link an existing product as a child of a bulk parent.

    POST params:
      parent_id       — ID of the bulk product
      child_id        — ID of the existing product to link
      qty_per_parent  — Decimal quantity of child produced per 1 parent unit

    Logic:
      1. Require manager permission (same as add_child)
      2. Validate all required params present
      3. parent = get_object_or_404(Product, id=parent_id)
      4. child = get_object_or_404(Product, id=child_id)
      5. Validate: child != parent (can't link product to itself)
      6. Validate: no duplicate RecipeIngredient for (parent, child) already exists
         (unique_together handles DB-level, but check first for a better error message)
      7. RecipeIngredient.objects.create(
           parent_product=parent,
           child_product=child,
           quantity_required=Decimal(qty_per_parent),
         )
      8. messages.success(request, f'Linked "{child.name}" as child of "{parent.name}".')
      9. return HttpResponseRedirect(reverse_lazy('inventory:repack') + f'?parent={parent_id}')
    """
```

### Validation Details

```python
# Step 2 — Validate required fields
missing = []
if not parent_id: missing.append('parent_id')
if not child_id: missing.append('child_id')
if not qty_per_parent: missing.append('qty_per_parent')
if missing:
    messages.error(request, f'Missing fields: {", ".join(missing)}')
    return redirect back to repack with ?parent=parent_id

# Step 5 — Self-link guard
if int(child_id) == int(parent_id):
    messages.error(request, 'Cannot link a product to itself.')
    return redirect back

# Step 6 — Duplicate guard
existing_link = RecipeIngredient.objects.filter(
    parent_product_id=parent_id,
    child_product_id=child_id,
).exists()
if existing_link:
    messages.error(request, f'"{child.name}" is already linked to "{parent.name}".')
    return redirect back
```

---

## Step 2: Create `LinkExistingProductSearchView` — HTMX search endpoint

**File:** `inventory/views.py` — new view class, placed near `RepackProductSearchView`.

### Pseudocode

```python
class LinkExistingProductSearchView(LoginRequiredMixin, View):
    """
    GET /inventory/repack/link-search/?q=...&parent_id=...
    HTMX partial. Searches existing products that could be linked as children.

    Excludes:
      - The parent product itself
      - Products already linked to this parent via RecipeIngredient

    Returns partial template: inventory/partials/link_product_search.html
    """
    def get(self, request):
        q = request.GET.get('q', '').strip()
        parent_id = request.GET.get('parent_id')

        if len(q) < 2:
            html = render_to_string('inventory/partials/link_product_search.html', {
                'products': [],
                'q': q,
            })
            return HttpResponse(html)

        # Get IDs already linked as children of this parent
        existing_child_ids = RecipeIngredient.objects.filter(
            parent_product_id=parent_id,
        ).values_list('child_product_id', flat=True)

        # Search all products except parent and existing children
        products = Product.objects.exclude(
            id=parent_id,
        ).exclude(
            id__in=existing_child_ids,
        ).filter(
            Q(sku__icontains=q) | Q(name__icontains=q),
        ).select_related('vendor').order_by('name')[:15]

        html = render_to_string('inventory/partials/link_product_search.html', {
            'products': products,
            'q': q,
            'parent_id': parent_id,
        }, request=request)

        return HttpResponse(html)
```

### URL Route

**File:** `inventory/urls.py` — add after existing repack routes:

```python
path('repack/link-search/', views.LinkExistingProductSearchView.as_view(), name='link_product_search'),
```

---

## Step 3: Create `link_product_search.html` partial

**File:** `templates/inventory/partials/link_product_search.html` — new file.

### Pseudocode

```html
{% if q %}
  {% if products %}
    <div class="divide-y divide-gray-100 max-h-48 overflow-y-auto border rounded">
      {% for p in products %}
      <button type="button"
              data-child-id="{{ p.id }}"
              data-child-name="{{ p.name }}"
              data-child-sku="{{ p.sku }}"
              class="w-full text-left px-4 py-2.5 hover:bg-blue-50 transition text-sm flex items-center justify-between"
              onclick="selectExistingChild(this)">
        <div>
          <span class="font-medium text-gray-800">{{ p.name }}</span>
          <span class="text-gray-400 ml-2 text-xs">{{ p.sku }}</span>
        </div>
        <span class="text-xs text-gray-500">Stock: {{ p.stock_quantity }}</span>
      </button>
      {% endfor %}
    </div>
  {% else %}
    <div class="px-4 py-3 text-center text-gray-400 text-sm border rounded">
      No products match "{{ q }}"
    </div>
  {% endif %}
{% endif %}
```

### JavaScript Helper (inline in `repack.html` or a `<script>` block)

```javascript
function selectExistingChild(btn) {
    document.getElementById('link-child-id').value = btn.dataset.childId;
    document.getElementById('link-child-display').textContent =
        btn.dataset.childName + ' (' + btn.dataset.childSku + ')';
    document.getElementById('link-search-results').innerHTML = '';
    document.getElementById('link-search-input').value = '';
}
```

---

## Step 4: Update `repack.html` template — Add "Link Existing Product" form

**File:** `templates/inventory/repack.html`

Add a new section below the existing "Add Child Product" form. Wrap it in the same manager-only conditional.

### Pseudocode

```html
{% if request.user.is_manager and selected_parent %}
  <!-- ====== EXISTING "ADD CHILD PRODUCT" FORM (unchanged) ====== -->
  ...

  <!-- ====== NEW "LINK EXISTING PRODUCT" FORM ====== -->
  <div class="mt-6 pt-6 border-t border-gray-200">
    <h3 class="text-md font-semibold text-gray-800 mb-3">
      <i class="fas fa-link mr-2 text-blue-500"></i>Link Existing Product
    </h3>
    <p class="text-sm text-gray-500 mb-3">
      Select an existing product to link as a child of
      <strong>{{ selected_parent.name }}</strong>.
    </p>

    <form method="post">
      {% csrf_token %}
      <input type="hidden" name="action" value="link_existing">
      <input type="hidden" name="parent_id" value="{{ selected_parent.id }}">

      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <!-- Product Search -->
        <div class="md:col-span-2">
          <label class="block text-xs font-medium text-gray-600 mb-1">Find Product</label>
          <input type="text" id="link-search-input"
                 placeholder="Search by name or SKU..."
                 class="w-full bg-white rounded-lg border border-gray-300 px-3 py-2 text-sm"
                 hx-get="{% url 'inventory:link_product_search' %}?parent_id={{ selected_parent.id }}"
                 hx-target="#link-search-results"
                 hx-trigger="keyup changed delay:300ms"
                 hx-indicator="#link-search-spinner">
          <div id="link-search-spinner" class="htmx-indicator text-xs text-gray-400 mt-1">
            <i class="fas fa-spinner fa-spin"></i> Searching...
          </div>
          <div id="link-search-results" class="mt-1"></div>
        </div>

        <!-- Qty per Parent -->
        <div>
          <label class="block text-xs font-medium text-gray-600 mb-1">Qty per Parent</label>
          <input type="number" name="qty_per_parent" step="0.001" min="0.001"
                 class="w-full bg-white rounded-lg border border-gray-300 px-3 py-2 text-sm"
                 required>
        </div>
      </div>

      <!-- Selected Child Display -->
      <div class="mt-3 flex items-center gap-3">
        <span class="text-sm text-gray-500">Selected:</span>
        <span id="link-child-display" class="text-sm text-gray-400 italic">None</span>
        <input type="hidden" name="child_id" id="link-child-id" value="">
      </div>

      <!-- Submit -->
      <button type="submit"
              class="mt-3 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition">
        <i class="fas fa-link mr-1"></i> Link Product
      </button>
    </form>
  </div>
{% endif %}
```

---

## Step 5: Add `selected_parent` to the link-search context (optional cleanup)

The `LinkExistingProductSearchView` receives `parent_id` as a GET param. The view uses it to exclude already-linked children. No additional context changes are needed because the parent_id is passed via the HTMX URL directly.

---

## Step 6: Wire URL in `inventory/urls.py`

**File:** `inventory/urls.py`

```python
path('repack/link-search/', views.LinkExistingProductSearchView.as_view(), name='link_product_search'),
```

Place it after line 35 (existing `repack_product_search` route).

---

## No Changes Required

| File | Reason |
|---|---|
| `inventory/services.py` | `execute_repack()` operates on `RecipeIngredient` — works with any linked child regardless of how it was created |
| `inventory/models.py` | No new fields or constraints needed |
| `inventory/repack.html` / existing child display | The child breakdown already lists children by name/SKU — newly linked products will appear alongside newly created ones |
| `deduct_composite()` | Unaffected — handles POS sales, not repack |

---

## Flow Diagram (After Change)

```
User visits /inventory/repack/

  ├─ Search bulk products → select parent
  │
  ├─ [Children exist?]
  │    ├─ YES → show breakdown + Execute Repack form
  │    └─ NO  → show "No breakdown defined"
  │
  ├─ [Manager?]
  │    ├─ YES → show "Add Child Product" form (create new)
  │    │       + show "Link Existing Product" form (← NEW)
  │    │          ├─ Search existing product by name/SKU
  │    │          ├─ Click result → fills hidden child_id
  │    │          ├─ Enter qty per parent
  │    │          └─ Submit → RecipeIngredient created
  │    └─ NO  → only execute repack if children exist
  │
  └─ Execute Repack → consume parent stock, increment child stock
```

---

## Files Changed Summary

| File | Action | Lines Added |
|---|---|---|
| `inventory/views.py` | Add `link_existing` branch in `RepackView.post` | ~25 |
| `inventory/views.py` | Add `LinkExistingProductSearchView` class | ~25 |
| `inventory/urls.py` | Add `repack/link-search/` route | ~2 |
| `templates/inventory/repack.html` | Add "Link Existing Product" form section | ~45 |
| `templates/inventory/partials/link_product_search.html` | **Create** — HTMX search results partial | ~30 |

**Total new lines:** ~130 | **Files created:** 1 | **Files modified:** 3 | **Effort:** 3–5 hours
