"""Tests for StoreModel with nested types (Pydantic models, TypedDicts, dataclasses, etc.)"""

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple, Union, cast

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from inspect_ai.util import Store, StoreModel


# Test models and types
class Address(BaseModel):
    street: str
    city: str
    zip_code: str


class Person(BaseModel):
    name: str
    age: int
    address: Optional[Address] = None


class UserTypedDict(TypedDict):
    username: str
    email: str
    is_active: bool


@dataclass
class Product:
    id: int
    name: str
    price: float


class SystemMessage(BaseModel):
    content: str
    type: Literal["system"] = "system"


class UserMessage(BaseModel):
    content: str
    type: Literal["user"] = "user"


Message = Union[SystemMessage, UserMessage]


# Test StoreModels
class NestedPydanticStore(StoreModel):
    person: Person = Field(default_factory=lambda: Person(name="", age=0))
    people: List[Person] = Field(default_factory=list)
    person_dict: Dict[str, Person] = Field(default_factory=dict)


class TypedDictStore(StoreModel):
    user: UserTypedDict = Field(
        default_factory=lambda: cast(
            UserTypedDict, {"username": "", "email": "", "is_active": False}
        )
    )
    users: List[UserTypedDict] = Field(default_factory=list)


class DataclassStore(StoreModel):
    product: Product = Field(default_factory=lambda: Product(0, "", 0.0))
    products: List[Product] = Field(default_factory=list)


class UnionTypeStore(StoreModel):
    message: Optional[Message] = None
    messages: List[Message] = Field(default_factory=list)


class TupleStore(StoreModel):
    coords: Tuple[float, float] = (0.0, 0.0)
    matrix: List[Tuple[int, int, int]] = Field(default_factory=list)


class MixedStore(StoreModel):
    data: Dict[str, Any] = Field(default_factory=dict)
    items: List[Union[Person, Product]] = Field(default_factory=list)


def test_nested_pydantic_model_coercion():
    """Test that nested Pydantic models are properly coerced from dicts."""
    # Create a store with dict data
    store = Store()
    store.set(
        "NestedPydanticStore:person",
        {
            "name": "Alice",
            "age": 30,
            "address": {
                "street": "123 Main St",
                "city": "Springfield",
                "zip_code": "12345",
            },
        },
    )

    # Access through StoreModel
    model = NestedPydanticStore(store=store)

    # Verify coercion happened
    assert isinstance(model.person, Person)
    assert model.person.name == "Alice"
    assert isinstance(model.person.address, Address)
    assert model.person.address.city == "Springfield"

    # Verify mutations persist
    model.person.age = 31
    assert store.get("NestedPydanticStore:person").age == 31


def test_list_of_pydantic_models_coercion():
    """Test that lists of Pydantic models are properly coerced."""
    store = Store()
    store.set(
        "NestedPydanticStore:people",
        [
            {"name": "Bob", "age": 25, "address": None},
            {
                "name": "Carol",
                "age": 28,
                "address": {
                    "street": "456 Oak Ave",
                    "city": "Portland",
                    "zip_code": "67890",
                },
            },
        ],
    )

    model = NestedPydanticStore(store=store)

    # Verify all items are coerced
    assert len(model.people) == 2
    assert all(isinstance(p, Person) for p in model.people)
    assert model.people[0].name == "Bob"
    assert model.people[1].address.street == "456 Oak Ave"

    # Verify list mutations persist
    model.people.append(Person(name="Dave", age=35))
    assert len(store.get("NestedPydanticStore:people")) == 3
    assert store.get("NestedPydanticStore:people")[2].name == "Dave"


def test_dict_of_pydantic_models_coercion():
    """Test that dicts with Pydantic model values are properly coerced."""
    store = Store()
    store.set(
        "NestedPydanticStore:person_dict",
        {
            "alice": {"name": "Alice", "age": 30, "address": None},
            "bob": {"name": "Bob", "age": 25, "address": None},
        },
    )

    model = NestedPydanticStore(store=store)

    # Verify dict values are coerced
    assert isinstance(model.person_dict["alice"], Person)
    assert model.person_dict["alice"].name == "Alice"

    # Verify dict mutations persist
    model.person_dict["carol"] = Person(name="Carol", age=28)
    assert "carol" in store.get("NestedPydanticStore:person_dict")
    assert store.get("NestedPydanticStore:person_dict")["carol"].name == "Carol"


