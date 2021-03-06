import itertools
import logging
from collections import namedtuple
from typing import Dict, List

import numpy as np
import pandas as pd
from pandas import DataFrame
from sklearn.metrics import cohen_kappa_score
from sqlalchemy import distinct, func

from alchemy.db.model import (
    AnnotationRequest,
    AnnotationRequestStatus,
    AnnotationType,
    AnnotationValue,
    ClassificationAnnotation,
)
from alchemy.db.model import Task as NewTask
from alchemy.db.model import (
    User,
    db,
    delete_requests_for_user_under_task,
    update_instance,
)
from alchemy.shared.annotation_server_path_finder import (
    generate_annotation_server_compare_link,
)
from alchemy.shared.utils import (
    PrettyDefaultDict,
)

# Utility namedtuples
UserNameAndIdPair = namedtuple("UserNameAndIdPair", ["username", "id"])
EntityAndAnnotationValuePair = namedtuple(
    "EntityAndAnnotationValuePair", ["entity", "value"]
)


def save_new_ar_for_user_db(
    dbsession,
    task_id,
    username,
    annotation_requests,
    label,
    entity_type,
    clean_existing=True,
):
    user = (dbsession.query(User)
            .filter_by(username=username)
            .one_or_none())
    if not user:
        # Should not happen since the annotator usernames are not arbitrary anymore
        raise ValueError(f"Annotator {user} is not registered on the website.")
    if clean_existing:
        try:
            delete_requests_for_user_under_task(
                dbsession=dbsession, username=username, task_id=task_id
            )
            dbsession.commit()
            logging.info(
                "Deleted requests under user {} for task {}".format(username, task_id)
            )
        except Exception as e:
            dbsession.rollback()
            logging.error(e)
            raise

    try:
        # TODO requests were generated in reverse order.
        for i, req in enumerate(annotation_requests[::-1]):
            """
            Currently the full request looks like:
            {
                "fname": "myfile.jsonl",             <-- (optional)
                "line_number": 78,                   <-- (optional)
                "score": 0.11627906976744186,
                "entity": "blah",
                "data": {
                    "text": "Blah blah ...",
                    "meta": {"name": "Blah", "domain": "blah"}
                },
                "pattern_info": {                    <-- (optional)
                    "tokens": ["Blah", "blah", ...],
                    "matches": [(1, 2, "Blah"), ...],
                    "score": 0.11627906976744186
                }
            }
            """
            new_request = AnnotationRequest(
                user_id=user.id,
                entity_type=entity_type,
                entity=req["entity"],
                label=label,
                annotation_type=AnnotationType.ClassificationAnnotation,
                task_id=task_id,
                context=req,
                order=i,
            )
            dbsession.add(new_request)
        dbsession.commit()
    except Exception as e:
        logging.error(e)
        dbsession.rollback()
        raise


def fetch_tasks_for_user_from_db(dbsession, username):
    res = (
        dbsession.query(AnnotationRequest.task_id, NewTask.name)
        .distinct(AnnotationRequest.task_id, NewTask.name)
        .join(NewTask)
        .join(User)
        .filter(User.username == username)
        .all()
    )
    TaskIdAndNamePair = namedtuple("TaskIdAndNamePair", ["task_id", "name"])
    return [TaskIdAndNamePair(item[0], item[1]) for item in res]


def fetch_ar_ids(dbsession, task_id, username):
    query = (
        dbsession.query(AnnotationRequest.id)
        .join(User)
        .filter(User.username == username, AnnotationRequest.task_id == task_id)
    )
    res = query.all()
    print(res)
    return [item[0] for item in res]


def fetch_ar_id_and_status(dbsession, task_id, username):
    query = (
        dbsession.query(AnnotationRequest.id, AnnotationRequest.status)
        .join(User)
        .filter(User.username == username, AnnotationRequest.task_id == task_id)
        .order_by(AnnotationRequest.order)
    )
    return query.all()


def count_ar_under_task_and_user(dbsession, task_id, username):
    res = (
        dbsession.query(func.count(AnnotationRequest.id))
        .join(User)
        .filter(User.username == username, AnnotationRequest.task_id == task_id)
        .all()
    )
    return res[0][0]


def count_completed_ar_under_task_and_user(dbsession, task_id, username):
    res = (
        dbsession.query(func.count(AnnotationRequest.id))
        .join(User)
        .filter(
            User.username == username,
            AnnotationRequest.task_id == task_id,
            AnnotationRequest.status == AnnotationRequestStatus.Complete,
        )
        .all()
    )
    return res[0][0]


