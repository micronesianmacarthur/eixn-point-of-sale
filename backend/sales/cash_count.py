from decimal import Decimal

CURRENCY_DEFS = [
    (Decimal('0.01'), 'pennies', 'coins'),
    (Decimal('0.05'), 'nickels', 'coins'),
    (Decimal('0.10'), 'dimes', 'coins'),
    (Decimal('0.25'), 'quarters', 'coins'),
    (Decimal('0.50'), 'half_dollars', 'coins'),
    (Decimal('1.00'), 'dollars', 'coins'),
    (Decimal('2.00'), 'two_dollars', 'coins'),
    (Decimal('1.00'), 'ones', 'bills'),
    (Decimal('2.00'), 'twos', 'bills'),
    (Decimal('5.00'), 'fives', 'bills'),
    (Decimal('10.00'), 'tens', 'bills'),
    (Decimal('20.00'), 'twenties', 'bills'),
    (Decimal('50.00'), 'fifties', 'bills'),
    (Decimal('100.00'), 'hundreds', 'bills'),
]


def calculate_totals(counts: dict[str, int]) -> dict:
    totals = {'bills': Decimal('0'), 'coins': Decimal('0')}
    breakdown = []
    for val, key, cat in CURRENCY_DEFS:
        count = counts.get(key, 0)
        amount = count * val
        totals[cat] += amount
        breakdown.append({'key': key, 'count': count, 'amount': amount, 'category': cat})
    totals['grand_total'] = totals['bills'] + totals['coins']
    totals['breakdown'] = breakdown
    return totals


def calculate_removal(remove_amount: Decimal, available_counts: dict[str, int]) -> dict:
    results = {
        'counts': {},
        'amounts': {},
        'category_totals': {'bills': Decimal('0'), 'coins': Decimal('0')},
        'total_removed': Decimal('0'),
        'remaining': remove_amount,
    }
    remaining = remove_amount
    sorted_defs = sorted(CURRENCY_DEFS, key=lambda x: x[0], reverse=True)
    for val, key, cat in sorted_defs:
        available = available_counts.get(key, 0)
        count_taken = min(int(remaining / val), available)
        amount_taken = count_taken * val
        remaining -= amount_taken
        results['total_removed'] += amount_taken
        results['category_totals'][cat] += amount_taken
        results['counts'][key] = count_taken
        results['amounts'][key] = amount_taken
    results['remaining'] = remaining
    return results
