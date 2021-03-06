from alchemy.ar.data import (
    _compute_total_distinct_number_of_annotated_entities_for_label,
)
from alchemy.db.model import ClassificationAnnotation, User


def test__compute_total_distinct_number_of_annotated_entities_for_label(dbsession):
    user_1 = User(username="user_1")
    user_2 = User(username="user_2")

    def _anno(entity_type, entity, value, user):
        return ClassificationAnnotation(
            entity=entity, entity_type=entity_type, label="foo", value=value, user=user
        )

    # Add 3 distinct entities with labels, 2 with an unknown annotation.
    # Unknown annotations are not counted. So this should be 3.
    annos = [
        _anno("Company", "X", 1, user_1),
        _anno("Company", "Y", 1, user_1),
        _anno("Company", "Z", -1, user_1),
        _anno("Company", "X", 1, user_2),
        _anno("Company", "X", -1, user_2),
        _anno("Company", "Y", 0, user_2),
        _anno("Company", "Q", 0, user_2),
    ]
    dbsession.add_all([user_1, user_2] + annos)
    dbsession.commit()

    res = _compute_total_distinct_number_of_annotated_entities_for_label(
        dbsession, "foo"
    )
    assert res == 3

    # Add some data of a different type:
    annos = [_anno("Person", "X", 1, user_1), _anno("Person", "Y", 1, user_1)]
    dbsession.add_all([user_1, user_2] + annos)
    dbsession.commit()

    res = _compute_total_distinct_number_of_annotated_entities_for_label(
        dbsession, "foo"
    )
    assert res == 5