# TODO refactor this piece since it's a duplicate of the ar_request function.
def construct_annotation_dict(dbsession, annotation_id) -> Dict:
    # TODO possible destructing of None
    annotation_id, entity, entity_type, label, context = (
        dbsession.query(
            ClassificationAnnotation.id,
            ClassificationAnnotation.entity,
            ClassificationAnnotation.entity_type,
            ClassificationAnnotation.label,
            ClassificationAnnotation.context,
        )
        .filter(ClassificationAnnotation.id == annotation_id)
        .one_or_none()
    )

    result = {
        # Essential fields
        "annotation_id": annotation_id,
        "entity": entity,
        "entity_type": entity_type,
        "label": label,
        # Optional fields
        "fname": None,
        "line_number": None,
        "score": None,
        "data": None,
        "pattern_info": None,
    }

    if context is not None and isinstance(context, dict):
        result.update(
            {
                "fname": context.get("fname"),
                "line_number": context.get("line_number"),
                "score": context.get("score"),
                "data": context.get("data") if "data" in context else context,
                "pattern_info": context.get("pattern_info"),
            }
        )
    else:
        # TODO this is a temporarily workaround since some entities only
        #  have annotations but not annotation requests in my local db and
        #  they are not from Salesforce. Weird...
        #  I can't run backfill on the context column so I have to hardcode
        #  a text field to show the description on the annotation server.
        result.update({"data": {"text": context}})

    return result


def construct_ar_request_dict(dbsession, ar_id) -> Dict:
    request_id, entity, entity_type, label, context = (
        dbsession.query(
            AnnotationRequest.id,
            AnnotationRequest.entity,
            AnnotationRequest.entity_type,
            AnnotationRequest.label,
            AnnotationRequest.context,
        )
        .filter(AnnotationRequest.id == ar_id)
        .one_or_none()
    )

    result = {
        # Essential fields
        "ar_id": request_id,
        "entity": entity,
        "entity_type": entity_type,
        "label": label,
        # Optional fields
        "fname": None,
        "line_number": None,
        "score": None,
        "data": None,
        "pattern_info": None,
    }

    if context is not None:
        result.update(
            {
                "fname": context.get("fname"),
                "line_number": context.get("line_number"),
                "score": context.get("score"),
                "data": context.get("data"),
                "pattern_info": context.get("pattern_info"),
            }
        )

    return result


def get_next_ar_id_from_db(dbsession, task_id, user_id, current_ar_id):
    res = (
        dbsession.query(AnnotationRequest.id)
        .filter(
            AnnotationRequest.task_id == task_id,
            AnnotationRequest.user_id == user_id,
            AnnotationRequest.id > current_ar_id,
        )
        .order_by(AnnotationRequest.id.asc())
        .first()
    )
    if res is not None:
        return res[0]
    else:
        return res


def get_next_annotation_id_from_db(dbsession, user_id, current_annotation_id, labels):
    res = (
        dbsession.query(ClassificationAnnotation.id)
        .filter(
            ClassificationAnnotation.user_id == user_id,
            ClassificationAnnotation.id > current_annotation_id,
            ClassificationAnnotation.label.in_(labels),
            ClassificationAnnotation.value != AnnotationValue.NOT_ANNOTATED,
        )
        .order_by(ClassificationAnnotation.id.asc())
        .first()
    )
    if res is not None:
        return res[0]
    else:
        return res


def build_empty_annotation(ar):
    return {"req": ar, "anno": {"labels": {}}}


def mark_ar_complete_in_db(dbsession, ar_id):
    logging.info(
        "Updating the status of the annotation "
        "request {} to {}".format(ar_id, AnnotationRequestStatus.Complete)
    )
    update_instance(
        dbsession=dbsession,
        model=AnnotationRequest,
        filter_by_dict={"id": ar_id},
        update_dict={"status": AnnotationRequestStatus.Complete},
    )
    # logging.info("Updating the value of the annotation {} to {}".format(
    #     annotation_id, annotation_result))
    # update_instance(dbsession=dbsession,
    #                 model=ClassificationAnnotation,
    #                 filter_by_dict={"id": annotation_id},
    #                 update_dict={"value": annotation_result})
    # logging.info("Updated annotation request and result.")


def fetch_user_id_by_username(dbsession, username):
    return dbsession.query(User.id).filter(User.username == username).one_or_none()[0]


def fetch_existing_classification_annotation_from_db(dbsession, annotation_id):
    return (
        dbsession.query(ClassificationAnnotation.label, ClassificationAnnotation.value)
        .filter(ClassificationAnnotation.id == annotation_id)
        .one_or_none()
    )


