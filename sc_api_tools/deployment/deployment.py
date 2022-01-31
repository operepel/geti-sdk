import json
import os
from typing import List, Union, Optional, Dict, Any

import attr

import numpy as np

from sc_api_tools.data_models import Project, Task, TaskType, Prediction, Label
from sc_api_tools.data_models.enums import OpenvinoModelName
from sc_api_tools.deployment.data_models import ROI, IntermediateInferenceResult
from sc_api_tools.deployment.deployed_model import DeployedModel
from sc_api_tools.deployment.prediction_converters import (
    convert_classification_output,
    convert_detection_output,
    convert_anomaly_classification_output
)
from sc_api_tools.rest_converters import ProjectRESTConverter


@attr.s(auto_attribs=True)
class Deployment:
    """
    This class represents a deployed SC project that can be used to run inference
    locally
    """
    project: Project
    models: List[DeployedModel]

    def __attrs_post_init__(self):
        """
        Initializes private attributes
        """
        self._is_single_task: bool = len(self.project.get_trainable_tasks()) == 1
        self._are_models_loaded: bool = False

    @property
    def is_single_task(self) -> bool:
        """
        Returns True if the deployment represents a project with only a single task

        :return: True if the deployed project contains only one trainable task, False
            if it is a pipeline project
        """
        return self._is_single_task

    @property
    def are_models_loaded(self) -> bool:
        """
        Returns True if all inference models for the Deployment are loaded and ready
        to infer

        :return: True if all inference models for the deployed project are loaded in
            memory and ready for inference
        """
        return self._are_models_loaded

    def save(self, path_to_folder: Union[str, os.PathLike]):
        """
        Saves the Deployment instance to a folder on local disk

        :param path_to_folder: Folder to save the deployment to
        """
        project_dict = ProjectRESTConverter.to_dict(self.project)
        deployment_folder = os.path.join(path_to_folder, 'deployment')

        if not os.path.exists(deployment_folder):
            os.makedirs(deployment_folder)
        # Save project data
        project_filepath = os.path.join(deployment_folder, 'project.json')
        with open(project_filepath, 'w') as project_file:
            json.dump(project_dict, project_file)
        # Save model for each task
        for task, model in zip(self.project.get_trainable_tasks(), self.models):
            model_dir = os.path.join(deployment_folder, task.title)
            if not os.path.exists(model_dir):
                os.makedirs(model_dir)
            model.save(model_dir)

    @classmethod
    def from_folder(cls, path_to_folder: Union[str, os.PathLike]) -> 'Deployment':
        """
        Creates a Deployment instance from a specified `path_to_folder`

        :param path_to_folder: Path to the folder containing the Deployment data
        :return: Deployment instance corresponding to the deployment data in the folder
        """
        deployment_folder = path_to_folder
        if not path_to_folder.endswith("deployment"):
            if 'deployment' in os.listdir(path_to_folder):
                deployment_folder = os.path.join(path_to_folder, 'deployment')
            else:
                raise ValueError(
                    f"No `deployment` folder found in the directory at "
                    f"`{path_to_folder}`. Unable to load Deployment."
                )
        project_filepath = os.path.join(deployment_folder, 'project.json')
        with open(project_filepath, 'r') as project_file:
            project_dict = json.load(project_file)
        project = ProjectRESTConverter.from_dict(project_dict)
        task_folder_names = [task.title for task in project.get_trainable_tasks()]
        models: List[DeployedModel] = []
        for task_folder in task_folder_names:
            models.append(
                DeployedModel.from_folder(os.path.join(deployment_folder, task_folder))
            )
        return cls(models=models, project=project)

    def load_inference_models(self, device: str = 'CPU'):
        """
        Loads the inference models for the deployment to the specified device

        :param device: Device to load the inference models to
        """
        for model, task in zip(self.models, self.project.get_trainable_tasks()):
            model_name = self._get_model_name(model, task)

            # Load additional model configuration from the hyper parameters, if needed
            configuration: Optional[Dict[str, Any]] = None
            if task.type == TaskType.SEGMENTATION:
                if model_name == OpenvinoModelName.BLUR_SEGMENTATION:
                    threshold_name = 'soft_threshold'
                    blur_name = 'blur_strength'
                    configuration = {
                        threshold_name: model.hyper_parameters.get_parameter_by_name(
                            threshold_name
                        ).value,
                        blur_name: model.hyper_parameters.get_parameter_by_name(
                            blur_name
                        ).value
                    }

            model.load_inference_model(
                model_name=model_name, device=device, configuration=configuration
            )
        self._are_models_loaded = True

    def infer(self, image: np.ndarray) -> Union[np.ndarray, Prediction]:
        """
        Runs inference on an image for the full model chain in the deployment

        NOTE: For now this is not supported for a detection -> segmentation pipeline
        project

        :param image: Image to run inference on
        :return: inference results
        """
        if self.is_single_task:
            return self._infer_task(image, task=self.project.get_trainable_tasks()[0])

        previous_labels: Optional[List[Label]] = None
        intermediate_result: Optional[IntermediateInferenceResult] = None
        rois: Optional[List[ROI]] = None
        image_views: Optional[List[np.ndarray]] = None
        for task in self.project.pipeline.tasks[1:]:
            # First task in the pipeline generates the initial result and ROIs
            if task.is_trainable and previous_labels is None:
                task_prediction = self._infer_task(image, task=task)
                rois: Optional[List[ROI]] = None
                if not task.is_global:
                    rois = [
                        ROI.from_annotation(annotation)
                        for annotation in task_prediction.annotations
                    ]
                intermediate_result = IntermediateInferenceResult(
                    image=image,
                    prediction=task_prediction,
                    rois=rois
                )
                previous_labels = [label for label in task.labels if not label.is_empty]
            # Downstream trainable tasks
            elif task.is_trainable:
                if task.type == TaskType.SEGMENTATION:
                    raise NotImplementedError(
                        f"Unable to run inference for the pipeline in the deployed "
                        f"project: Inferring downstream segmentation tasks is not "
                        f"supported yet"
                    )
                if rois is None or image_views is None or intermediate_result is None:
                    raise NotImplementedError(
                        f"Unable to run inference for the pipeline in the deployed "
                        f"project: A flow control task is required between each "
                        f"trainable task in the pipeline."
                    )
                new_rois: List[ROI] = []
                for roi, view in zip(rois, image_views):
                    view_prediction = self._infer_task(view, task)
                    for annotation in view_prediction.annotations:
                        intermediate_result.append_annotation(annotation, roi=roi)
                        if not task.is_global:
                            new_rois.append(ROI.from_annotation(annotation))
                    intermediate_result.rois = [
                        new_roi.to_absolute_coordinates(parent_roi=roi)
                        for new_roi in new_rois
                    ]
            # Downstream flow control tasks
            else:
                if previous_labels is None:
                    raise NotImplementedError(
                        f"Unable to run inference for the pipeline in the deployed "
                        f"project: First task in the pipeline after the DATASET task "
                        f"has to be a trainable task, found task of type {task.type} "
                        f"instead."
                    )
                # CROP task
                if task.type == TaskType.CROP:
                    rois = intermediate_result.filter_rois(label=None)
                    image_views = intermediate_result.generate_views(rois)
                else:
                    raise NotImplementedError(
                        f"Unable to run inference for the pipeline in the deployed "
                        f"project: Unsupported task type {task.type} found."
                    )
        return intermediate_result.prediction

    def _infer_task(
            self, image: np.ndarray, task: Task
    ) -> Union[Prediction, np.ndarray]:
        """
        Runs pre-processing, inference, and post-processing on the input `image`, for
        the model associated with the `task`

        :param image: Image to run inference on
        :param task: Task to run inference for
        :return: Inference result
        """
        model = self._get_model_for_task(task)
        preprocessed_image, metadata = model.preprocess(image)
        inference_results = model.infer(preprocessed_image)
        postprocessing_results = model.postprocess(
            inference_results, metadata=metadata
        )

        if task.type == TaskType.DETECTION:
            return convert_detection_output(
                    model_output=postprocessing_results,
                    image_width=image.shape[1],
                    image_height=image.shape[0],
                    labels=task.labels
                )
        elif task.type == TaskType.CLASSIFICATION:
            return convert_classification_output(
                model_output=postprocessing_results,
                labels=task.labels
            )
        elif task.type == TaskType.ANOMALY_CLASSIFICATION:
            return convert_anomaly_classification_output(
                model_output=postprocessing_results,
                anomalous_label=next(
                    (label for label in task.labels if label.name == 'Anomalous')
                ),
                normal_label=next(
                    (label for label in task.labels if label.name == 'Normal')
                )
            )
        else:
            return postprocessing_results

    @staticmethod
    def _get_model_name(model: DeployedModel, task: Task) -> OpenvinoModelName:
        """
        Returns the name of the openvino model corresponding to the deployed `model`

        :param model: DeployedModel to get the name for
        :param task: Task corresponding to the model
        :return: OpenvinoModelName instance corresponding to the model name for `model`
        """
        task_type = task.type
        if task_type == TaskType.DETECTION:
            return OpenvinoModelName.SSD
        elif task_type == TaskType.CLASSIFICATION:
            return OpenvinoModelName.OTE_CLASSIFICATION
        elif task_type == TaskType.ANOMALY_CLASSIFICATION:
            return OpenvinoModelName.ANOMALY_CLASSIFICATION
        elif task_type == TaskType.SEGMENTATION:
            model_name_parameter = model.hyper_parameters.get_parameter_by_name(
                "class_name"
            )
            return OpenvinoModelName(model_name_parameter.value)

    def _get_model_for_task(self, task: Task) -> DeployedModel:
        """
        Gets the DeployedModel instance corresponding to the input `task`

        :param task: Task to get the model for
        :return: DeployedModel corresponding to the task
        """
        try:
            task_index = self.project.get_trainable_tasks().index(task)
        except ValueError as error:
            raise ValueError(
                f"Task {task.title} is not in the list of trainable tasks for project "
                f"{self.project.name}."
            ) from error
        return self.models[task_index]