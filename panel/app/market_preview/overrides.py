"""Bounds and immutable defaults for the shared native/panel price settings."""
import threading
import time

LOCK = threading.RLock()
MAX_ROWS = 8192
MAX_CHANGES = 256
META = {'__world_started__', '__median_wealth_40__', '__reference_version__'}


def valid(key, value):
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    bounds = {
        'glob:patch18': (18, 18),
        'glob:moonlight_pct': (-99, 1000), 'glob:bonus_boost_pct': (0, 500),
        'glob:cap_full': (100, 1000000), 'glob:cap_excess_pct': (0, 100),
        'glob:cap_vs_plus9': (0, 1000000), 'glob:young_world_days': (0, 36500),
        'glob:young_cap_pct': (0, 1000),
    }
    if key.startswith('glob:'):
        if key not in bounds:
            return False
        low, high = bounds[key]
    elif key.startswith(('bonusq:', 'intq:')):
        low, high = 0, 10000000
    elif key == '__median_wealth_40__':
        low, high = 0, 9000000000000000
    elif key.startswith('bonus:') and key.endswith((':lvfrom', ':lvto')):
        # Patch 19, 2E: a bonus row's level band, a BYTE in the native table.
        low, high = 0, 255
    elif key.startswith(('bonus:', 'avg:', 'skilltier:')):
        low, high = 0, 65535
    elif key.startswith(('sockcnt:', 'sockstone:')):
        low, high = 0, 10000
    else:
        low, high = 0, 0xffffffff
    return low <= value <= high


def validate(changes, defaults, allow_meta=False):
    if not isinstance(changes, dict) or len(changes) > (MAX_ROWS if allow_meta else MAX_CHANGES):
        raise ValueError('bad_changes')
    for key, value in changes.items():
        if not isinstance(key, str) or key.startswith('__') and not (allow_meta and key in META):
            raise ValueError('bad_key')
        if key not in defaults and not (allow_meta and key in META):
            raise ValueError('bad_key')
        if not valid(key, value):
            raise ValueError('out_of_range')
    return dict(changes)


def boost(value, percent):
    # Native integer division truncates towards zero, including discounts.
    part = (value - 100) * (100 + percent)
    scaled = abs(part) // 100 * (1 if part >= 0 else -1)
    return max(0, min(65535, 100 + scaled))


def options(values):
    return {'precise': values.get('glob:patch18') == 18, 'resulting': dict(values),
            'cap_active': 'glob:cap_full' in values or 'glob:cap_excess_pct' in values,
            'full': values.get('glob:cap_full', 10000), 'excess': values.get('glob:cap_excess_pct', 0),
            'plus9': values.get('glob:cap_vs_plus9', 0), 'young_days': values.get('glob:young_world_days', 0),
            'young_pct': values.get('glob:young_cap_pct', 0), 'started': values.get('__world_started__', 0),
            'median': values.get('__median_wealth_40__', 0)}


def migrated_multiplier(old_percent):
    return max(0, 10000 + (old_percent-100)*145)


def resulting_percent(key, legacy, policy):
    if policy.get('precise') and key in policy.get('resulting', {}):
        return policy['resulting'][key] / 100.0
    return legacy


def soft_cap(product, policy):
    if not policy.get('cap_active') or product <= policy['full']:
        return product
    return policy['full'] + (product-policy['full'])*policy['excess']//100


def final_cap(value, plus9, policy, now=None):
    if policy.get('plus9', 0) > 0 and plus9 > 0:
        value = min(value, plus9*policy['plus9']//100)
    started = policy.get('started', 0)
    age = (int(time.time()) if now is None else now)-started if started else -1
    if (policy.get('young_days', 0) > 0 and policy.get('young_pct', 0) > 0 and 0 <= age < 86400*policy['young_days']
            and policy.get('median', 0) > 0):
        value = min(value, policy['median']*policy['young_pct']//100)
    return max(1, value)


def synchronized(fn):
    from functools import wraps
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with LOCK:
            return fn(*args, **kwargs)
    return wrapped