def fetch_annotated_ar_ids_from_db(dbsession, task_id, username):
    res = (
        dbsession.query(AnnotationRequest.id)
        .join(User)
        .filter(
            AnnotationRequest.task_id == task_id,
            AnnotationRequest.status == AnnotationRequestStatus.Complete,
            User.username == username,
        )
        .all()
    )

    return [item[0] for item in res]


def compute_annotation_request_statistics(dbsession, task_id):
    total_number_of_outstanding_requests = (
        dbsession.query(AnnotationRequest)
        .filter(
            AnnotationRequest.task_id == task_id,
            AnnotationRequest.status == AnnotationRequestStatus.Pending,
        )
        .count()
    )

    n_outstanding_requests_per_user = (
        dbsession.query(func.count(AnnotationRequest.id), User.username)
        .join(User)
        .filter(AnnotationRequest.task_id == task_id)
        .filter(AnnotationRequest.status == AnnotationRequestStatus.Pending)
        .group_by(User.username)
        .all()
    )
    n_outstanding_requests_per_user_dict = {
        username: num for num, username in n_outstanding_requests_per_user
    }

    return {
        "total_outstanding_requests": total_number_of_outstanding_requests,
        "n_outstanding_requests_per_user": n_outstanding_requests_per_user_dict,
    }


def compute_annotation_statistics_db(dbsession, label, task_id):
    total_distinct_annotated_entities = _compute_total_distinct_number_of_annotated_entities_for_label(
        dbsession=dbsession, label=label
    )

    num_of_annotations_done_per_user = _compute_number_of_annotations_done_per_user(
        dbsession=dbsession, label=label
    )

    user_names_mapping = {
        username: (f'{first_name or ""} {last_name or ""}'.strip() or username)
        for _, username, first_name, last_name, _ in num_of_annotations_done_per_user
    }

    total_num_of_annotations_done_by_users = sum(
        [num for num, username, first_name, last_name, user_id in num_of_annotations_done_per_user]
    )
    n_annotations_done_per_user_dict = {
        user_names_mapping[username]: num
        for num, username, first_name, last_name, user_id in num_of_annotations_done_per_user
    }

    num_of_annotations_per_value = _compute_num_of_annotations_per_value(
        dbsession=dbsession, label=label
    )

    # kappa stats calculation
    distinct_users = set(
        [
            UserNameAndIdPair(username=user_names_mapping[item[1]], id=item[4])
            for item in num_of_annotations_done_per_user
        ]
    )

    kappa_stats_raw_data = _construct_kappa_stats_raw_data(
        db.session, distinct_users, label
    )

    kappa_matrices = _compute_kappa_matrix(kappa_stats_raw_data)

    kappa_analysis_link_dict = _construct_kappa_analysis_link_dict(
        kappa_matrices=kappa_matrices, task_id=task_id
    )

    return {
        "total_annotations": total_num_of_annotations_done_by_users,
        "total_distinct_annotated_entities": total_distinct_annotated_entities,
        "n_annotations_per_value": num_of_annotations_per_value,
        "n_annotations_per_user": n_annotations_done_per_user_dict,
        "kappa_table": kappa_matrices,
        "kappa_analysis_link_dict": kappa_analysis_link_dict,
    }


def _compute_num_of_annotations_per_value(dbsession, label):
    res = (
        dbsession.query(
            func.count(ClassificationAnnotation.id), ClassificationAnnotation.value
        )
        .filter_by(label=label)
        .group_by(ClassificationAnnotation.value)
        .all()
    )
    data = PrettyDefaultDict(lambda: 0)
    for item in res:
        data[item[1]] = item[0]
    return data


def _compute_total_distinct_number_of_annotated_entities_for_label(dbsession, label):
    """Note: An "unknown" annotation (of value 0) doesn't count.
    """
    query = (
        dbsession.query(
            ClassificationAnnotation.entity_type, ClassificationAnnotation.entity
        )
        .filter_by(label=label)
        .filter(ClassificationAnnotation.value != 0)
        .group_by(ClassificationAnnotation.entity_type, ClassificationAnnotation.entity)
    )

    return query.count()


def _compute_number_of_annotations_done_per_user(dbsession, label):
    num_of_annotations_done_per_user = (
        dbsession.query(
            func.count(ClassificationAnnotation.id),
            User.username,
            User.first_name,
            User.last_name,
            User.id
        )
        .join(User)
        .filter(ClassificationAnnotation.label == label)
        .group_by(User.username, User.id)
        .all()
    )

    return num_of_annotations_done_per_user


