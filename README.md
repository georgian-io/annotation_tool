![CI](https://github.com/georgianpartners/annotation_tool/workflows/CI/badge.svg)
[![codecov](https://codecov.io/gh/georgianpartners/annotation_tool/branch/master/graph/badge.svg?token=DR90HIIVYF)](https://codecov.io/gh/georgianpartners/annotation_tool)

# Getting Started

Create an `.env` file or pass in your own environment vars to override configuration. See `.env.example`.

e.g.

```
env ANNOTATION_TOOL_MAX_PER_ANNOTATOR=200 ci/run_server.sh annotation_server
```


Or use the --env or --env-file args for Docker.

Descriptions of the env vars:

- `ANNOTATION_TOOL_ANNOTATION_SERVER_SERVER`: URL of annotation server, e.g. `http://127.0.0.1:5001`.
- `ANNOTATION_TOOL_INFERENCE_CACHE_DIR`: Where some model inference are cached. Default is `./__infcache`
- `ANNOTATION_TOOL_MAX_PER_ANNOTATOR`: How many examples to assign to each annotator in a batch. Default is 100.
- `ANNOTATION_TOOL_MAX_PER_DP`: How many annotators should see the same example. Default is 3.
- `TRANSFORMER_MAX_SEQ_LENGTH`: Max sequence length - longer means more accurate models but longer training time and memory requirements. Setting to 128 is usually good enough for small machines. Default is 512.
- `TRANSFORMER_TRAIN_EPOCHS`: Default number of epochs to train. Default is 5.
- `TRANSFORMER_SLIDING_WINDOW`: If a sequence is too long (longer than `TRANSFORMER_MAX_SEQ_LENGTH`), should we use a sliding window to average out the result. We don't always see better performance with this turned on. Default is "False".
- `TRANSFORMER_TRAIN_BATCH_SIZE`: Training batch size. Default is 8.
- `TRANSFORMER_EVAL_BATCH_SIZE`: Prediction batch size. Default is 8.
- `GOOGLE_AI_PLATFORM_ENABLED`: Whether to use Google AI Platform for training. Default is False.
- `GOOGLE_AI_PLATFORM_BUCKET`: Distributed Training - bucket to store data.
- `GOOGLE_AI_PLATFORM_DOCKER_IMAGE_URI`: Distributed Training - pre-built training image URI.
- `CLOUDSDK_COMPUTE_REGION`: The GCP region, e.g. "us-central1". You must set this in order for Google AI Platform to work.
- `GCP_PROJECT_ID`: The id of the current project on GCP.
- `DB_URL_FOR_MIGRATION`: The link to the database instance when running migration.
- `ADMIN_SERVER_LOGGER`: The logger name for the alchemy admin server.
- `ANNOTATION_SERVER_LOGGER`: The logger name for the alchemy annotation server.
- `INFERENCE_OUTPUT_PUBSUB_TOPIC_DEV`: The PubSub topic name for inference output on the dev stage.
- `INFERENCE_OUTPUT_PUBSUB_TOPIC_BETA`: The PubSub topic name for inference output on the beta stage.
- `INFERENCE_OUTPUT_PUBSUB_TOPIC_PROD`: The PubSub topic name for inference output on the prod stage.
- `ENV_STAGE`: Environment stage name.
- `API_TOKEN_NAME`: The secret name for the inference API token.
- `INFERENCE_OUTPUT_DATA_SOURCE_NAME_FOR_PUBSUB`: The inference output dataset source name for pubsub.
- `USE_CLOUD_LOGGING`: Use GCP logging instead of the default logging. If set to true, `ADMIN_SERVER_LOGGGER` and `ANNOTATION_SERVER_LOGGER` must be set properly.
- `ALCHEMY_FILESTORE_DIR`: Local filestore location.
- `ALCHEMY_DATABASE_URI`: The URI of SQL database.
- `ALCHEMY_ENV`: The environemnt the server is running in.
- `API_TOKEN`: API token for /api/* calls.
- `FLOWER_BASIC_AUTH`: Basic auth for the Celery monitoring UI, Flower. Set to `foo:bar` so foo is the username and bar is the password.
- `CELERY_BROKER_URL`: Full URL to the message broker used by celery.
- `SECRET_KEY`: The key used for encrypting session cookies
- `SAML_METADATA_URL`: Path to metadata xml file in case of using `saml` authentication backend.
- `ANNOTATION_TOOL_ADMIN_SERVER_PASSWORD`: The password to use in case of using `basic_auth` authentication backend.

# Development
## Running the code
You can use the provided docker-compose file to run the dev server. 

```bash
docker-compose up -d
```

Or use the run_server script directly outside the docker environment:

```
bash ci/run_server.sh \
        --flask-env local \
        --flask-host 127.0.0.1 \
        --flask-port 8080 \
        --database postgres://alchemy:pswd@localhost:5432/alchemy \
        [optional flask run flags here]
```

## Authentication in Development environment
Change the authentication backend to basic authentication.
Change the following setting in `admin_server/__init__.py` and `annotation_server/__init__.py`
from 

```python
'AUTH_BACKEND': 'alchemy.shared.auth_backends.saml'
```

to

```python
'AUTH_BACKEND': 'alchemy.shared.auth_backends.basic_auth'
```

The password for the login form is set by `ANNOTATION_TOOL_ADMIN_SERVER_PASSWORD`. 
Be careful not to commit this change over to production.

## Tests
You may run the tests using `ci/run_tests.sh` in a docker container, in ci, etc.
By default, it will look for tests in `tests/` directory, however you can also 
specify a certain directory or file to run. 
To provide additional arguments for `pytest` you can use `TEST_ARGS` environment variable.

```bash
[TEST_ARGS="--optional-args-here"] ci/run_tests.sh [/optional/path/to/test]
```

Here are a few examples:

```bash
$ docker exec alchemy-server source ci/run_tests.sh tests/integration
$ docker exec -it alchemy-server bash 
root:/app# chmod +x ci/run_tests.sh
root:/app# ci/run_tests.sh tests/unit/test_nlp_model.py
root:/app# TEST_ARGS="--setup-show" ci/run_tests.sh 
```

# Notes for production
## Building
You can submit cloud build jobs from your local development environment
using `ci/gcloud_build.sh` script. This script comes in handy particularly
when you need to build an image to manually deploy on staging server.
example usage:

```bash
ci/gcloud_build.sh -t production
ci/gcloud_build.sh -t production -t staging --async
```

## Exposing Port on Google Cloud
Add a Firewall group, then tag your instance with that group.
