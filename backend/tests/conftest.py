import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Role, User
from apps.tenants.models import Branch, Restaurant

PW = "Str0ng-Passw0rd!x"


def host(slug=None):
    return f"{slug}.platform.test" if slug else "platform.test"


@pytest.fixture
def world(db):
    """Two restaurants, two branches in A, one in B, and a user of every role."""
    a = Restaurant.objects.create(name="Alpha", slug="alpha")
    b = Restaurant.objects.create(name="Bravo", slug="bravo")
    a1 = Branch.unscoped.create(restaurant=a, name="A One", code="A1")
    a2 = Branch.unscoped.create(restaurant=a, name="A Two", code="A2")
    b1 = Branch.unscoped.create(restaurant=b, name="B One", code="B1")

    def mk(email, restaurant, role, branches=()):
        u = User.objects.create_user(email, PW, full_name=email.split("@")[0], email_verified=True)
        m = Membership.objects.create(user=u, restaurant=restaurant, role=role)
        m.branches.set(branches)
        return u

    return {
        "a": a, "b": b, "a1": a1, "a2": a2, "b1": b1,
        "platform": User.objects.create_user("root@x.com", PW, is_platform_admin=True, email_verified=True),
        "admin_a": mk("admin@a.com", a, Role.RESTAURANT_ADMIN),
        "admin_b": mk("admin@b.com", b, Role.RESTAURANT_ADMIN),
        "mgr_a1": mk("mgr1@a.com", a, Role.MANAGER, [a1]),
        "cashier_a1": mk("cash1@a.com", a, Role.CASHIER, [a1]),
        "cust_a": mk("cust@a.com", a, Role.CUSTOMER),
        "cust2_a": mk("cust2@a.com", a, Role.CUSTOMER),
        "kitchen_a1": mk("kitchen1@a.com", a, Role.KITCHEN, [a1]),
        "delivery_a1": mk("deliv1@a.com", a, Role.DELIVERY, [a1]),
        "cashier_a2": mk("cash2@a.com", a, Role.CASHIER, [a2]),
        "mgr_a2": mk("mgr2@a.com", a, Role.MANAGER, [a2]),
    }


def client_for(user, slug=None):
    c = APIClient(HTTP_HOST=host(slug))
    c.force_authenticate(user)
    return c