def _construct_kappa_stats_raw_data(dbsession, distinct_users, label):
    entities_and_annotation_values_by_user = _retrieve_entity_ids_and_annotation_values_by_user(
        dbsession, distinct_users, label
    )
    user_pairs = list(itertools.combinations(distinct_users, 2))
    kappa_stats_raw_data = {
        label: {
            tuple(
                sorted([user_pair[0].username, user_pair[1].username])
            ): _retrieve_annotation_with_same_entity_shared_by_two_users(
                user_pair[0], user_pair[1], entities_and_annotation_values_by_user
            )
            for user_pair in user_pairs
        }
    }
    return kappa_stats_raw_data


def _retrieve_entity_ids_and_annotation_values_by_user(dbsession, users, label):
    res = (
        dbsession.query(
            ClassificationAnnotation.entity,
            ClassificationAnnotation.value,
            ClassificationAnnotation.user_id,
        )
        .filter(
            ClassificationAnnotation.label == label,
            ClassificationAnnotation.user_id.in_([user.id for user in users]),
        )
        .all()
    )

    data = PrettyDefaultDict(lambda: [])
    for item in res:
        data[item[2]].append(
            EntityAndAnnotationValuePair(entity=item[0], value=item[1])
        )
    return data


def _retrieve_annotation_with_same_entity_shared_by_two_users(
    user1, user2, entities_and_annotation_values_by_user
):
    annotations_from_user1 = entities_and_annotation_values_by_user[user1.id]
    annotations_from_user2 = entities_and_annotation_values_by_user[user2.id]

    dict_of_context_value_from_user1 = {
        annotation.entity: annotation.value for annotation in annotations_from_user1
    }

    dict_of_context_value_from_user2 = {
        annotation.entity: annotation.value for annotation in annotations_from_user2
    }
    intersection = set(dict_of_context_value_from_user1.keys()).intersection(
        set(dict_of_context_value_from_user2.keys())
    )
    intersection = sorted(list(intersection))

    if len(intersection) == 0:
        return None

    values_from_annotations_with_overlapping_context_user1 = [
        dict_of_context_value_from_user1[entity] for entity in intersection
    ]

    values_from_annotations_with_overlapping_context_user2 = [
        dict_of_context_value_from_user2[entity] for entity in intersection
    ]

    return {
        user1.username: values_from_annotations_with_overlapping_context_user1,
        user2.username: values_from_annotations_with_overlapping_context_user2,
    }


def _compute_kappa_matrix(kappa_stats_raw_data):
    """Compute the kappa matrix for each label and return the html form of the
    matrix.

    :param user_ids: the user ids
    :param kappa_stats_raw_data: raw labeling results per label per user pair
    on overlapping annotations
    :return: a dictionary of kappa matrix html table per label

    Structure of the input:
    {
        "label1": {
            ("user_id1", "user_id2"): {
                "user_id1": [1, -1, 1, 1, -1],
                "user_id2": [-1, 1, 1, -1, 1]
            },
            ("user_id1", "user_id3"): {
                "user_id1": [1, -1],
                "user_id2": [-1, 1]
            }
            ...
        },
        "label12": {
            ("user_id1", "user_id3"): {
                "user_id1": [1, -1],
                "user_id2": [-1, 1]
            },
            ...
        },
        ...
    }

    Structure of the final output:
    {
        "label1": kappa matrix for this label as a pandas dataframe,
        "label2": kappa matrix for this label as a pandas dataframe,
        ...
    }

    """
    kappa_matrix = PrettyDefaultDict(
        lambda: PrettyDefaultDict(lambda: PrettyDefaultDict(float))
    )
    for label, result_per_user_pair_per_label in sorted(kappa_stats_raw_data.items()):
        for user_pair, result_per_user in result_per_user_pair_per_label.items():
            if result_per_user is None:
                kappa_matrix[label][user_pair[0]][user_pair[1]] = np.nan
                kappa_matrix[label][user_pair[1]][user_pair[0]] = np.nan
            else:
                result_user1 = result_per_user[user_pair[0]]
                result_user2 = result_per_user[user_pair[1]]
                logging.info(
                    "Calculating the kappa score for {} and {}".format(
                        user_pair[0], user_pair[1]
                    )
                )
                result_user1, result_user2 = _exclude_unknowns_for_kappa_calculation(
                    result_user1, result_user2
                )
                kappa_score = cohen_kappa_score(result_user1, result_user2)
                kappa_score = float("{:.2f}".format(kappa_score))
                kappa_matrix[label][user_pair[0]][user_pair[1]] = kappa_score
                kappa_matrix[label][user_pair[1]][user_pair[0]] = kappa_score

            kappa_matrix[label][user_pair[0]][user_pair[0]] = 1
            kappa_matrix[label][user_pair[1]][user_pair[1]] = 1

    kappa_dataframe = PrettyDefaultDict(DataFrame)
    for label, nested_dict in kappa_matrix.items():
        kappa_dataframe[label] = (
            pd.DataFrame.from_dict(nested_dict).sort_index(axis=0).sort_index(axis=1)
        )
    return kappa_dataframe