def test_typeddict_coercion():
    """Test that TypedDict types are properly handled."""
    store = Store()
    store.set(
        "TypedDictStore:user",
        {"username": "johndoe", "email": "john@example.com", "is_active": True},
    )
    store.set(
        "TypedDictStore:users",
        [
            {"username": "alice", "email": "alice@example.com", "is_active": True},
            {"username": "bob", "email": "bob@example.com", "is_active": False},
        ],
    )

    model = TypedDictStore(store=store)

    # TypedDicts remain as dicts but are validated
    assert isinstance(model.user, dict)
    assert model.user["username"] == "johndoe"
    assert len(model.users) == 2
    assert model.users[0]["email"] == "alice@example.com"

    # Mutations persist
    model.user["is_active"] = False
    assert store.get("TypedDictStore:user")["is_active"] is False


def test_dataclass_coercion():
    """Test that dataclass types are properly coerced."""
    store = Store()
    store.set("DataclassStore:product", {"id": 1, "name": "Laptop", "price": 999.99})
    store.set(
        "DataclassStore:products",
        [
            {"id": 2, "name": "Mouse", "price": 29.99},
            {"id": 3, "name": "Keyboard", "price": 79.99},
        ],
    )

    model = DataclassStore(store=store)

    # Verify dataclass coercion
    assert isinstance(model.product, Product)
    assert model.product.name == "Laptop"
    assert all(isinstance(p, Product) for p in model.products)
    assert model.products[1].price == 79.99

    # Verify mutations persist
    model.product.price = 899.99
    assert store.get("DataclassStore:product").price == 899.99


def test_union_type_coercion():
    """Test that Union types are properly coerced."""
    store = Store()
    store.set(
        "UnionTypeStore:message", {"content": "System starting", "type": "system"}
    )
    store.set(
        "UnionTypeStore:messages",
        [
            {"content": "Hello", "type": "user"},
            {"content": "Hi there", "type": "system"},
        ],
    )

    model = UnionTypeStore(store=store)

    # Verify Union type coercion
    assert isinstance(model.message, SystemMessage | UserMessage)
    assert model.message.type == "system"

    assert len(model.messages) == 2
    assert isinstance(model.messages[0], UserMessage)
    assert isinstance(model.messages[1], SystemMessage)

    # Verify mutations persist
    model.messages.append(UserMessage(content="New message"))
    assert len(store.get("UnionTypeStore:messages")) == 3


def test_tuple_coercion():
    """Test that tuple types are properly coerced."""
    store = Store()
    store.set("TupleStore:coords", [1.5, 2.5])  # Lists are coerced to tuples
    store.set("TupleStore:matrix", [[1, 2, 3], [4, 5, 6]])

    model = TupleStore(store=store)

    # Verify tuple coercion
    assert isinstance(model.coords, tuple)
    assert model.coords == (1.5, 2.5)

    assert len(model.matrix) == 2
    assert all(isinstance(row, tuple) for row in model.matrix)
    assert model.matrix[0] == (1, 2, 3)


def test_mixed_nested_types():
    """Test complex mixed nested type scenarios."""
    store = Store()
    store.set(
        "MixedStore:data",
        {
            "person": {"name": "Alice", "age": 30, "address": None},
            "product": {"id": 1, "name": "Widget", "price": 19.99},
            "list": [1, 2, 3],
            "scalar": "hello",
        },
    )
    store.set(
        "MixedStore:items",
        [
            {"name": "Bob", "age": 25, "address": None},  # Person
            {"id": 2, "name": "Gadget", "price": 29.99},  # Product
        ],
    )

    model = MixedStore(store=store)

    # Dict[str, Any] preserves structure but validates
    assert isinstance(model.data, dict)
    assert model.data["scalar"] == "hello"
    assert model.data["list"] == [1, 2, 3]

    # Union types in list are coerced
    assert len(model.items) == 2
    assert isinstance(model.items[0], Person | Product)


