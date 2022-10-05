# Copyright (C) 2022 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions
# and limitations under the License.
import copy
import os

import pytest

from geti_sdk.data_models import Algorithm, Project, TaskType
from geti_sdk.utils import (
    deserialize_dictionary,
    get_server_details_from_env,
    get_supported_algorithms,
)
from geti_sdk.utils.serialization_helpers import DataModelMismatchException
from tests.fixtures.geti import DUMMY_PASSWORD, DUMMY_USER
from tests.helpers.constants import DUMMY_HOST


class TestUtils:
    @pytest.mark.vcr()
    def test_get_supported_algorithms(self, fxt_geti_session):
        """
        Verifies that getting the list of supported algorithms from the server works
        as expected

        Test steps:
        1. Retrieve a list of supported algorithms from the server
        2. Assert that the returned list is not emtpy
        3. Assert that each entry in the list is a properly deserialized Algorithm
            instance
        4. Filter the AlgorithmList to select only the classification algorithms from
            it
        5. Assert that the list of classification algorithms is not empty and that
            each algorithm in it has the proper task type
        """
        algorithms = get_supported_algorithms(fxt_geti_session)

        assert len(algorithms) > 0
        for algorithm in algorithms:
            assert isinstance(algorithm, Algorithm)

        classification_algos = algorithms.get_by_task_type(
            task_type=TaskType.CLASSIFICATION
        )
        assert len(classification_algos) > 0
        for algorithm in classification_algos:
            assert algorithm.task_type == TaskType.CLASSIFICATION

    def test_deserialize_dictionary(self, fxt_project_dictionary: dict):
        """
        Verifies that deserializing a dictionary to a python object works.

        Also tests that a DataModelMismatchException is raised in case:
            1. the input dictionary contains an invalid key
            2. the input dictionary misses a required key
        """
        object_type = Project
        project = deserialize_dictionary(
            input_dictionary=fxt_project_dictionary, output_type=object_type
        )
        assert project.name == fxt_project_dictionary["name"]
        assert project.get_trainable_tasks()[0].type == TaskType.DETECTION

        dictionary_with_extra_key = copy.deepcopy(fxt_project_dictionary)
        dictionary_with_extra_key.update({"invalid_key": "invalidness"})
        with pytest.raises(DataModelMismatchException):
            deserialize_dictionary(
                input_dictionary=dictionary_with_extra_key, output_type=object_type
            )

        dictionary_with_missing_key = copy.deepcopy(fxt_project_dictionary)
        dictionary_with_missing_key.pop("pipeline")
        with pytest.raises(DataModelMismatchException):
            deserialize_dictionary(
                input_dictionary=dictionary_with_extra_key, output_type=object_type
            )

    def test_get_server_details_from_env(self, fxt_env_filepath: str):
        """
        Verifies that fetching server details from a .env file works.

        This also tests that getting the server details from the global environment
        works as expected.
        """
        host, authentication_info = get_server_details_from_env(fxt_env_filepath)

        assert host == DUMMY_HOST
        assert authentication_info["token"] == "this_is_a_fake_token"
        assert len(authentication_info) == 1

        environ_keys = ["GETI_HOST", "GETI_USERNAME", "GETI_PASSWORD"]
        expected_results = {}
        dummy_results = {
            "GETI_HOST": DUMMY_HOST,
            "GETI_USERNAME": DUMMY_USER,
            "GETI_PASSWORD": DUMMY_PASSWORD,
        }
        for ekey in environ_keys:
            evalue = os.environ.get(ekey, None)
            if evalue is not None:
                expected_results.update({ekey: evalue})
            else:
                variable_dictionary = {ekey: dummy_results[ekey]}
                os.environ.update(variable_dictionary)
                expected_results.update(variable_dictionary)

        host, authentication_info = get_server_details_from_env(
            use_global_variables=True
        )
        assert host == expected_results["GETI_HOST"]
        assert authentication_info["username"] == expected_results["GETI_USERNAME"]
        assert authentication_info["password"] == expected_results["GETI_PASSWORD"]