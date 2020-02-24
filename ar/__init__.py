# Annotation Request Module

import os
import shutil
import re
import glob
from typing import List
from collections import namedtuple

import numpy as np
from shared.utils import load_jsonl, save_jsonl, load_json, save_json, mkf, mkd
from db.task import Task, DIR_ANNO, DIR_AREQ
from inference.base import ITextCatModel
from inference import get_predicted
from inference.random_model import RandomModel

from .data import fetch_all_annotations
from .utils import get_ar_id

Pred = namedtuple('Pred', ['score', 'fname', 'line_number'])

def generate_annotation_requests(task_id, n=100, overlap=2):
    '''
    NOTE: This could be super slow, but that's okay for now!
    '''
    task = Task.fetch(task_id)

    print("Get prediction from each model...")
    # TODO better to stream these?

    _examples = []
    _proportions = []

    # Random Examples
    _examples.append(
        _get_predictions(task.get_full_data_fnames(), [RandomModel()], cache=False)
    )
    _proportions.append(1)

    # Pattern-driven Examples
    _patterns_model = task.get_pattern_model()
    if _patterns_model:
        _examples.append(
            _get_predictions(task.get_full_data_fnames(), [_patterns_model], cache=True)
        )
        _proportions.append(3) # [1,3] -> [0.25, 0.75]
    
    print("Shuffling together examples...")
    ordered_examples = _shuffle_together_examples(_examples, proportions=_proportions)

    # Blacklist whatever users have labeled already
    blacklist_fn = _build_blacklist_fn(task)

    print("Assigning to annotators...")
    assignments = _assign(ordered_examples, task.annotators, blacklist_fn=blacklist_fn, max_per_annotator=n, max_per_dp=overlap)

    # ---- Populate Cache ----

    # We will need random access for each line in each file.
    __cache_df = {}
    for fname in task.get_full_data_fnames():
        __cache_df[fname] = load_jsonl(fname)
    def get_dp(fname, line_number):
        '''Get Datapoint'''
        return __cache_df[fname].iloc[line_number]

    # It's faster to get decorated examples in batch. 
    __examples = set()
    for annotator, list_of_examples in assignments.items():
        for pred in list_of_examples:
            __examples.add(pred)
    __examples = list(__examples)

    # Basic decorations
    # Also generate a __text_list to be used for other decorators.
    __basic_decor = []
    __text_list = []
    for p in __examples:
        row = get_dp(p.fname, p.line_number)
        __basic_decor.append({
            'text': row['text'],
            'meta': row['meta']
        })
        __text_list.append(row['text'])

    # Pattern decorations
    if task.get_pattern_model():
        __pattern_decor = task.get_pattern_model().predict(__text_list, fancy=True)
    else:
        __pattern_decor = None

    # Build up a dict for random access
    __example_idx_lookup = dict(zip(__examples, range(len(__examples))))

    def get_decorated_example(pred:Pred):
        idx = __example_idx_lookup[pred]

        ar_id = get_ar_id(pred.fname, pred.line_number)
        res = {
            'ar_id': ar_id,
            'fname': pred.fname,
            'line_number': pred.line_number,
            'score': pred.score,
        }
        res.update({
            'data': __basic_decor[idx]
        })
        if __pattern_decor is not None:
            res.update({
                'pattern_info': __pattern_decor[idx]
            })
        return res

    # ---- Populate Annotation Requests per Annotator ----

    print("Constructing requests...")
    annotation_requests = {}
    for user, list_of_examples in assignments.items():

        decorated_list_of_examples = [get_decorated_example(ex)
                                      for ex in list_of_examples]

        annotation_requests[user] = decorated_list_of_examples

    print("Finished generating annotation requests.")
    return annotation_requests

def _build_blacklist_fn(task:Task):
    _lookup = {
        user: set(fetch_all_annotations(task.task_id, user))
        for user in task.annotators
    }        

    # blacklist_fn = lambda thing, user : False
    def blacklist_fn(pred:Pred, annotator:str):
        ar_id = get_ar_id(pred.fname, pred.line_number)
        return ar_id in _lookup[annotator]

    return blacklist_fn

def _get_predictions(data_filenames:List[str], models:List[ITextCatModel], cache=True):
    '''
    Return the aggregated score from all models for all lines in each data_filenames

    Return Pred namedtuple (score, fname, line_number)
    '''
    result = []

    for fname in data_filenames:
        preds = []

        for model in models:
            res = get_predicted(fname, model, cache=cache)
            preds.append( [x['score'] for x in res] )

        if len(preds) > 0:
            # Get total score from all models.
            total_scores = np.sum(preds, axis=0)

            for line_number, score in enumerate(total_scores):
                result.append( Pred(score, fname, line_number) )

    return result