def test_scalar_values_not_coerced() -> None:
    """Test that scalar values are not unnecessarily coerced."""

    class ScalarStore(StoreModel):
        text: str = "default"
        number: int = 0
        decimal: float = 0.0
        flag: bool = False
        nothing: Optional[str] = None
        data: bytes = b""

    store = Store()
    store.set("ScalarStore:text", "hello")
    store.set("ScalarStore:number", 42)
    store.set("ScalarStore:decimal", 3.14)
    store.set("ScalarStore:flag", True)
    store.set("ScalarStore:nothing", None)
    store.set("ScalarStore:data", b"binary")

    model = ScalarStore(store=store)

    # Verify scalars are returned directly without coercion
    assert model.text == "hello"
    assert model.number == 42
    assert model.decimal == 3.14
    assert model.flag is True
    assert model.nothing is None
    assert model.data == b"binary"


def test_coercion_caching():
    """Test that coerced values are cached in the store."""
    store = Store()
    store.set(
        "NestedPydanticStore:person", {"name": "Alice", "age": 30, "address": None}
    )

    model = NestedPydanticStore(store=store)

    # First access coerces
    person1 = model.person
    assert isinstance(person1, Person)

    # Second access should return the same object (cached)
    person2 = model.person
    assert person1 is person2

    # Store should now contain the Person object, not dict
    stored_value = store.get("NestedPydanticStore:person")
    assert isinstance(stored_value, Person)
    assert stored_value is person1


def test_invalid_data_returns_raw() -> None:
    """Test that invalid data that can't be coerced returns raw value."""

    class StrictStore(StoreModel):
        person: Person = Field(default_factory=lambda: Person(name="", age=0))

    store = Store()
    # Invalid data - missing required fields
    store.set("StrictStore:person", {"invalid": "data"})

    model = StrictStore(store=store)

    # Should return the raw invalid data since coercion failed
    # (though validation might fail later if strict validation is enabled)
    person = model.person
    assert isinstance(person, dict)
    assert person == {"invalid": "data"}


def test_multiple_instances_with_nested_types():
    """Test multiple StoreModel instances with nested types."""
    store = Store()

    # Create two instances with different data
    model1 = NestedPydanticStore(store=store, instance="user1")
    model2 = NestedPydanticStore(store=store, instance="user2")

    model1.person = Person(name="Alice", age=30)
    model2.person = Person(name="Bob", age=25)

    # Verify they maintain separate data
    assert model1.person.name == "Alice"
    assert model2.person.name == "Bob"

    # Verify store has both namespaced
    assert "NestedPydanticStore:user1:person" in store.keys()
    assert "NestedPydanticStore:user2:person" in store.keys()


def test_deeply_nested_structures() -> None:
    """Test deeply nested structures are properly coerced."""

    class DeeplyNested(BaseModel):
        value: str

    class NestedLevel2(BaseModel):
        items: List[DeeplyNested]

    class NestedLevel1(BaseModel):
        level2: NestedLevel2

    class DeepStore(StoreModel):
        root: NestedLevel1 = Field(
            default_factory=lambda: NestedLevel1(level2=NestedLevel2(items=[]))
        )

    store = Store()
    store.set(
        "DeepStore:root",
        {"level2": {"items": [{"value": "first"}, {"value": "second"}]}},
    )

    model = DeepStore(store=store)

    # Verify deep coercion
    assert isinstance(model.root, NestedLevel1)
    assert isinstance(model.root.level2, NestedLevel2)
    assert all(isinstance(item, DeeplyNested) for item in model.root.level2.items)
    assert model.root.level2.items[0].value == "first"

    # Verify mutations work at depth
    model.root.level2.items.append(DeeplyNested(value="third"))
    assert len(store.get("DeepStore:root").level2.items) == 3
