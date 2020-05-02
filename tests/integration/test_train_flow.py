from tests.sqlalchemy_conftest import *
from typing import List
import os
import numpy as np

from db.model import (
    Task, ClassificationAnnotation, User, EntityTypeEnum
)
from db.fs import RAW_DATA_DIR

from train.no_deps.run import (
    train_model, inference
)
from train.no_deps.paths import (
    # Train Model
    _get_data_parser_fname,
    _get_metrics_fname,
    # Model Inference
    _get_inference_fname,
)
from train.no_deps.inference_results import InferenceResults
from train.no_deps.utils import BINARY_CLASSIFICATION

from train.prep import prepare_task_for_training

from shared.utils import save_jsonl, load_jsonl, load_json

LABEL = 'IsTall'

# TODO add a case to cover only 1 class present in the data.
# This is easy to do, just set N=2.
# Unclear what's the best way to surface that error just yet.


class stub_model:
    def predict(self, text: List[str]):
        preds = np.array([1] * len(text))
        # This is the style when "Sliding Window" is enabled
        probs = [np.array([[-0.48803285,  0.56392884]],
                          dtype=np.float32)] * len(text)
        return preds, probs


def stub_train_fn(X, y, config):
    return stub_model()


def stub_build_fn(config, model_dir):
    return stub_model()


def _populate_db_and_fs(dbsession, tmp_path, N):
    # =========================================================================
    # Add in a fake data file
    d = tmp_path / RAW_DATA_DIR
    d.mkdir(parents=True)
    p = d / 'data.jsonl'
    data = [{'text': f'item {i} text', 'meta': {'domain': f'{i}.com'}}
            for i in range(N)]
    save_jsonl(str(p), data)

    # =========================================================================
    # Create dummy data

    # Create many Users
    user = User(username=f'someuser')
    dbsession.add(user)

    dbsession.commit()

    # Create many Annotations for a Label
    def _create_anno(ent, v): return ClassificationAnnotation(
        entity_type=EntityTypeEnum.COMPANY, entity=ent, user=user,
        label=LABEL, value=v)

    ents = [d['meta']['domain'] for d in data]
    annos = [
        # Create a few annotations for the first 2 entities.
        _create_anno(ents[0], 1),
        _create_anno(ents[0], 1),
        _create_anno(ents[0], 1),
        _create_anno(ents[0], -1),
        _create_anno(ents[0], 0),
        _create_anno(ents[0], 0),
        _create_anno(ents[0], 0),
        _create_anno(ents[0], 0),

        _create_anno(ents[1], 1),
        _create_anno(ents[1], 1),
        _create_anno(ents[1], -1),
        _create_anno(ents[1], -1),
        _create_anno(ents[1], -1),
        _create_anno(ents[1], -1),
        _create_anno(ents[1], 0),
        _create_anno(ents[1], 0),
    ]
    for i in range(2, N):
        # Create one annotations for the rest of the entities.
        annos.append(_create_anno(ents[i], 1 if i % 2 else -1))

    dbsession.add_all(annos)
    dbsession.commit()

    # Create a Task
    task = Task(name='Bball')
    task.set_labels([LABEL])
    task.set_annotators([user.username])
    task.set_patterns_file(None)
    task.set_patterns(['Shaq', 'Lebron'])
    task.set_data_filenames(['data.jsonl'])
    dbsession.add(task)
    dbsession.commit()


def test_train_flow(dbsession, monkeypatch, tmp_path):
    monkeypatch.setenv('ALCHEMY_FILESTORE_DIR', str(tmp_path))
    N = 20
    _populate_db_and_fs(dbsession, tmp_path, N)
    task = dbsession.query(Task).first()

    # Part 1. Prepare.
    model = prepare_task_for_training(dbsession, task.id)
    model_dir = model.dir(abs=True)

    # These are all the files we need to train a model.
    files = os.listdir(model_dir)
    assert set(files) == set(['data.jsonl', 'config.json'])

    data = load_jsonl(os.path.join(model_dir, 'data.jsonl'), to_df=False)
    data = sorted(data, key=lambda d: d['text'])
    print(data[0])
    print(data[1])
    print(len(data))
    assert data[0] == {'text': 'item 0 text', 'labels': {'IsTall': 1}}
    assert data[1] == {'text': 'item 1 text', 'labels': {'IsTall': -1}}
    assert len(data) == 20

    config = load_json(os.path.join(model_dir, 'config.json'))
    assert config is not None
    assert config['train_config'] is not None

    # Part 2. Train model.
    train_model(model_dir, train_fn=stub_train_fn)

    data_parser_results = load_json(_get_data_parser_fname(model_dir))
    assert data_parser_results['problem_type'] == BINARY_CLASSIFICATION

    metrics = load_json(_get_metrics_fname(model_dir))
    assert metrics['test'] is not None
    assert metrics['train'] is not None

    # Part 3. Post-training Inference.
    f = tmp_path / 'tmp_file_for_inference.jsonl'
    save_jsonl(str(f), [
        {'text': 'hello'},
        {'text': 'world'}
    ])
    fnames = [str(f)]

    inference(model_dir, fnames,
              build_model_fn=stub_build_fn, generate_plots=False)

    ir = InferenceResults.load(
        _get_inference_fname(model_dir, fnames[0]))
    assert np.isclose(ir.probs, [0.7411514, 0.7411514]).all()