def _exclude_unknowns_for_kappa_calculation(result_user1, result_user2):
    """Exclude unknowns for kappa calculation.

    This means if either of the user's label result is unknown then we
    should include neither in the final calculation.

    :param result_user1: labeling results from user1 with potentially unknowns
    :param result_user2: labeling results from user2 with potentially unknowns
    :return: the labeling result tuple without unknowns
    """
    if len(result_user1) != len(result_user2):
        raise ValueError("The number of labeling results should be the same.")
    labeling_results1 = []
    labeling_results2 = []
    ignored_count = 0
    for i in range(len(result_user1)):
        if result_user1[i] != 0 and result_user2[i] != 0:
            labeling_results1.append(result_user1[i])
            labeling_results2.append(result_user2[i])
        else:
            ignored_count += 1
    logging.info("Unknown ignored count: {}".format(ignored_count))
    return labeling_results1, labeling_results2


def _construct_kappa_analysis_link_dict(kappa_matrices, task_id):
    kappa_analysis_links_dict = PrettyDefaultDict(
        lambda: PrettyDefaultDict(lambda: str)
    )
    for label, df in kappa_matrices.items():
        columns = list(df.columns)
        index = list(df.index.values)
        for i in range(len(columns)):
            user1 = columns[i]
            for j in range(len(index)):
                user2 = index[j]
                if user1 != user2:
                    kappa_analysis_links_dict[label][
                        (user1, user2)
                    ] = generate_annotation_server_compare_link(
                        task_id=task_id,
                        label=label,
                        users_dict={"user1": user1, "user2": user2},
                    )
    return kappa_analysis_links_dict


def _construct_comparison_df(dbsession, label: str, users_to_compare: List):
    res = (
        dbsession.query(distinct(ClassificationAnnotation.entity))
        .filter(ClassificationAnnotation.label == label)
        .order_by(ClassificationAnnotation.entity.asc())
        .all()
    )

    distinct_entities_under_label = [item[0] for item in res]

    comparison_df = pd.DataFrame(
        {
            user: [str(np.NaN)] * len(distinct_entities_under_label)
            for user in users_to_compare
        },
        index=list(distinct_entities_under_label),
    )

    annotation_id_per_user_df = comparison_df.copy(deep=True)

    for user in users_to_compare:
        entity_value_id_tuple = (
            dbsession.query(
                ClassificationAnnotation.entity,
                ClassificationAnnotation.value,
                ClassificationAnnotation.id,
            )
            .filter(ClassificationAnnotation.label == label, User.username == user)
            .join(User)
            .order_by(ClassificationAnnotation.entity.asc())
            .all()
        )
        entities = [pair[0] for pair in entity_value_id_tuple]
        values = [str(pair[1]) for pair in entity_value_id_tuple]
        user_df = pd.DataFrame({user: values}, index=entities)
        comparison_df.update(user_df)

        ids = [str(pair[2]) for pair in entity_value_id_tuple]
        id_df = pd.DataFrame({user: ids}, index=entities)
        annotation_id_per_user_df.update(id_df)

    comparison_df["contentious_level"] = comparison_df.apply(
        lambda row: _compute_contentious_level(row), axis=1
    )

    comparison_df.sort_values(by="contentious_level", inplace=True, ascending=False)
    sorted_index = comparison_df.index
    annotation_id_per_user_df = annotation_id_per_user_df.reindex(sorted_index)

    comparison_df = comparison_df.drop(columns=["contentious_level"])

    return comparison_df, annotation_id_per_user_df


def _compute_contentious_level(row):
    """The maximum contentious level is one meaning we have an equal
    split among the annotators while the minimum level is 1/(len(users) + 1)"""
    values = row.values.tolist()
    stats = PrettyDefaultDict(int)
    for val in values:
        stats[str(val)] += 1

    # We are only considering positives and negatives.
    positives = stats[str(AnnotationValue.POSITIVE)]
    negatives = stats[str(AnnotationValue.NEGTIVE)]

    ratio = len(values) + 1
    if positives > 0 and negatives > 0:
        ratio = (
            positives / negatives if positives >= negatives else negatives / positives
        )
    return 1 / ratio
