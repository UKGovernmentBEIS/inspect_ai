from rectangle import Rectangle


def test_overlaps():
    bounds1 = Rectangle(10, 20, 30, 40)
    bounds2 = Rectangle(20, 30, 40, 50)
    assert bounds1.overlaps(bounds2)
    bounds3 = Rectangle(50, 60, 20, 30)
    assert not bounds1.overlaps(bounds3)


def test_within():
    bounds1 = Rectangle(231, 167, 2, 9)
    bounds2 = Rectangle(231, 167, 26, 9)
    assert bounds1.within(bounds2)