def _assign(datapoints:List, annotators:List, blacklist_fn=None, max_per_annotator=100, max_per_dp=2):
    '''
    Args:
        datapoints: A list of data points to assign to each annotator.
        annotators: A list of annotators.
        blacklist_fn: fn(datapoint, annotator) that returns if an annotator has previously annotated this thing.
        max_per_annotator: How many datapoints should each annotator strive to have.
        max_per_dp: How many annotators should each datapoint strive to have.
    Returns:
        Assignment in the form of:
        {
            annotator:  list of datapoints
            ...
        }
    '''
    if blacklist_fn is None:
        blacklist_fn = lambda datapoint, annotator : False

    from queue import PriorityQueue
    from collections import defaultdict

    anno_q = PriorityQueue()
    for anno in annotators:
        # Each annotator starts off with 0 datapoint assigned
        anno_q.put( (0, anno) )

    per_dp_queue = defaultdict(list)
    per_anno_queue = defaultdict(list)

    def is_valid(anno, dp):
            if anno in per_dp_queue[dp]:
                # This datapoint already assigned to this annotator
                return False
            if blacklist_fn(dp, anno):
                # User specified function to not allow this
                return False
            if len(per_anno_queue[anno]) >= max_per_annotator:
                # This annotator has too many datapoints to label already 
                return False
            return True

    def get_next_anno(dp):
        put_back = []
        ret_anno = None

        while not anno_q.empty():
            item = anno_q.get()
            anno = item[1]

            if is_valid(anno, dp):
                ret_anno = anno
                break
            else:
                put_back.append(item)

        for item in put_back:
            anno_q.put(item)
        
        return ret_anno
    
    for dp in datapoints:
        for i in range(max_per_dp):
            anno = get_next_anno(dp)
            # print(dp, i, anno)
            if anno is None:
                # No more possible users to annotate this
                break
            else:
                per_dp_queue[dp].append(anno)
                per_anno_queue[anno].append(dp)
                anno_q.put( (len(per_anno_queue[anno]), anno) )
    
    # TODO insert random jobs to trade explore/exploit?

    return per_anno_queue

def _shuffle_together_examples(list_of_examples:List[List[Pred]], proportions:List[float]):
    '''
    Randomly shuffle together lists of Pred, such that at any length, the proportion of elements
    from each list is approximately `proportions`.
    '''

    # Sort each list from top to bottom
    list_of_examples = [sorted(x, key=lambda pred: pred.score, reverse=True) for x in list_of_examples]

    res = []
    seen = set()
    list_idx = [0 for _ in range(len(list_of_examples))] # Current index into each list

    proportions = np.array(proportions)
    proportions = proportions / np.sum(proportions)

    # O(total_n)
    total_n = sum([len(x) for x in list_of_examples])

    for _ in range(total_n):
        which_list = np.argmax(np.random.multinomial(1, proportions, size=1), axis=1)[0]
        ls = list_of_examples[which_list]
        idx = list_idx[which_list]
        
        if idx < len(ls):
            pred = ls[idx]
            list_idx[which_list] += 1
            
            if list_idx[which_list] == len(ls):
                # We've exhausted one list, reshuffle the proportions
                proportions[which_list] = 0

                if np.isclose(np.sum(proportions), 0):
                    # We're done! Nothing more to sample.
                    # print("Done")
                    # break # No need to explicitly break...
                    pass
                else:
                    # Normalize
                    proportions = proportions / np.sum(proportions)

            if (pred.fname, pred.line_number) not in seen:
                seen.add( (pred.fname, pred.line_number) )
                # TODO keep track of source of pred as well, for easier debugging
                res.append(pred)

    # assert np.isclose(np.sum(proportions), 0) # Should be always true, but not needed...
    return res


if __name__ == '__main__':
    # Round robin
    datapoints = ['a', 'b', 'c']
    annotators = ['u1', 'u2']
    per_anno_queue = _assign(datapoints, annotators, max_per_annotator=2, max_per_dp=1)
    expected = {
        'u1': ['a', 'c'],
        'u2': ['b']
    }
    assert per_anno_queue == expected, per_anno_queue

    # Unlimited budget
    datapoints = ['a', 'b', 'c']
    annotators = ['u1', 'u2']
    per_anno_queue = _assign(datapoints, annotators, max_per_annotator=999, max_per_dp=999)
    expected = {
        'u1': ['a', 'b', 'c'],
        'u2': ['a', 'b', 'c']
    }
    assert per_anno_queue == expected, per_anno_queue

    # Limited by max_per_annotator
    datapoints = ['a', 'b', 'c']
    annotators = ['u1', 'u2']
    per_anno_queue = _assign(datapoints, annotators, max_per_annotator=2, max_per_dp=2)
    expected = {
        'u1': ['a', 'b'],
        'u2': ['a', 'b']
    }
    assert per_anno_queue == expected, per_anno_queue

    # Limited by max_per_dp
    datapoints = ['a', 'b', 'c']
    annotators = ['u1', 'u2']
    per_anno_queue = _assign(datapoints, annotators, max_per_annotator=2, max_per_dp=1)
    expected = {
        'u1': ['a', 'c'],
        'u2': ['b']
    }
    assert per_anno_queue == expected, per_anno_queue

    # Blacklist
    datapoints = ['a', 'b', 'c']
    annotators = ['u1', 'u2']
    blacklist_fn = lambda dp, anno : (dp == 'a' and anno == 'u1')
    per_anno_queue = _assign(datapoints, annotators, max_per_annotator=999, max_per_dp=999, blacklist_fn=blacklist_fn)
    expected = {
        'u1': ['b', 'c'],
        'u2': ['a', 'b', 'c']
    }
    assert per_anno_queue == expected, per_anno_queue

    list_of_examples = [
        [
            Pred(0.31, 'a', 1),
            Pred(0.34, 'a', 2),
            Pred(0.32, 'a', 3),
            Pred(0.39, 'a', 4),
        ],
        [
            Pred(0.51, 'a', 1),
            Pred(0.54, 'a', 2),
            Pred(0.53, 'a', 3),
            Pred(0.59, 'a', 4),
            Pred(0.53, 'a', 5),
        ]
    ]
    print(_shuffle_together_examples(list_of_examples, proportions=[0.8, 0.2]))