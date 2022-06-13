import copy
from typing import Dict, Any, List

from .prediction_rest_converter import PredictionRESTConverter
from sc_api_tools.data_models import Prediction, Annotation
from sc_api_tools.rest_converters.annotation_rest_converter import (
    NormalizedAnnotationRESTConverter,
)
from sc_api_tools.data_models.predictions import ResultMedium


class NormalizedPredictionRESTConverter(PredictionRESTConverter):
    """
    This class implements methods for converting predictions in normalized format to
    and from their REST representation

    It is a legacy class to support the annotation format in a normalized coordinate
    system, which was used in SCv1.1 and below
    """

    @staticmethod
    def normalized_prediction_from_dict(
            prediction: Dict[str, Any], image_width: int, image_height: int
    ) -> Prediction:
        """
        Legacy method that creates an AnnotationScene object from a dictionary
        returned by the /annotations REST endpoint in SC versions 1.1 or below

        :param prediction: dictionary representing a Prediction, which
            contains all predictions for a certain media entity
        :param image_width: Width of the image to which the annotation scene applies
        :param image_height: Height of the image to which the annotation scene applies
        :return: Prediction object
        """
        input_copy = copy.deepcopy(prediction)
        media_identifier = NormalizedAnnotationRESTConverter._media_identifier_from_dict(
            prediction["media_identifier"]
        )
        annotations: List[Annotation] = []
        for annotation in prediction["annotations"]:
            annotations.append(
                NormalizedAnnotationRESTConverter.normalized_annotation_from_dict(
                    input_dict=annotation,
                    image_width=image_width,
                    image_height=image_height
                )
            )
        result_media: List[ResultMedium] = []
        for result_medium in prediction["maps"]:
            if not isinstance(result_medium, ResultMedium):
                result_media.append(ResultMedium(**result_medium))
            else:
                result_media.append(result_medium)
        input_copy.update(
            {
                "annotations": annotations,
                "media_identifier": media_identifier,
                "maps": result_media
            }
        )
        return Prediction(**input_copy)

    @staticmethod
    def to_normalized_dict(
            prediction: Prediction,
            image_width: int,
            image_height: int,
            deidentify: bool = True
    ) -> Dict[str, Any]:
        """
        Converts a Prediction to a dictionary. By default, removes any ID
        fields in the output dictionary

        :param prediction: Prediction object to convert
        :param image_width:
        :param image_height:
        :param deidentify: True to remove any unique database ID fields in the output,
            False to keep these fields. Defaults to True
        :return: Dictionary holding the serialized AnnotationScene data
        """
        return NormalizedAnnotationRESTConverter.to_normalized_dict(
            annotation_scene=prediction,
            image_height=image_height,
            image_width=image_width,
            deidentify=deidentify
        )
